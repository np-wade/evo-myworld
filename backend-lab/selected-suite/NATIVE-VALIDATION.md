# Native repository validation

Recorded 2026-07-28. These checks exercise actual local repositories, separate
from the small technique-port races in `run.py`.

| Repository/component | Command/scope | Result | Interpretation |
|---|---|---:|---|
| selected suite | `python3 run.py --all` + `unittest` | 7/7 tests pass | Harness and gates are runnable |
| Witt Spine | `cargo test --workspace` | 69/69 pass | Scheduling, rails, recall SQL shape, dedup, vectors, sketches, and ledger primitives are healthy |
| Evo | mission, runner bridge, graph-store unit subset | 23/23 pass | Current control/evidence primitives pass their focused tests |
| Graphify App | engine, evidence, source slices, pixel proxy | 17/17 pass | Focused read-only evidence/storage/proxy slice passes |
| Witt Brain | `cargo test`; socket case rerun with Unix-socket permission | 17/17 pass | Background JSON-RPC and memory service is viable |
| Witt Link Server | `npm test` | 2/3 files pass | API integration test is not portable: it hardcodes `/workspace/witt-link-server`; under Node 24 the failed child lifecycle triggers a native assertion |

## Important limits

- Witt Spine's recall test currently validates generated SQL shape, not a real
  Turso database. It is not yet evidence that Turso wins the storage race.
- Graphify engine tests force the in-memory path; the large production SQLite
  path still needs a small exported fixture/native adapter.
- Witt Link's failure is a real test portability defect, but not evidence that
  its target registry or event log is broken; those focused tests pass.
- No daemon-dependent candidate (Qdrant, FalkorDB, Meilisearch, Mitmproxy) has a
  score yet.
- No model weights were changed. The self-improvement race tests selection,
  held-out verification, and rollback behavior first.
