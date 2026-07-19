# Brief — stage `variants` — run asm-cli-stopwatch

Load the `evo:subagent` skill IN FULL before acting.

- **Objective**: THE RACE. Propose >=2 candidate implementations of the core operation (different algorithm/idiom/library), one sibling experiment each under this stage's node, same benchmark, same gates. Losers get discarded, winner is committed. Do not merge candidates.
- **Parent node**: the committed node of stage 'harness'
- **Boundaries / anti-patterns**:
  - Write ONLY within owned paths: src/ (port of ownedPaths write-allowlist, enforced at integration).
  - Expected artifacts must exist when you finish: src/cli_stopwatch.py.
  - Do NOT modify benchmark, gate, or framework code (subagent protocol rule).
  - Test profile is python-pytest — do not swap harnesses mid-run.
  - Anti-pattern: merging candidate implementations into one — each candidate is its own sibling experiment; the gate+score decides.
- **Pointer traces**: failing-task traces of stage 'harness''s committed node (`evo traces <exp_id> <task_id>`)

Iteration budget: 3

Gates in effect on this stage's branch (inherit down the tree):
  - regression (pre): `python3 world/hermes/gates/regression.py --parent-score .evo/parent_proxy.json --current-score {worktree}/proxy_score.json --field score --mode percent --tolerance 0.0`
  - correctness (post): `python3 world/hermes/gates/correctness.py --golden golden/variants.jsonl --solver 'python3 {target}/src/cli_stopwatch.py'`
  - budget (post): `python3 world/hermes/gates/budget.py --stage variants --budget-file {worktree}/.evo/budget.json --ceilings budgets.yaml`
  - held_out (post): `python3 world/hermes/gates/held_out.py --held-out golden/variants.held_out.jsonl --solver 'python3 {target}/src/cli_stopwatch.py' --threshold 0.7`
