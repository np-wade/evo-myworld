# race: graph-traversal-store
seat: backend-lab
question: best store for 1–2-hop neighborhood queries over code/knowledge edges — SQLite edge table vs FalkorDB vs in-RAM adjacency?
metric: min — p95 ms for 2-hop neighborhood over 100 probe nodes on a generated 100k-node/500k-edge power-law graph; correctness gated first
gate: returned neighbor sets exactly equal the SQLite reference implementation for all 100 probes, at both 1 and 2 hops

## candidate: sqlite-edges (incumbent)
source: projects/graphify-app/src/search/db.js:43-47 (edges table + src/dst indexes) and projects/graphify-app/src/search/db-graph.js (graph ops served from SQL)
approach: indexed `edges(repo_id, src, dst, relation)` table; 1-hop = indexed lookup, 2-hop = join/recursive CTE. The reference implementation and the zero-new-infra baseline.

## candidate: falkordb
source: docker image falkordb/falkordb:latest (already local); live-incumbent format reference projects/graphify-app/data/falkor/dump.rdb
approach: load the fixture graph, query `MATCH (a)-[*1..2]->(b)` via Cypher. The already-running incumbent graph daemon — does a purpose-built graph store beat indexed joins?

## candidate: mem-adjacency
source: projects/graphify-app/src/search/engine.js + db-graph.js (in-RAM engine whose output the SQL path mirrors exactly)
approach: load the edge list into adjacency maps at boot, BFS for 1/2 hops entirely in memory. Pays boot + RAM cost (capped by the 12GB box) to buy query speed — measures what the SQL path actually costs per query.
