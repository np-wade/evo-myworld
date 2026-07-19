# Build notes — evo-graph phase 1 (claude-backend, 2026-07-19)

## GRAPH-FIRST pull (done before writing code)

Route: `data/graphs/TOPICS.md` → slice INDEX.md for both target repos →
skimmed 4 slice JSONs → read real source at the slice-cited lines.

### Slices read

1. **Graphify-Labs__graphify / `chinese-terms-mcp_c55.json`**
   (topic_terms: chinese, terms, mcp; files: serve.py) — the graphify
   server's own query path: `_query_terms()` at serve.py L128,
   `_is_searchable()` L103.
2. **Graphify-Labs__graphify / `trigram-prefilter-candidates_c104.json`**
   — `_trigrams()` L180, `_trigram_candidates()` L234, `_find_node()`
   L657: candidate prefilter + ranking approach.
3. **TencentCloud__tencentdb-agent-memory / `search-jieba-fts_c15.json`**
   (files: memory-search.ts, sqlite.ts) — `buildFtsQuery()`,
   `tokenizeForFts()`: FTS5 query construction for agent memory search.
4. **TencentCloud__tencentdb-agent-memory / `gateway-watchdog-prefetch_c11.json`**
   — `MemoryTencentdbProvider`, `._try_recover_gateway()` at
   `__init__.py` L449: agent-memory gateway resilience pattern.

### Source read (filing-cabinet/library-base/repos/)

- `Graphify-Labs_graphify/code/graphify/serve.py` L103-180:
  - `_query_terms()` — `re.findall(r"\w+", raw.lower())` tokenization,
    `_QUERY_STOPWORDS` filter (question/filler words), **fallback to
    unfiltered terms when everything is a stopword**. → ported into
    `evo_graph._query_terms()`.
  - Ranking tiers `_EXACT_MATCH_BONUS=1000 / _PREFIX_MATCH_BONUS=100 /
    _SUBSTRING=1` — exact label beats prefix beats plain score. → ported
    as post-bm25 bonuses in `cmd_find()`.
- `TencentCloud_tencentdb-agent-memory/code/src/core/store/sqlite.ts`
  L198 `buildFtsQuery()` — tokens individually **double-quoted** then
  joined, so user punctuation can't inject FTS5 operators. → ported as
  `evo_graph._fts_query()` (with `""` escaping, AND-join + OR fallback).
- `TencentCloud_tencentdb-agent-memory/code/hermes-plugin/memory/
  memory_tencentdb/__init__.py` L449 `_try_recover_gateway()` — the
  documented guarantees ("never raises", cooldown, degrade gracefully).
  → adopted as the CLI's failure policy: missing DB/slices = message +
  exit 2, never a traceback.

## index.db schema facts (discovered via sqlite_master, read-only)

- Tables: `meta`, `repos`, `nodes`, `edges`, `nodes_fts` (FTS5) + its
  shadow tables.
- `nodes`: id PK, repo_id, node_id, label, norm_label, kind, file_type,
  source_file, loc, community, community_name, degree, in/out_degree,
  centrality, rationale, context, rel_json. Indexes on (repo_id,node_id)
  unique, (repo_id,norm_label), (norm_label).
- `edges`: repo_id, src, dst, relation; indexed on (repo_id,src) and
  (repo_id,dst). No rowid join to nodes — src/dst are node_id strings.
- `nodes_fts` columns: label, norm_label, source_file, kind, rationale,
  context, community_name, repo_name; tokenizer
  `unicode61 tokenchars '+#'`. **`nodes_fts.rowid == nodes.id`** —
  verified by joining; that's the whole bridge.
- `repos`: 597 rows; `sum(fts_nodes)` = 5,939,371 (the top-50k/repo cap
  in action: 5.94M of 9.2M nodes are FTS-searchable).
- `meta`: just `built_at = 2026-07-19T17:19:07Z`.
- Surprise: `kind` is populated in the DB (class/function/file/const/
  rationale/…) but is `None` on slice-JSON nodes — don't rely on it in
  slices.
- Surprise: docstring/"rationale" text is indexed as first-class nodes
  (kind=rationale), so FTS hits include prose — useful for concept
  queries, noisy for symbol queries.

## Verification (real runs, 2026-07-19)

`find dedup --limit 5`:

```
cloned__library__elastic__elasticsearch__es2m2k  Dedup  [class]  Dedup.java Dedup.java:33  deg=23
cloned__library__quinn-rs__quinn__l58zs0  Dedup  [class]  spaces.rs spaces.rs:456  deg=10
cloned__library__gastownhall__gastown__iy8ynh  dedup.go  [file]  dedup.go dedup.go:1  deg=2
cloned__library__elastic__elasticsearch__es2m2k  Dedup.java  [file]  Dedup.java Dedup.java:1  deg=33
cloned__library__zeroclaw-labs__zeroclaw__mcntvv  dedup.rs  [file]  dedup.rs dedup.rs:1  deg=6
```

`find falkor --limit 5` (top 3 shown):

```
cloned__library__Graphify-Labs__graphify__htef7z  _connect()  [function]  test_falkordb_integration.py test_falkordb_integration.py:28  deg=3
cloned__library__Graphify-Labs__graphify__htef7z  push_to_falkordb()  [function]  export.py export.py:1472  deg=4
cloned__library__Graphify-Labs__graphify__htef7z  test_falkordb_integration.py  [file]  test_falkordb_integration.py test_falkordb_integration.py:1  deg=5
```

`find "agent memory gateway" --repo tencentdb --limit 5` (top 3):

```
cloned__library__TencentCloud__tencentdb-agent-memory__193pqaf  resolve_gateway_cmd()  [function]  memory-tencentdb-ctl.sh memory-tencentdb-ctl.sh:211  deg=2
cloned__library__TencentCloud__tencentdb-agent-memory__193pqaf  merge_gateway_json()  [function]  memory-tencentdb-ctl.sh memory-tencentdb-ctl.sh:391  deg=7
cloned__library__TencentCloud__tencentdb-agent-memory__193pqaf  _resolve_gateway_host()  [function]  __init__.py __init__.py:120  deg=4
```

`slice tencentdb --topic fts`:

```
repo: cloned__library__TencentCloud__tencentdb-agent-memory__193pqaf
index: .../graphify-out/slices/INDEX.md
2 slice(s):
.../slices/query-fts-tables_c9.json
    topic_terms=['query', 'fts', 'tables'] nodes=36 edges=47
    files=['embedding.ts', 'sqlite.ts', 'state-manager.ts', 'types.ts']
    first nodes: ['EmbeddingProviderInfo', 'bm25RankToScore()', 'VectorStore', '.isDegraded()', '.init()']
.../slices/search-jieba-fts_c15.json
    topic_terms=['search', 'jieba', 'fts'] nodes=29 edges=38
    ...
```

Graceful-failure check: `GRAPHIFY_DATA=/nonexistent python3 evo_graph.py
find dedup` → `evo-graph: index.db not found at /nonexistent/index.db
(set GRAPHIFY_DATA to the graphify data dir)`, exit 2. Punctuation-bomb
query `'weird(punct)"chars'` → OR-fallback fired, 3 hits, exit 0.

pytest (`uv run --no-project --with pytest python -m pytest
test_evo_graph.py -q`): **12 passed in 8.80s** — includes a live check
that the connection really is read-only (CREATE TABLE raises).

## Decisions

- AND-join first, OR fallback: precision by default (symbol lookups),
  recall when precision empties out. graphify itself seeds with OR, but
  it has BFS expansion after seeding; a flat CLI wants precision.
- bm25 + exact/prefix bonuses computed in Python over a 5x overfetch,
  not in SQL — keeps the SQL simple and the bonus tiers debuggable.
- No FalkorDB in phase 1: nothing here needs 3+ hops, and the RAM rule
  says don't spin the in-memory store for lookups SQLite already answers.
- `--repo` matches `repo_id` substring (not repos.name) because repo_id
  is what `find` prints — copy/paste round-trips.
