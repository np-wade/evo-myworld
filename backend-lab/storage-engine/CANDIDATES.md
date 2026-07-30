# CANDIDATES — storage-engine

Every plausible store/retrieval engine from catalog categories 1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 22 (+ relevant 4), verified with `ls` against `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/` on 2026-07-27. Incumbent baselines (not from the catalog) are listed first. "Runs here?" assumes 12GB RAM / 8 cores / docker with `falkordb/falkordb:latest` and `ollama/ollama:latest` already local.

## Incumbent baselines (to beat)

| candidate | cat | verified path | technique | test on | weight/deps + runs here? | verdict |
|---|---|---|---|---|---|---|
| SQLite+FTS5 WAL (graphify index.db) | incumbent | `projects/graphify-app/src/search/db.js:18-52` (26GB DB, 9.2M nodes/24.6M edges, verified) | FTS5 `unicode61 tokenchars '+#'`, pre-tokenized text, bm25; edges table w/ src/dst indexes; node:sqlite + python sqlite3 readers | every race — it is the baseline | zero deps (node:sqlite, py3 sqlite3 3.46.1 present); yes | RACE NOW (baseline) |
| witt-spine spine-trunk | incumbent | `projects/witt-spine/crates/spine-trunk/schema.sql` + `src/recall.rs` (verified) | in-house Rust store on Turso: 23-table schema, single-SQL hybrid RRF k=60 (vector arm `vector_distance_cos` + FTS arm), scope-proximity weighting | hybrid-rrf race; full TESTS.md suite | Rust crate; needs Turso engine (below); yes | RACE NOW |
| FalkorDB (Redis-graph) | incumbent | docker image `falkordb/falkordb:latest` (local); dump `projects/graphify-app/data/falkor/dump.rdb` (237KB, verified) | Cypher graph queries over Redis module; RDB snapshot persistence | graph-traversal race; crash-recovery test | docker run, ~100MB RAM; yes | RACE NOW |

## Engines from the catalog

| candidate | cat | verified repo path | technique | test on | weight/deps + runs here? | verdict |
|---|---|---|---|---|---|---|
| tursodatabase_turso | 8/9 | `tursodatabase_turso` (`core/vdbe/execute.rs` has `vector_distance_cos`, `vector32/64/8/1bit`; COMPAT.md: FTS via Tantivy) | SQLite-compatible file format in Rust with built-in vector fns + Tantivy-based FTS — the "one file does everything" play; engine under spine-trunk | hybrid race (via spine-trunk), ingest, crash-recovery, footprint | cargo build (~heavy but one-time) or CLI/pip bindings; yes | RACE NOW |
| quickwit-oss_tantivy | 7 | `quickwit-oss_tantivy/code` (`examples/basic_search.rs`) | embedded Lucene-class BM25 index in Rust; per-segment indexing, fast | FTS race; ingest throughput | cargo lib, no server; yes | RACE NOW |
| meilisearch_meilisearch | 7/1 | `meilisearch_meilisearch/code` (Dockerfile, BENCHMARKS.md) | search server: typo tolerance, ranking rules, hybrid (keyword+semantic) search | FTS race; hybrid race | `docker pull getmeili/meilisearch` (~150MB), ~200MB RAM; yes | RACE NOW |
| qdrant_qdrant | 6/1 | `qdrant_qdrant/code` (`lib/shard/src/query/` — RRF fusion verified) | vector DB w/ payload filtering + server-side hybrid queries (prefetch + RRF/DBSF fusion) | hybrid race; concurrent read-while-write; crash-recovery | `docker pull qdrant/qdrant` (~120MB), <1GB RAM at fixture scale; yes | RACE NOW |
| facebookresearch_faiss | 6/1 | `facebookresearch_faiss/code` (`benchs/`) | ANN library: IndexFlatIP exact baseline, IVF/HNSW/PQ indexes; the reference implementation | vector race; ground-truth generator for all recall tests | `pip install faiss-cpu` wheel; yes | RACE NOW |
| spotify_annoy | 6 | `spotify_annoy` (`src/annoylib.h`, `annoymodule.cc`) | random-projection trees, mmap-able static indexes, tiny | vector race (lightweight counterpoint to faiss) | `pip install annoy`, C++ header; yes | RACE NOW |
| StarTrail-org_LEANN | 6/1 | `StarTrail-org_LEANN/code` (`packages/leann`, `packages/leann-backend-hnsw`, `benchmarks/`) | graph ANN with aggressive storage pruning (recompute-on-demand); claims ~97% storage saving | vector race round 2; disk-footprint test | pip pkg exists in-repo; wheel availability for this box unverified | RACE LATER (build risk; try after faiss/annoy baseline lands) |
| ruvnet_ruvector | 6/3 | `ruvnet_ruvector/code` (benches/) | embedded Rust vector store (HNSW claims) for agent memory | vector race round 2 | cargo; maturity/API stability unverified | RACE LATER (dup of faiss niche until it proves a win) |
| postgres_postgres | 9/8 | `postgres_postgres` | the "just Postgres" option: JSONB docs + tsvector FTS + pgvector + recursive CTE graphs in one server | tier race vs (sqlite+turso) after round 1 | `docker pull postgres` + pgvector image; ~1GB RAM comfy; yes | RACE LATER (needs docker pull; race the consolidated-store question after engines settle) |
| redis_redis | 11/3 | `redis_redis` | in-memory KV/structures; cache/queue/ephemeral tier; FalkorDB already runs on its module API | cache-tier race; not the system of record | docker or build; yes | RACE LATER (cache-tier only) |
| moka-rs_mini-moka | 11/22/3 | `moka-rs_mini-moka` | concurrent bounded in-RAM cache (Caffeine-style) | query-cache micro-race | cargo lib; yes | RACE LATER (with quick-cache, if a cache tier opens) |
| arthurprs_quick-cache | 11/22 | `arthurprs_quick-cache` | lock-free LRU for Rust | query-cache micro-race | cargo lib; yes | RACE LATER (same race as mini-moka) |
| apache_datafusion | 12/4 | `apache_datafusion` | embeddable columnar OLAP SQL engine (Arrow) | cold/analytics tier over scraped-data parquet | cargo lib, heavy build; yes | RACE LATER (tier decision, after hot store settles) |
| lance-format_lance | 12/13/4 | `lance-format_lance` | columnar file format w/ vector indexes; versioned datasets | cold-tier candidate for scraped data + embeddings archive | cargo/pip; yes | RACE LATER (with datafusion, cold-tier race) |
| elastic_elasticsearch | 7 | `elastic_elasticsearch` | distributed Lucene search/analytics server | — | JVM, ≥1GB heap, ~600MB image; runs but wasteful here | SKIP (heavyweight dup of meilisearch+qdrant on a 12GB box) |
| cockroachdb_cockroach | 9 | `cockroachdb_cockroach` | distributed SQL | — | pointless single-node; wants a cluster | SKIP (needs cluster) |
| apache_couchdb | 8 | `apache_couchdb` | multi-master sync JSON doc DB | — | Erlang VM; weak search vs every FTS candidate | SKIP (sync niche; dup of postgres-JSONB) |
| pouchdb_pouchdb | 8 | `pouchdb_pouchdb` | browser doc DB syncing with CouchDB | — | JS, browser-side | SKIP (client-side sync pair of couchdb) |
| apache_couchdb-docker | 8 | `apache_couchdb-docker` | packaging of the above | — | — | SKIP (dup row) |
| karakeep-app_karakeep | 8 | `karakeep-app_karakeep` | bookmark/archive app | — | app, not an engine | SKIP (not a store) |
| spotify_kairosdb | 10 | `spotify_kairosdb` | distributed TSDB on Cassandra | — | Java + Cassandra | SKIP (metrics niche + cluster deps; not the knowledge store) |
| spotify_heroic | 10 | `spotify_heroic` | TSDB for metrics aggregation | — | Java, wants Bigtable/Cassandra | SKIP (same) |
| netdata_netdata | 10 | `netdata_netdata` | metrics collector daemon | — | — | SKIP (observability, Builder-monitoring territory) |
| zeroclaw-labs_zeroclaw-metrics | 10 | `zeroclaw-labs_zeroclaw-metrics` | agent telemetry exporter | — | — | SKIP (telemetry, not a store) |
| redis-rs_redis-rs | 11 | `redis-rs_redis-rs` | Rust Redis client | — | — | SKIP (client library, not a store) |
| apache_arrow-rs | 12/13 | `apache_arrow-rs` | in-memory columnar format | — | reached via datafusion/lance | SKIP (building block, not a store) |
| apache_iceberg | 13/4 | `apache_iceberg` | lake table format (Java) | — | needs catalog/warehouse infra | SKIP (single box overkill; cold-tier already covered by lance) |
| apache_iceberg-rust | 13 | `apache_iceberg-rust` | Rust impl of the same | — | — | SKIP (same) |
| apache_opendal | 13 | `apache_opendal` | unified storage access layer | — | — | SKIP (access abstraction, not a store) |
| supermemoryai_supermemory | 1/2/3 | `supermemoryai_supermemory` | hosted-style memory API + knowledge graph app | memory-API design ideas only | Next.js app + its own infra | SKIP (app/SaaS layer, not an embeddable store) |
| TencentCloud_tencentdb-agent-memory | 3 | `TencentCloud_tencentdb-agent-memory` | agent-memory schema on a DB | — | lineage already mined into spine-trunk (schema.sql header) | SKIP (already absorbed) |
| EverMind-AI_HyperMem | 2/3 | `EverMind-AI_HyperMem` | hypergraph agent memory (research) | — | store not separable from the research code | SKIP (research artifact) |
| EverMind-AI_raven | 3 | `EverMind-AI_raven` | memory consolidation/eval engine | memory-tier design reference | — | SKIP as store (Builder memory-section material) |
| EverMind-AI_EverMemBench | 3 | `EverMind-AI_EverMemBench` | long-term memory benchmark suite | fixture source for future memory-tier tests | — | SKIP as candidate (keep as fixture donor) |
| EverMind-AI_MSA / EverMe | 3 | `EverMind-AI_MSA`, `EverMind-AI_EverMe` | multi-agent memory / personal memory profile apps | — | — | SKIP (apps) |
| DeusData_codebase-memory-mcp | 1/3 | `DeusData_codebase-memory-mcp` | codebase-memory MCP server | — | store underneath is the sqlite+vec pattern (dup of incumbent) | SKIP (dup pattern; MCP surface is another section's race) |
| Wassimyounes01_memory | 3 | `Wassimyounes01_memory` | small persistent semantic-memory module | — | — | SKIP (tiny module, no engine) |
| raiyanyahya_recall | 3 | `raiyanyahya_recall` | lightweight agent memory module | — | — | SKIP (same) |
| Graphify-Labs_graphify | 1/2 | `Graphify-Labs_graphify` | code-graph extraction pipeline — upstream of the incumbent index.db | ingestion-pipeline races (other section) | node; yes | SKIP as store (it feeds the baseline; not a store itself) |
| stanford-oval_suql | 1 | `stanford-oval_suql` | conversational structured+unstructured query layer | — | research prototype over postgres | SKIP (query layer, not a store) |
| PJDude_librer | 1/7 | `PJDude_librer` | desktop document indexer | — | Python desktop app | SKIP (app) |
| searxng_searxng | 1/7 | `searxng_searxng` | metasearch engine | — | image local, but it's a search client | SKIP (not a store) |
| schlegelp_aann | 6 | `schlegelp_aann` | adaptive ANN research lib | — | small research lib | SKIP (no edge over faiss) |
| NVIDIA_nv-embedding-cache | 6/22 | `NVIDIA_nv-embedding-cache` | GPU embedding cache | — | needs GPU workload | SKIP (not a store; GPU-oriented) |
| LMCache_LMCache | 3/22 | `LMCache_LMCache` | LLM KV/prompt-reuse cache | — | inference-engine territory | SKIP (not a store) |
| deepcausality_deep_causality | 2 | `deepcausality_deep_causality` | hypergraph causal reasoning engine | — | causal section (cat 18) | SKIP (reasoning engine, not a store) |

## Grouped exclusions (verified present; not stores — no race value here)

- **Cat 1 apps/frameworks:** haystack (+cookbook/experimental/hayhooks), ragbits (+create-ragbits-app), storm, WikiChat, local-deep-researcher, deep-research-starter, openwiki, paper-search-mcp, browser-search, Scout, PixelRAG, neuron, web-check, crawl4ai, Scrapegraph-ai, awesome-llm-apps — retrieval/RAG *apps and frameworks*; the store decision is independent of them.
- **Cat 2 constructors/visualizers:** ontocast, code-review-graph, catala, Understand-Anything, likec4, freeplane, papers-we-love, ewiser, 21-word-sense-disambiguation, wittgenstein, openscience, undoc, repowise, flow-builder — graph *construction/visualization*; they write into a store, they aren't one.
- **Cat 4 cluster infra:** spark, flink, kafka, druid, paimon, seatunnel, scio, scalding, algebird, SynapseML, sedona-db, datasketches(+rust), floci, superset, polynote, tabfm, chartify, Chips-n-Salsa, Data-Engineering-HowTo — cluster/streaming infra or non-store utilities; the cold tier (if any) is covered by lance+datafusion above.
- **Cat 9 apps over SQL:** Chat2DB, db-ally, nocodb, WrenAI, hasura_graphql-engine, dbeaver, twenty — clients/text-to-SQL/CRMs over whatever store wins.
- **Cat 13 serialization:** thrift, fory, baml — wire/schema formats, Builder-C territory.
- **Cat 22 cache micro-libs:** lazy-lru, cached, ttl, filecache, SPTPersistentCache, sliding_window_alt, sliding-window-counter, rust-sliding_windows, bolt-load, heavykeeper-rs, pingora — single-algorithm libs; only mini-moka/quick-cache (above) justify a tier race.

## Tally

- **RACE NOW: 9** (3 incumbents + turso, tantivy, meilisearch, qdrant, faiss, annoy)
- **RACE LATER: 8** (postgres, redis, LEANN, ruvector, lance, datafusion, mini-moka, quick-cache)
- **SKIP: ~25 individual rows + 5 excluded groups**
