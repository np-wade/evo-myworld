# race: graph-reachability-extraction
seat: backend-lab
question: fastest correct way to produce the per-repo graph-reachability signal (node count, degree sum, max centrality) for every indexed repo from the 26GB graphify index?
metric: min wall seconds to emit the full per-repo table (one row per repo in index.db's repos table) on the 12GB box
gate: exit 0 iff per-repo node_count and edge_count match the precomputed columns in the index.db repos table (schema graphify-app/src/search/db.js:22-30) for 100% of rows, and the DB is opened read-only (no WAL growth)

## candidate: sql-aggregate
source: world/backend/evo_graph.py
approach: Single read-only (mode=ro, evo_graph.py L65) GROUP BY repo_id over the nodes table using the nodes_repo_node covering index; one pass, no graph.json parsing. Naive probe measured 375s on this box (2026-07-27) — the raced implementation must beat that via the covering index or a staged scan.

## candidate: slice-walk-fallback
source: graphify-app/src/search/db-graph.js
approach: Walk each repo's graphify-out slice JSONs under data/graphs/<id>/ and aggregate client-side (the db-graph.js fallback path used when graph.json is quarantined/oversized); more I/O but parallelizable and independent of SQLite query planning.
