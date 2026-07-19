# race: gate-correctness
seat: hermes
question: which correctness-gate pattern (golden-case-list vs golden-file-snapshot) is the better fit for evo's gate contract on this box?
metric: min seconds to gate a 50-case stage run
gate: exit 0 iff the gate's verdict matches a known-correct oracle across (a) all-pass set, (b) one-plant-wrong set, (c) empty/malformed set

## candidate: case-list
source: tests/fixtures/auto_harness_demo/gate.py:35-44 (this repo, evo-hq/evo upstream)
approach: hardcode a `GATE_TASKS` list of {request, expected}; iterate, run `module.solve(task)`, `sys.exit(1)` on first mismatch. Zero deps, plain `sys.exit`. This is evo's canonical gate pattern.

## candidate: file-snapshot
source: /library/repos/nocodb_nocodb/code/docker-compose/1_Auto_Upstall/tests/lib/helpers.bash:58
approach: bash helper `assert_golden`: normalize the generated artifact and `diff -u` it against a committed golden file; non-zero exit from `diff` fails. Snapshot = a fixed committed artifact, not a case list.