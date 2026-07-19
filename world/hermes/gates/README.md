# Gate library — world/hermes/gates/

Track A, deliverable A1 of PORT-PLAN.md. Four executable gate scripts
that fit evo's gate contract (sdk-notes.md §3): each is a plain
command, exit 0 = pass, exit 1 = fail, exit 2 = misconfigured. None read
any `EVO_*` env var (cli.py:3232 strips them anyway).

All four were built under the RACE RULE (CHARTER.md §"THE RACE RULE"):
≥2 prior-art candidates per gate, pulled via GRAPH-FIRST
(world/backend/evo_graph.py find), cited in PRIOR-ART.md. Race
requests filed at `racetrack/requests/gate-<type>.md` for the lab loop
to run; results land in `racetrack/results/gate-<type>.md`.

## Files

| File | Phase | Purpose |
|---|---|---|
| correctness.py | post | golden-case assertion — first mismatch fails |
| budget.py | post | per-stage spend cap — ratchet OR absolute |
| regression.py | pre | parent-score cull — aborts before benchmark spend |
| held_out.py | post | generalization check — disjoint slice threshold |
| test_gates.py | — | self-tests, 15/15 green, pure stdlib, ~1s |
| PRIOR-ART.md | — | citations + race dimensions for all four gates |

## Usage

All scripts are `python3 <gate> ...` (stdlib only, no SDK import). In
an evo run, `{target}` and `{worktree}` are filled by evo when the gate
command runs (cli.py:2734 `_apply_runtime_prefix`).

### correctness.py — post-phase golden gate
```sh
python3 correctness.py \
    --golden golden/<stage>.jsonl \
    --solver "python3 {target}/solve.py" \
    --input-field input --expected-field expected
```
- `--golden` = JSONL, one `{id, input, expected}` per line.
- `--solver` = shell command; case's `input` is piped to stdin; stripped
  stdout must equal stripped `expected`.
- Exit 0 = all cases pass. Exit 1 = first mismatch (case id + diff on
  stderr). Exit 2 = golden file missing.

### budget.py — post-phase spend cap
Two modes (race: ratchet vs absolute, see PRIOR-ART.md §2):

Absolute (raven variant):
```sh
python3 budget.py --stage intake \
    --budget-file {worktree}/.evo/budget.json \
    --ceilings budgets.yaml
```
`budgets.yaml` accepts either flat or `stages:`-wrapped shape:
```yaml
stages:
  intake:
    tokens: 100000
    usd: 5.0
```

Ratchet (OmniRoute variant):
```sh
python3 budget.py --stage intake \
    --budget-file {worktree}/.evo/budget.json \
    --baseline baseline.json \
    --toleration-percent 2.0
```
- Missing field in `budget.json` = pass for that field (graceful
  degrade, adk-rust BaselineStore pattern).
- Exit 0 = under cap. Exit 1 = field exceeded. Exit 2 = misconfigured.

### regression.py — pre-phase parent-score cull
```sh
python3 regression.py \
    --parent-score parent_proxy.json \
    --current-score {worktree}/proxy_score.json \
    --field score --mode percent --tolerance 0.0
```
- `--mode absolute`: fail when `parent - current > tolerance`.
- `--mode percent` (default): fail when `(parent - current) / parent >
  tolerance`. Parent ≤ 0 falls back to absolute (zero-baseline is a
  signal, not an auto-pass).
- Missing parent file = PASS (no baseline → no regression, adk-rust
  graceful-skip). Missing current file = exit 2 (misconfigured).

### held_out.py — post-phase generalization check
```sh
python3 held_out.py \
    --held-out golden/<stage>.held_out.jsonl \
    --solver "python3 {target}/solve.py" \
    --threshold 0.7
```
- Score = fraction of cases where stripped(stdout) == stripped(expected).
- Exit 0 = score ≥ threshold. Exit 1 = below. Exit 2 = empty set or
  bad threshold.
- Default threshold 0.7 (ruvector `learned_weights_beat_chance_on_held_out`).

## Wiring into evo

Per sdk-notes.md §6, attach gates with `evo gate add`:
```sh
evo gate add <exp> correctness "python3 world/hermes/gates/correctness.py --golden ... --solver 'python3 {target}/solve.py'" --phase post
evo gate add <exp> budget      "python3 world/hermes/gates/budget.py --stage intake --budget-file {worktree}/.evo/budget.json --ceilings ..." --phase post
evo gate add <exp> regression  "python3 world/hermes/gates/regression.py --parent-score ... --current-score {worktree}/proxy_score.json" --phase pre
evo gate add <exp> held_out    "python3 world/hermes/gates/held_out.py --held-out ... --solver 'python3 {target}/solve.py'" --phase post
```
Inheritance is automatic: gates on a stage's root branch inherit to
all sub-stages (cli.py:2685 `_inherited_gate_specs`). Run order is
guaranteed by `_split_gates_by_phase` + the run flow in sdk-notes.md
§3d: **regression (pre) → benchmark → correctness + budget + held_out
(post) → keep decision.**

## Self-test

```sh
cd world/hermes/gates && python3 test_gates.py
```
15 tests, ~1s, stdlib only. Covers exit codes (0/1/2), graceful
degrade on missing baseline, ratchet vs absolute-cap, per-case solver
invocation, threshold semantics.

— hermes, 2026-07-19