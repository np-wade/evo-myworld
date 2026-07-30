# race: link-retrieval-recall
seat: backend-lab
question: best recall@10 for finding cross-app links/entities — bm25-bonus FTS vs hybrid RRF (vector+FTS) vs vector-ANN-only — on a <10MB slice of the graphify index?
metric: max — recall@10 over 20 gold queries with labeled link targets, averaged (latency-gated, not latency-raced)
gate: query "falkor" must surface push_to_falkordb() in top-10; avg <500ms/query on the slice fixture; empty/garbage queries must not error. NOTE: complements, does not duplicate, racetrack/requests/backend-query-ranking.md (that race is ms/query at full 26GB scale; this one is recall-first on a slice)

## candidate: bm25-bonus (incumbent)
source: projects/evo-myworld/world/backend/evo_graph.py (fts5 bm25 + exact/prefix label bonuses, ported from filing-cabinet repos Graphify-Labs_graphify/code/graphify/serve.py L128-152)
approach: FTS5 quoted-AND MATCH with OR fallback, bm25 rank plus 1000/100 exact/prefix bonus tiers. Keyword-only arm; the baseline every hybrid must beat on recall.

## candidate: hybrid-rrf-fusion
source: witt-spine/crates/spine-trunk/src/recall.rs (RRF k=60 fusing vector arm + FTS5 arm, proximity multiplier, recency tiebreak)
approach: port the two-arm RRF SQL to the slice fixture: Ollama embeddings for the vector arm, FTS5 for the keyword arm, 1/(60+rank) fusion. Should win queries where the gold target shares no tokens with the query.

## candidate: vector-ann-only
source: filing-cabinet repos StarTrail-org_LEANN (lightweight graph-pruned ANN, CPU) with spotify_annoy as fallback if LEANN's deps don't install cleanly
approach: embed all slice nodes once (Ollama), ANN top-k per query, no keyword arm. Tests the opposite extreme from bm25-bonus; expected to lose symbol-exact queries and win paraphrase queries — the race shows how much.
