# backend-lab / pipelines

Seat: data routing + observability — how scraped and AI-processed data flows through the whole system, visible at every hop.
Inventory: the 10 real seams (SQLite+FTS5 index, graphify bridge, CARDS-META corpus, run-dir protocol, witt-link-server ports, event streams, witt.sock, evo dashboard, pixel sidecar, shared Ollama) plus the 8787/8080 port collisions.
`CANDIDATES.md` — verified library candidates for event-bus/log, tracing/APM, serialization, and routing/orchestration races.
`TESTS.md` — contract tests (one per seam, cheap invariants) and flow/race tests (schema conformance, trace stitching, routing correctness) to build later.
`requests/` — race requests in the standard racetrack format; every cited path verified against the library on 2026-07-27.
