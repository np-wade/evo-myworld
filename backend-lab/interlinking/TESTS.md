# TESTS — interlinking (to build later)

Numbered test definitions. Each lists: question, metric, executable gate, fixture, budget, candidates. Fixtures must be <10MB and each test must run in seconds, not minutes. Shared fixture sources (all verified to exist):

- **FC**: `filing-cabinet/library-base/repos/*/CARD.md` + `filing-cabinet/library-base/CARDS-META.json` (616 repos)
- **GA**: `projects/graphify-app/data/graphs/cloned__library__*` dir names (one id per indexed repo)
- **AR**: `projects/assembly-runs/` run manifests
- **EV**: `.evo/graph/evidence.db` written by `projects/evo-myworld/plugins/evo/src/evo/graph/writeback.py`
- **WS**: `projects/witt-spine/crates/spine-trunk/src/` (recall.rs, dedup.rs)

---

## 1. cross-app-same-entity
- Question: do three representations of the same repo (FC `Graphify-Labs_graphify`, GA `cloned__library__Graphify-Labs__graphify__htef7z`, AR run that pulled it) resolve to ONE canonical id?
- Metric: max — F1 on gold same/different pairs (200 pairs: 100 same-entity across apps, 100 hard negatives like `EverMind-AI_HyperMem` vs `EverMind-AI_EverMemBench`).
- Gate: the known `graphify` triple must resolve to one id; the two EverMind near-name repos must NOT merge; runtime <60s.
- Fixture: sampled list of 100 repos present in all three of FC/GA/AR (name strings + CARD one-liners only, ~200KB JSON).
- Budget: <60s total incl. any Ollama calls.
- Candidates: normalized-name exact match (CARD baseline) vs cosine-threshold gate (tencentdb l1-dedup / spine dedup.rs) vs LLM batch judge (tencentdb prompt via Ollama) vs embedding cluster (ontocast entity_aligner).

## 2. dedup-on-reingest
- Question: ingesting the same evidence twice (or with cosmetic mutation) creates how many ids, at what cost?
- Metric: min — ms per 1k ingests at steady state (10k-record store); correctness gated first.
- Gate: exact re-ingest → 0 new ids; key-reordered JSON re-ingest → 0 new ids; 50 held-out distinct docs → 50 new ids (no false merges).
- Fixture: 10k synthetic evidence records (experiment/artifact JSON, ~5MB), plus a mutated copy set (whitespace, key order, one-token edits).
- Budget: <30s per contender.
- Candidates: sha256-content-address (writeback.py) vs fnv1a-canonical-json (spine dedup.rs + clawsweeper stable-json.ts) vs minhash-lsh (algebird MinHasher port, near-dup arm).

## 3. lineage-query-correctness
- Question: does `lineage()` return exactly the DERIVED_FROM chain, oldest-last, and nothing else — including under adversarial writes?
- Metric: min — number of incorrect chains across the fixture (0 required to pass; then ms/query as tiebreak).
- Gate: 20 known chains must match exactly; a hand-planted cycle (`a→b→a`) must terminate (cycle guard) and a missing-parent chain must stop gracefully; re-recording the same experiment twice must not duplicate edges.
- Fixture: generated evidence.db with 3 experiment trees (~500 nodes, <1MB) written via `record_experiment`.
- Budget: <10s.
- Candidates: writeback.py `lineage()` (incumbent) vs a recursive-CTE SQL variant vs a NetworkX in-memory walk — same fixture, same answers expected; this test validates the incumbent more than it races.

## 4. orphan-detection
- Question: which entities have NO inbound or outbound links (evidence nodes nothing cites, CARDs no graph dir claims, graph dirs with no CARD)?
- Metric: max — precision of the orphan report against a hand-labeled list (recall must be 100% structurally: a full scan finds every orphan).
- Gate: the 10 hand-planted orphans in the fixture must all appear; no linked entity may be reported.
- Fixture: small evidence.db (500 nodes with 10 planted orphans) + a 50-repo FC/GA name fixture with 5 planted unmatched on each side.
- Budget: <10s.
- Candidates: SQL anti-join scan (writeback.py edges tables) vs python set-difference over exported adjacency — trivially fast either way; the test exists to fix the orphan *definition* (which edge types count as "linked").

## 5. gold-query-recall@10
- Question: given 20 gold queries with known-correct link targets (e.g. "falkor" → `push_to_falkordb()`), which retrieval stack surfaces them?
- Metric: max — recall@10 over the 20 gold queries.
- Gate: ≥15/20 recall to be comparable at all; avg <500ms/query on the fixture; empty/garbage queries must not error.
- Fixture: export of 3 repos' nodes from the 26GB graphify index.db into a <10MB slice sqlite (schema-preserved), 20-query gold set with labeled targets.
- Budget: <60s total.
- Candidates: bm25-bonus (evo_graph.py) vs RRF hybrid vector+FTS (spine recall.rs ported) vs vector-only (LEANN or annoy arm) vs bm25+trigram-prefilter ( contender carried over from `backend-query-ranking.md`).

## 6. ms-per-query-budget
- Question: at fixture scale, what does each retrieval contender actually cost per query, p50/p95?
- Metric: min — ms per 10-hit query, averaged over the 20 gold queries, p95 reported separately.
- Gate: correctness inherited from test 5 (must hit the same recall floor); any contender >2s/query p95 is disqualified regardless of recall.
- Fixture: same as test 5.
- Budget: <60s.
- Candidates: same as test 5. This is the interlinking-side counterpart of the already-filed `racetrack/requests/backend-query-ranking.md` (which runs at full 26GB scale); keep both, they bound the scale curve.

## 7. llm-rerank-quality
- Question: does an Ollama rerank of bm25's top-20 improve the top-10 enough to pay its latency?
- Metric: max — nDCG@10 on the gold query set.
- Gate: rerank must not demote a known-correct hit out of the top-10 on any gold query; p95 <2s/query; Ollama unreachable → clean fallback to bm25 order, not an error.
- Fixture: same as test 5 plus cached top-20 bm25 candidate lists (so the race doesn't re-run retrieval).
- Budget: <120s (LLM-bound).
- Candidates: bm25-only order (evo_graph.py) vs LLM pointwise rerank (tencentdb batch-judge prompt shape, adapted) vs RRF hybrid without LLM (spine recall.rs).

## 8. garbage-empty-input-robustness
- Question: what breaks when identity/retrieval functions receive empty strings, binary garbage, 1MB blobs, SQL/FTS metacharacters, or duplicate-key floods?
- Metric: min — count of unhandled exceptions/tracebacks across the abuse corpus (0 required).
- Gate: every input returns either a clean result or a clean error (exit code / typed exception); no traceback, no hang >5s, no db corruption (store passes an integrity_check afterward).
- Fixture: ~100 abuse inputs: `""`, `"\x00"`, 1MB of `/dev/urandom`, `'" OR 1=1 --`, FTS5 operators (`AND OR NEAR " *`), 10k identical upserts in a loop, valid JSON with 10k keys.
- Budget: <30s per contender.
- Candidates: writeback.py upsert path, evo_graph.py find path (its `_die` convention claims graceful failure — verify), spine dedup.rs `content_hash` (port).

## 9. id-stability-across-reparse (LATER, depends on AST extraction candidates)
- Question: does a `repo:file:symbol` id survive an edit to an unrelated part of the file?
- Metric: max — fraction of ids unchanged after cosmetic edits (whitespace, comment added) across 50 files.
- Gate: symbol ids for untouched functions must be 100% stable.
- Fixture: 50 source files + edited copies (<1MB).
- Budget: <30s.
- Candidates: graphify extract.py node-id scheme vs tree-sitter-magma (codebase-memory-mcp) span-based ids.
