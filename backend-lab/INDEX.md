# Backend Lab — INDEX (identification pass, 2026-07-27)

Source of truth for candidates: `repository-catalog.md` / `repository-catalog.index.json`
(project root; converted from `racetrack_repository_catalog.html` — the :8765
server was down, use the files). 43 numbered categories, 535 unique repos
cross-listed; library confirmed 616 repos / ~40GB (not ~100GB).

## Sections at a glance

| Section | Candidates (RACE NOW / LATER / SKIP) | Tests specced | Race requests |
|---|---|---|---|
| `storage-engine/` | 9 / 8 / ~25+groups | 10 | 4 |
| `interlinking/` | 13 / 7 / 7 (+1 already-raced) | 9 | 4 |
| `pipelines/` | 7 / 16 / rest | 20 (12 contract + 8 flow) | 4 |
| `library-triage/` | 4 rankers / 3 / 1 (+8 signals) | 6 | 4 |

**Total: 45 test specs, 16 race requests awaiting review.**

## The 16 race requests (file into `racetrack/requests/` after review)

storage-engine:
- `fts-engine-recall` — sqlite-fts5 vs tantivy vs meilisearch (recall@10, 30 gold queries / 20k generated docs)
- `embedded-vector-recall` — faiss-ivf vs annoy vs leann-hnsw (recall@10 vs brute-force truth)
- `hybrid-recall-rrf` — spine-trunk single-SQL RRF vs qdrant native fusion vs app-side RRF — **the decisive one-store race**
- `graph-traversal-store` — sqlite edge-joins vs FalkorDB vs in-RAM adjacency (p95 2-hop ms)

interlinking:
- `entity-id-dedup` — SHA-256 vs FNV-1a canonical-JSON vs MinHash (ms/1k ingests)
- `cross-app-entity-resolution` — name-exact vs cosine-gate vs LLM-judge vs ontocast cluster (F1 on 200 gold pairs; gold triple verified real)
- `link-retrieval-recall` — bm25-bonus vs RRF hybrid vs LEANN vector-only (recall@10; complements filed `backend-query-ranking` latency race)
- `llm-link-rerank` — bm25-only vs Ollama rerank vs RRF-no-LLM (nDCG@10) — **blocked: Ollama :11434 is down today**

pipelines:
- `event-log-append-replay` — incumbent SSE/JSONL vs eventsourcing-sqlite vs echoed-replay
- `cross-app-trace-stitching` — agent-trace-schema vs flyline-envelope vs runid-convention
- `live-tail-fanout` — sse-tail vs socketio-rooms vs flyline-tailer
- `front-door-port-routing` — hardcoded-ports vs nginx-front-door vs mitmproxy-programmable

library-triage:
- `triage-ranker-blend` — weighted-blend vs UCB1 vs graph-centrality-first
- `repo-duplicate-detection` — (verified mirror-pair fixture: `iOfficeAI_OfficeCLI`/`iOfficeAI_OfficeCli`)
- `triage-cache-eviction` — CLOCK-PRO vs W-TinyLFU admission as cull policy
- `graph-reachability-extraction` — full per-repo GROUP BY over 26GB index.db took 375s; race the extraction

## Headline findings

- **Turso** (FTS-via-Tantivy + native vector fns in one `.db`) is the strongest
  single-store challenger to the SQLite+FTS5 incumbent — `hybrid-recall-rrf` decides it.
- Contract tests **A11/A12 (pipelines) are expected to FAIL today** — they encode the
  real port collisions: 8787 (information-processer ↔ witt-link-server), 8080 (evo dashboard ↔ localai).
- `evo_graph.py:8` docstring is stale: index.db covers **all 616 repos** (not 597).
- `CARDS-META.json` counts don't reconcile: 301 carded + 316 uncarded = 617 ≠ 616 (S8 data-quality flag).
- `graphs_quarantine/` is lazily created — triage test #5 gates on it existing before cull dry-runs.
- Ollama daemon down (curl 000) — blocks `llm-link-rerank` and LLM-judged triage tier.

## Corrections to earlier assumptions (propagated from builders)

- Citation identity lives in `information-processer/server/pipeline.mjs` L727-739
  (`renderCitations`/`formatBibtex`); `.data/workspace.json` did not exist at scan time.
- `CARDS-META.json` is at `filing-cabinet/library-base/`, not under `repos/`.
- FalkorDB + Ollama docker images already local; meilisearch/qdrant need one-time pulls (~150/120MB).

## Next actions (need your call)

1. Review the 16 race requests in `*/requests/`; say the word to file any into `racetrack/requests/`.
2. Build order for test code: contract tests A1–A12 (cheap, immediate value) → storage-engine races → triage signals.
3. Fix or accept the two port collisions; start Ollama if LLM-tier races are wanted.
