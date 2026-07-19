# world/assembly — build notes (Track A core port)

The assembly line reborn on evo primitives. One stdlib-only CLI
(`assembly.py`) with three commands: `plan` (idea -> plan.json), `brief`
(plan.json -> per-stage subagent briefs), `to-evo` (plan.json -> discover
seed + gate registration). Worked example under `example/` (idea:
"a CLI stopwatch"). Tests: `test_assembly.py`, 17 passed in 0.20s via
`uv run --no-project --with pytest pytest -q world/assembly/test_assembly.py`.

## Port map with citations (assembly-office file:line -> here)

| Ported concept | Source (projects/assembly-office/) | Landed as |
|---|---|---|
| Boss idea intake (one line, no pseudo-spec) | docs/HOW-ASSEMBLY-OFFICE-BUILDS-APPS.md:13-14; server.js:549-556 writes planner-input.json | `assembly.py plan "<idea>"` |
| Planner strict-JSON contract | lib/architecture.mjs:119-143 `plannerCliContract()`; required_output.fields at :131-137 (summary, assumptions, steps, risks, acceptance_criteria, handoffs) | plan.json top-level fields (test asserts them); AI-touchpoint fields dropped — evo products here are code-only |
| Deterministic plan draft (no LLM at draft time) | lib/station-roles.mjs:307-356 `draftPlanFromMission()` | `make_plan()` — deterministic, templated stages |
| Assigner node contract | lib/station-roles.mjs:393-453 `draftAssignmentsFromPlan()`; node fields at :395-408 (id, job, dependsOn, ownedPaths, expectedArtifacts, validationProfile) | `stages[]` entries carry the same fields (snake_case) |
| Narrow ownedPaths discipline | HOW-ASSEMBLY-OFFICE-BUILDS-APPS.md:108 + :342 ("['.'] disables useful scope separation") | every stage has narrow owned_paths; test forbids "." |
| Stations -> isolated worktrees | HOW doc :126-140 `executeRun()` worktree-per-station | each stage = an evo experiment worktree; brief's Boundaries field carries the write-allowlist |
| Scoped worker prompts | HOW doc :131 ("combines the Assigner prompt with worktree, ownership, research, artifact contracts") | `render_brief()` in evo's 4-field style: Objective / Parent node / Boundaries+anti-patterns / Pointer traces + iteration budget (evo-hq plugins/evo/skills/subagent/SKILL.md:57-64) |
| Oversight approvals + test profiles | lib/test-runner.mjs:8-33 `TEST_PROFILES` allowlist, :35-49 `inferTestProfile()` | gates from world/hermes/gates/ (correctness/budget/regression/held_out per gates/README.md) + `infer_profile()` allowlist (python-pytest, node-npm, rust-cargo, go-test) |
| Gate wiring into evo | evo-hq skills/references/cli-quick-reference.md:258 (`evo gate add ... --phase pre|post`); inheritance cli.py:2685; phase split cli.py:2699-2704 | `to-evo` emits one `evo gate add` per stage-root gate; regression is pre (cheap cull before benchmark spend, per hermes run-order note) |
| Boss idea -> headless run | FIELD-NOTES.md 2026-07-19 vanilla run ("Seeding the benchmark/metric in the discover prompt skips all interactive questions") | `to-evo` seed line `claude -p "/evo:discover ..."` with metric + profile baked in |

New capability (the point of the port, PORT-PLAN.md Track A): the `variants`
stage is an explicit RACE — its brief mandates >=2 sibling implementations
under one parent, same benchmark, same gates (budget + held_out added on top
of correctness), losers discarded. The factory stops being one-shot.

## Design decisions

- **Plan time vs integration time for profile inference.** assembly-office
  infers the test profile from lockfiles AFTER integration
  (test-runner.mjs:40-48). At `plan` time no repo exists yet, so
  `infer_profile()` keys on idea keywords / `--lang`, keeping the same
  allowlist discipline (unknown profile = hard error, mirroring :38).
- **Deterministic output, no timestamps.** `draftPlanFromMission` stamps
  `updated_at` (station-roles.mjs:354); dropped here so `plan` is a pure
  function of the idea — same input, same plan.json. That makes the bench
  comparison stable across lab-loop cycles and lets tests assert equality.
- **Gate selection is role-based**: every stage gets correctness (post);
  every non-root stage gets regression (pre, parent-score cull before
  benchmark spend); only the race stage gets budget + held_out. Rationale:
  SKILL.md:337 — "Do NOT gate every passing task — that over-constrains
  the search."

## RACE-RULE note

Two corpus approaches exist in assembly-office for turning an idea into an
approved plan: (1) the deterministic template draft
(`draftPlanFromMission`, lib/station-roles.mjs:307) and (2) LLM autopilot
normalization (`runAutopilotFlow`, lib/autopilot.mjs:54, treated as
untrusted input per HOW doc :90). **Took (1)** because this module must be
stdlib-only, offline, and bench-repeatable — an LLM call at plan time can't
run in `test_assembly.py` or the lab-loop bench cycle, and evo already
supplies the LLM layer downstream (`/evo:discover` consumes the seed; the
subagents do the thinking). Approach (2) is not culled from the ecosystem —
it IS the evo run this plan feeds. Not filed as a racetrack request: the
two candidates are not benchmarkable under one offline metric (one needs a
model), which fails RACETRACK.md's "small benchmark" requirement; the
choice + citations are recorded here instead per CHARTER's race-rule
escape hatch.

## Verified real output (to-evo on the example)

`python3 world/assembly/assembly.py to-evo world/assembly/example/plan.json`
emitted (full text in example/to-evo.txt):

```
claude -p "/evo:discover Build this product as an experiment tree: a CLI stopwatch. Stages in order: scaffold -> harness -> variants -> review. Benchmark: metric min, seconds per benchmark rep (bench.py prints 'seconds: X'). Test profile: python-pytest. The variants stage races >=2 sibling implementations under the same gates; losers are discarded. Correctness is asserted by gates, not by the benchmark."

evo gate add $EXP_SCAFFOLD --name correctness --command "python3 world/hermes/gates/correctness.py --golden golden/scaffold.jsonl --solver 'python3 {target}/src/cli_stopwatch.py'" --phase post
...
evo gate add $EXP_VARIANTS --name budget --command "python3 world/hermes/gates/budget.py --stage variants --budget-file {worktree}/.evo/budget.json --ceilings budgets.yaml" --phase post
evo gate add $EXP_VARIANTS --name held_out --command "python3 world/hermes/gates/held_out.py --held-out golden/variants.held_out.jsonl --solver 'python3 {target}/src/cli_stopwatch.py' --threshold 0.7" --phase post
```

(9 `evo gate add` lines total: scaffold 1, harness 2, variants 4, review 2.
Seed line verified shell-safe with `shlex.split` in the test suite.)

## Bench

`experiment.env` compares the raw idea line (A) against the planned output
(B). First real run: A exit=0 0.11s 1 line; B exit=0 0.11s 161 lines — the
diff is exactly what the module adds (stages, owned paths, gates, profile).

— assembly-port, 2026-07-19
