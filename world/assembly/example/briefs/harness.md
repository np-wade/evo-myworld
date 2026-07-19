# Brief — stage `harness` — run asm-cli-stopwatch

Load the `evo:subagent` skill IN FULL before acting.

- **Objective**: Build the proving ground: golden cases (golden/<stage>.jsonl, one {id,input,expected} per line), a disjoint held-out slice, and bench.py printing 'seconds: X' (metric min). Size CALLS_PER_REP so best-case runtime is well above the rounding unit (FIELD-NOTES 2026-07-19: score granularity).
- **Parent node**: the committed node of stage 'scaffold'
- **Boundaries / anti-patterns**:
  - Write ONLY within owned paths: golden/, bench.py, budgets.yaml (port of ownedPaths write-allowlist, enforced at integration).
  - Expected artifacts must exist when you finish: golden/harness.jsonl, golden/variants.held_out.jsonl, bench.py.
  - Do NOT modify benchmark, gate, or framework code (subagent protocol rule).
  - Test profile is python-pytest — do not swap harnesses mid-run.
- **Pointer traces**: failing-task traces of stage 'scaffold''s committed node (`evo traces <exp_id> <task_id>`)

Iteration budget: 3

Gates in effect on this stage's branch (inherit down the tree):
  - regression (pre): `python3 world/hermes/gates/regression.py --parent-score .evo/parent_proxy.json --current-score {worktree}/proxy_score.json --field score --mode percent --tolerance 0.0`
  - correctness (post): `python3 world/hermes/gates/correctness.py --golden golden/harness.jsonl --solver 'python3 {target}/src/cli_stopwatch.py'`
