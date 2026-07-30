# race: hybrid-recall-rrf
seat: backend-lab
question: best hybrid (keyword+vector) recall architecture — single-SQL RRF in Turso vs qdrant server-side fusion vs app-side RRF over sqlite+faiss?
metric: max — recall@10 over 24 gold queries (8 keyword-only, 8 semantic-only, 8 mixed) on a 10k-doc fixture with fixed embeddings (ollama nomic-embed-text via local docker image, seeded synthetic-embedding fallback)
gate: for every keyword-only AND every semantic-only gold query the planted known-good doc appears in the top-10 (winning only one arm = fail)

## candidate: single-sql-rrf (witt-spine)
source: projects/witt-spine/crates/spine-trunk/src/recall.rs (+ schema.sql)
approach: one SQL statement on Turso — vector arm (`vector_distance_cos` with cosine threshold) + FTS arm, fused RRF k=60 with scope-proximity weighting, forgotten/superseded excluded structurally. The "one file, one query" play.

## candidate: qdrant-native
source: qdrant_qdrant/code/lib/shard/src/query/ (RRF fusion in hybrid query path)
approach: `docker pull qdrant/qdrant`; dense prefetch + sparse/keyword prefetch fused server-side via RRF query API. Tests whether a dedicated vector server's fusion beats doing it in SQL.

## candidate: app-side-rrf
source: projects/evo-myworld/world/backend/evo_graph.py (FTS5 bm25 ranking pattern) + facebookresearch_faiss/code (vector arm)
approach: sqlite FTS5 bm25 ranks and faiss ranks computed independently, fused in python with RRF k=60 — the evo_graph pattern extended with a vector arm. No new infra: if this wins, the incumbent stack already suffices.
