# Brief — stage `review` — run asm-cli-stopwatch

Load the `evo:subagent` skill IN FULL before acting.

- **Objective**: Harden the winner: edge cases into golden/review.jsonl, docstrings, and a clean CLI surface. No behavior change to committed winners without a gate proving it.
- **Parent node**: the committed node of stage 'variants'
- **Boundaries / anti-patterns**:
  - Write ONLY within owned paths: src/, golden/review.jsonl, README.md (port of ownedPaths write-allowlist, enforced at integration).
  - Expected artifacts must exist when you finish: README.md.
  - Do NOT modify benchmark, gate, or framework code (subagent protocol rule).
  - Test profile is python-pytest — do not swap harnesses mid-run.
- **Pointer traces**: failing-task traces of stage 'variants''s committed node (`evo traces <exp_id> <task_id>`)

Iteration budget: 3

Gates in effect on this stage's branch (inherit down the tree):
  - regression (pre): `python3 world/hermes/gates/regression.py --parent-score .evo/parent_proxy.json --current-score {worktree}/proxy_score.json --field score --mode percent --tolerance 0.0`
  - correctness (post): `python3 world/hermes/gates/correctness.py --golden golden/review.jsonl --solver 'python3 {target}/src/cli_stopwatch.py'`
