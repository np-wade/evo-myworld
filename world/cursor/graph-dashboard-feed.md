# How the graph backend can feed the dashboard

Cursor note 2026-07-19. Builds on `world/cursor/dashboard-map.md` and
Track B phase 1 (`world/backend/evo_graph.py`).

## Two stores, do not merge them

| Store | Path / API | Owns |
|---|---|---|
| Experiment tree | `.evo/<run>/graph.json` → `/api/graph` | Live run: nodes, scores, frontier, prune |
| Prior-art library | graphify `index.db` + slices via `evo_graph.find` / `slice` | 9.2M symbols across ~597 repos |

The dashboard today has **one** data source for the timeline. A second source
must stay a **side channel** — never rewrite `graph.json` from FTS hits.
Mixing them would break frontier/scratchpad contracts and bloat the lock file.

## Concrete feed points (smallest first)

### 1. New read-only Flask routes (proxy `evo_graph`)

Add beside existing routes in `plugins/evo/src/evo/dashboard.py`:

| Route | Backs | Returns |
|---|---|---|
| `GET /api/library/find?q=&repo=&limit=` | `evo_graph.cmd_find` (import as lib, not subprocess) | JSON list: `{repo_id, label, kind, source_file, loc, degree, score}` |
| `GET /api/library/slice?repo=&topic=` | `evo_graph.cmd_slice` | Slice paths + summaries (topic_terms, counts, hubs) |

Constraints from FIELD-NOTES / evo_graph:
- Open `index.db` **read-only** (`mode=ro`); missing DB → empty payload + 503-ish message, no traceback.
- Cap `limit` (default 20, hard max 50) — FTS is 5.94M of 9.2M nodes; unbounded queries hurt WSL2 RAM.
- Reuse safe FTS quoting (`"tok"` AND-join, OR fallback) already in `evo_graph._fts_query`.

### 2. Node drawer enrichment (UI consumer)

In `static/app.js`, when a timeline bar opens the node drawer, if
`hypothesis` / branch name has searchable tokens, optionally call
`/api/library/find?q=<tokens>&limit=10` and render a **"Prior art"** strip
under traces/logs — not on the timeline spine.

Query seed: first content words of `node.hypothesis` (drop stopwords the
same way `_query_terms` does). Do **not** auto-query on every poll —
only on drawer open (one-shot per exp_id) so the 12 GB box stays quiet.

### 3. Scratchpad injection (agent consumer)

`build_scratchpad` today is purely `.evo/` files. Optional appendix section
**"Library hints"** (cap 5 lines): if `EVO_GRAPHIFY=1` or `GRAPHIFY_DATA`
is set, run one `find` on the best committed node's hypothesis tokens and
paste ranked labels. Agents already read `/api/scratchpad`; this is the
lowest-UI path to make GRAPH-FIRST visible in the run loop.

### 4. What not to do (yet)

- Do **not** put library nodes into `graph.json` `nodes{}`.
- Do **not** poll `/api/library/*` from `fetchAll()` — keep the main poll
  on experiment stats/graph/frontier only.
- Do **not** load FalkorDB into the Flask process until Track B says so;
  phase 1 sqlite FTS is enough for a feed prototype.
- Product-run view (queue A3) can later host a dedicated library panel;
  this note is the seam, not that UI.

## Suggested wiring sketch

```
app.js drawer open
    → GET /api/library/find?q=…
         → evo_graph find (sqlite FTS, ro)
              → JSON hits → "Prior art" strip

scratchpad (optional)
    → same find, 5-line appendix
```

## Acceptance for a later PORT

A feed is "working" when: (1) `/api/library/find` returns ranked hits with
DB present and `[]` + clear message without; (2) drawer shows prior art
without changing `/api/graph` shape; (3) experiment tree lock/write path
untouched. Bench later: BASE_CMD = dashboard without library routes,
NEW_CMD = with them, compare response shape / latency on one query.
