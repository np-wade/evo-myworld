# Selected backend race suite

Runnable first-pass benchmarks for the seven priorities selected on 2026-07-28:

1. cross-app contract;
2. agent lifecycle and mission control;
5. cross-app identity and trace stitching;
8. unified hybrid recall;
9. graph and lineage storage;
6. gateway routing and failover;
10. safe self-improvement.

The suite is intentionally dependency-free. It races small, technique-faithful
reference implementations first and records repository-backed candidates that
still need native adapters as `pending`, never as fabricated scores.

## Run

```bash
python3 backend-lab/selected-suite/run.py --all
python3 -m unittest discover -s backend-lab/selected-suite/tests -v
```

Results are written to `backend-lab/selected-suite/out/` by default. Set
`EVO_RESULT_PATH` and `EVO_TRACES_DIR` to emit Evo-compatible inline
instrumentation.

## Meaning of the first-pass results

- A `reference` result validates the fixture, metric, and hard gate.
- A `technique-port` result is a small port of the cited repository's relevant
  algorithm, not a claim about the full upstream product.
- A `pending` result means the upstream repository needs a native adapter,
  daemon, compiler, model, or package before it can be scored fairly.
- Only candidates whose hard gate passes are eligible to win.

The next pass replaces technique ports with native adapters in priority order:
Witt Spine/Evo/ZeroClaw first, then SQLite/Turso/Qdrant/FalkorDB, then the
larger agent frameworks.

## Witt product direction

Witt is tested as a background local-agent service, not as a user-facing CLI.
The intended seam is Witt Link HTTP/WebSocket → Witt Brain JSON-RPC service,
with Witt Spine supplying internal scheduling/memory/storage primitives and Evo
supplying optional, gated improvement runs. `/projects/witt` is not a required
user surface for this suite.
