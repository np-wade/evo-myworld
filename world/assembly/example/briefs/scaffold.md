# Brief — stage `scaffold` — run asm-cli-stopwatch

Load the `evo:subagent` skill IN FULL before acting.

- **Objective**: Build the smallest working cli-stopwatch: entry point src/cli_stopwatch.py implementing the core behavior of: a CLI stopwatch. Input on argv/stdin, result on stdout. Done when golden/scaffold.jsonl cases pass.
- **Parent node**: the baseline root (exp_0000) of this run
- **Boundaries / anti-patterns**:
  - Write ONLY within owned paths: src/ (port of ownedPaths write-allowlist, enforced at integration).
  - Expected artifacts must exist when you finish: src/cli_stopwatch.py.
  - Do NOT modify benchmark, gate, or framework code (subagent protocol rule).
  - Test profile is python-pytest — do not swap harnesses mid-run.
- **Pointer traces**: none — this is the baseline stage; study .evo/project.md instead

Iteration budget: 3

Gates in effect on this stage's branch (inherit down the tree):
  - correctness (post): `python3 world/hermes/gates/correctness.py --golden golden/scaffold.jsonl --solver 'python3 {target}/src/cli_stopwatch.py'`
