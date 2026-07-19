# race: backend-query-ranking
seat: claude-backend
question: best ranking approach for evo_graph find over the 5.9M-node FTS index — current bm25+bonus vs trigram-style prefilter+rank?
metric: min — ms per 10-hit query, averaged over 5 distinct queries (correctness gated first)
gate: for query "falkor" the top-3 must include push_to_falkordb() from Graphify-Labs graphify export.py (known-good hit); empty/garbage queries must not error

## candidate: bm25-bonus (current)
source: world/backend/evo_graph.py (fts5 bm25 + exact/prefix label bonuses, ported from Graphify-Labs_graphify code/graphify/serve.py L128-152)
approach: FTS5 MATCH with quoted AND tokens, OR fallback, bm25 rank plus 1000/100 exact/prefix label bonus tiers.

## candidate: prefilter-then-rank
source: graphify slice trigram-prefilter-candidates_c104 (graphify-app/data/graphs/cloned__library__Graphify-Labs__graphify__htef7z/slices/) and its cited source files
approach: cheap candidate prefilter (LIKE/trigram-style narrowing on norm_label) to a small set, then rank only the candidates — trades FTS generality for a tight candidate pool; may win on short symbol-ish queries.
