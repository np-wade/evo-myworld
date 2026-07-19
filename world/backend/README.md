# evo-graph — graphify library bridge (Track B, phase 1)

Read-only CLI bridge from the lab's graphify code-graph library into evo.
Pure stdlib (`sqlite3` + `json`); no installs needed.

## Usage

```bash
python3 world/backend/evo_graph.py find <query> [--repo R] [--limit N]
python3 world/backend/evo_graph.py slice <repo-id-or-substring> [--topic T]
```

- `find` — FTS5 search over the library index. Ranked symbol hits, one per
  line: `repo_id  label  [kind]  source_file loc  deg=N`. Tokens are
  stopword-filtered and AND-joined for precision; falls back to OR if the
  AND query has zero hits. `--repo` filters by `repo_id` substring.
- `slice` — locates a repo's slice directory and lists slice JSON paths.
  With `--topic T` it filters slice names (slices are named by TF-IDF topic
  terms, so use concept words: `fts`, `gateway`, `dedup`, ...) and prints a
  summary per slice (topic terms, node/edge counts, files, first nodes).
  With multiple repo matches it lists them and asks you to narrow.

Examples (real, verified 2026-07-19):

```bash
$ python3 evo_graph.py find falkor --limit 3
cloned__library__Graphify-Labs__graphify__htef7z  _connect()  [function]  test_falkordb_integration.py test_falkordb_integration.py:28  deg=3
cloned__library__Graphify-Labs__graphify__htef7z  push_to_falkordb()  [function]  export.py export.py:1472  deg=4
...

$ python3 evo_graph.py slice tencentdb --topic fts
repo: cloned__library__TencentCloud__tencentdb-agent-memory__193pqaf
2 slice(s): query-fts-tables_c9.json, search-jieba-fts_c15.json (+ summaries)
```

## Data-source map

| Source | Path | Access |
|---|---|---|
| FTS index | `graphify-app/data/index.db` (~26 GB; 9.2M nodes / 24.6M edges, 597 repos) | sqlite `mode=ro` only — never write |
| Slices | `graphify-app/data/graphs/<id>/graphify-out/slices/*.json` (self-contained, ≤200 nodes) | read only |
| Topic index | `graphify-app/data/graphs/TOPICS.md` | read only |
| Source code | `docker-envs/filing-cabinet/library-base/repos/` at slice `source_file`/`loc` | read only |
| FalkorDB | port 16379, compose profile `falkordb` | NOT used in phase 1 (3+-hop Cypher lives there; per-repo `falkor-push.sh` only) |

Data root override: `GRAPHIFY_DATA=/path/to/graphify-app/data`.

Caveats:
- FTS covers the top ~50k nodes per repo by degree (5.94M of 9.2M nodes
  indexed). A `find` miss is not proof of absence in giant repos — go to
  depth-1 SQL (`nodes.norm_label LIKE`) per GRAPH-FIRST.md.
- Missing DB or slices exit with code 2 and a hint, never a traceback.

## Tests

```bash
uv run --no-project --with pytest python -m pytest world/backend/test_evo_graph.py -q
```

Tests run against the real index.db read-only and skip cleanly when the
graphify data dir is absent.

## What phase 2 will add

- Hook wiring: on experiment start, inject top-3 `find` hits for the
  hypothesis text into the subagent brief (opt-out per run) — rides the
  evo plugin surface (PORT-PLAN Track B item 3).
- Experiment-history graph: our runs stored back as nodes/edges
  (experiments as nodes, gates/scores as edges) to feed the ML layer's
  predictive frontier strategy.
- FalkorDB path queries for "what's connected to this failure" style
  multi-hop questions.
