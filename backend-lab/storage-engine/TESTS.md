# TESTS — storage-engine

The standing test list for the store decision. Races (`requests/*.md`) are the cheap first pass; these are the fuller checks a race winner must survive before becoming **the** store. Every test must run on this box (12GB RAM / 8 cores) with generated, deterministic, <10MB fixtures. The 26GB real `index.db` and FalkorDB dump are used **read-only, optionally** — see the skip-cleanly pattern at the bottom.

1. **ingest-throughput**
   - Question: how fast can each store absorb the mixed record shape (1 node row + FTS entry + 2 edges + optional 384-dim embedding)?
   - Metric: max — committed records/sec sustained over a 50k-record fixture, measured after warmup, fsync semantics on.
   - Gate: post-ingest count equals 50k exactly; DB passes its integrity check (`PRAGMA integrity_check` / engine equivalent); wall-clock < 10 min.
   - Fixture: seeded generator producing graphify-shaped node/edge records (~8MB JSONL).
   - Budget: ~1 eng-day to build, <10 min to run. Candidates: sqlite-fts5, turso/spine-trunk, tantivy, meilisearch, qdrant, (postgres later).

2. **fts-recall@10** *(race 1 is the cheap version)*
   - Question: which keyword arm finds the right doc for code-symbol-ish and prose queries?
   - Metric: max — recall@10 against a 30-query gold set with planted answers in a 20k-doc corpus; tie-break mean ms/query.
   - Gate: indexes the identical fixture in <90s and returns ≥1 hit for every gold query.
   - Fixture: generated docs mixing camelCase/snake_case symbols, file paths, prose paragraphs; gold set = 30 queries each with one planted known-good doc.
   - Budget: covered by race `fts-engine-recall`; extended run ~1h. Candidates: sqlite-fts5, tantivy, meilisearch, turso-FTS.

3. **hybrid-rrf-recall** *(race 3 is the cheap version)*
   - Question: which hybrid architecture (single-SQL fusion, server-side fusion, app-side fusion) retrieves both keyword-obvious and semantic-only docs?
   - Metric: max — recall@10 over 24 gold queries: 8 keyword-only, 8 semantic-only, 8 mixed.
   - Gate: every keyword-only AND every semantic-only gold query has its planted doc in top-10 (a candidate that only wins one arm fails).
   - Fixture: 10k docs embedded with a fixed local model (ollama `nomic-embed-text` via the local docker image; seeded synthetic-embedding fallback for reproducibility).
   - Budget: ~1 eng-day, <15 min run. Candidates: spine-trunk single-SQL RRF, qdrant native fusion, app-side RRF (sqlite FTS + faiss), meilisearch hybrid.

4. **graph-traversal-latency** *(race 4 is the cheap version)*
   - Question: which store serves 1–2-hop neighborhood queries fastest at exact correctness?
   - Metric: min — p95 ms for 2-hop neighborhood over 100 probe nodes on a 100k-node/500k-edge generated graph.
   - Gate: returned neighbor sets exactly equal the SQLite reference for all 100 probes at 1 and 2 hops.
   - Fixture: seeded power-law graph generator (deterministic, ~7MB edge list).
   - Budget: covered by race `graph-traversal-store`. Candidates: sqlite edges table, FalkorDB, in-RAM adjacency, (postgres recursive CTE later).

5. **concurrent-read-while-write**
   - Question: does recall stay fast and correct while ingestion is running (the apps never stop writing)?
   - Metric: min — p99 read-latency ratio (mixed-phase p99 / idle-phase p99) under 1 writer + 4 readers for 30s.
   - Gate: zero read errors/timeouts; every committed write visible to readers within 1s; ratio must be < 10×.
   - Fixture: fixture from test 1 + test 2 gold queries as the read load.
   - Budget: ~0.5 eng-day, 2 min run per candidate. Candidates: sqlite WAL, turso, qdrant, meilisearch, falkordb.

6. **crash-recovery (kill -9)**
   - Question: what happens when the box OOMs / the process is killed mid-write? (WSL + 12GB makes this a when, not if.)
   - Metric: max — committed-txns preserved (must be 100%), then min — seconds from restart to first correct query answer.
   - Gate: kill -9 during a checkpointed write loop; on reopen, committed-row count matches the pre-kill ack count exactly; integrity check clean.
   - Fixture: small write loop (5k records) with client-side ack log.
   - Budget: ~0.5 eng-day, <5 min per candidate. Candidates: sqlite WAL, turso, falkordb (RDB/AOF), qdrant, meilisearch.

7. **disk-footprint**
   - Question: how much disk per unit of knowledge, indexes included? (The incumbent spends 26GB on 9.2M nodes.)
   - Metric: min — total bytes on disk after indexing the standard 50k-doc + 100k-edge + 10k-vector fixture, measured after compaction/vacuum.
   - Gate: post-compaction recall@10 on the gold set must equal pre-compaction recall.
   - Fixture: union of fixtures 1/2/4.
   - Budget: ~0.5 eng-day. Candidates: all RACE NOW engines + LEANN (its whole pitch) + lance (cold tier).

8. **export-restore-roundtrip**
   - Question: can the store be fully exported, moved, and restored without silent loss? (Backup + box-migration story.)
   - Metric: min — seconds to export + restore + verify the standard fixture.
   - Gate: post-restore recall@10 and graph-traversal results byte-identical to pre-export; row/doc counts match.
   - Fixture: union of fixtures 1/2/4 (small scale).
   - Budget: ~0.5 eng-day. Candidates: all race winners.

9. **cold-open-boot**
   - Question: how fast from process start to first served query at realistic scale? (The incumbent's selling point is "near-zero boot cost, no rebuild"; in-RAM approaches pay it at boot instead.)
   - Metric: min — ms from process spawn to correct answer for a fixed probe query, at 1M-node scale (generated).
   - Gate: first answer must be correct (no serving partial indexes); < 60s or the candidate is disqualified at this scale.
   - Fixture: scaled-up generator (1M nodes, still synthetic; DB files may exceed 10MB — fixture is the generator, not the data).
   - Budget: ~1 eng-day. Candidates: sqlite, turso, falkordb, qdrant, tantivy, mem-adjacency.

10. **embedding-pipeline-e2e**
    - Question: is a local vector tier even viable on this box — what does embed+store cost end-to-end?
    - Metric: max — docs/min through ollama embed → store write, sustained over 2k docs, no swap thrash (RSS of all participants < 10GB).
    - Gate: ollama container up, fixed model, all 2k docs retrievable afterwards; run survives with ≥1GB RAM headroom.
    - Fixture: 2k docs from fixture 1.
    - Budget: ~0.5 eng-day. Candidate-neutral, but run it against the hybrid-race winner; its number decides whether the vector arm ships on-box or stays optional.

## The skip-cleanly pattern (mandatory for anything touching real data)

Model: `projects/evo-myworld/world/backend/test_evo_graph.py`. Rules every test above follows:

- Big real artifacts (26GB `index.db`, FalkorDB dump, `data/graphs/`) are **optional validation, never fixtures**: `pytest.mark.skipif(not os.path.exists(DB), reason=...)`; missing data = skip, not fail.
- Real DBs open **read-only** (`sqlite3` URI `mode=ro`; prove it with a write that must raise, as in `test_db_opened_read_only`).
- Data root overridable by env var (`GRAPHIFY_DATA` pattern) so races run against generated fixtures while the same test can validate against the real DB when present.
- Missing-data behavior is itself tested: wrong root → clean message + exit 2, never a traceback.
- Race fixtures are always produced by a seeded generator checked into the race repo, so results are reproducible on any box (including ones without the 26GB file).
