# race: fts-engine-recall
seat: backend-lab
question: best full-text search engine for the unified store's keyword arm — incumbent SQLite FTS5 vs embedded Tantivy vs Meilisearch server?
metric: max — recall@10 over a 30-query gold set (code-symbol + prose mix) on a generated 20k-doc fixture; ties broken by mean ms/query
gate: indexes the identical 20k-doc fixture in <90s wall-clock and returns ≥1 hit for every one of the 30 gold queries

## candidate: sqlite-fts5 (incumbent)
source: projects/graphify-app/src/search/db.js:18-52 (schema) and db.js:124-130 (ftsQuery)
approach: FTS5 `unicode61 tokenchars '+#'` virtual table over pre-tokenized text; queries become quoted AND-joined prefix tokens; bm25 ranking. Zero-dependency baseline via node:sqlite or python sqlite3.

## candidate: tantivy
source: quickwit-oss_tantivy/code/examples/basic_search.rs
approach: embedded Rust BM25 index (Lucene-class) over the same docs; default tokenizer + text fields; served via a tiny `cargo run --example`-style harness. No server, no docker.

## candidate: meilisearch
source: meilisearch_meilisearch/code (Dockerfile; BENCHMARKS.md)
approach: `docker pull getmeili/meilisearch` (~150MB), push the fixture over HTTP, query with default ranking rules (typo tolerance on). Tests whether a server engine's ranking beats the embedded options enough to justify a daemon.
