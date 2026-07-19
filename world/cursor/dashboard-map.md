# Dashboard / graph / scratchpad map

Mapped 2026-07-19 (cursor). The thin wrappers under `scripts/` are entrypoints
only; real logic lives in `plugins/evo/src/evo/`.

## Entrypoints

| Script | What it does |
|---|---|
| `scripts/dashboard.py` | `from evo.dashboard import main` → Flask app on `EVO_DASHBOARD_HOST`/`EVO_DASHBOARD_PORT` (default `127.0.0.1:8080`) |
| `scripts/graph.py` | `evo.cli.main(["tree"])` → prints `ascii_tree(...)` to stdout |
| `scripts/scratchpad.py` | `evo.cli.main(["scratchpad"])` → prints `build_scratchpad(...)` to stdout |

CLI twins: `cmd_tree` / `cmd_scratchpad` in `plugins/evo/src/evo/cli.py`
(lines ~4157 and ~4275). Same render functions the dashboard HTTP routes call.

Lifecycle: `dashboard_supervisor.py` owns `.evo/supervisor.pid`, `dashboard.pid`,
rotated `dashboard.log` / `supervisor.log`. Spawns/respawns the Flask child.

## Where data lives (per active run)

`meta.json` at `.evo/meta.json` points at the active run (`"active": "run_0000"`).
`workspace_path()` resolves to `.evo/<active>/`. Everything below is under that
run dir unless noted.

| File / dir | Role |
|---|---|
| `.evo/meta.json` | Active run id, `next_run`, host |
| `.evo/project.md` | Top-level project brief (not per-run) |
| `.evo/run_NNNN/config.json` | Target, benchmark, metric, frontier_strategy, runtime_env, epochs |
| `.evo/run_NNNN/graph.json` | **The experiment tree** (single JSON object) |
| `.evo/run_NNNN/annotations.json` | `{ "annotations": [ {experiment_id, task_id, analysis, timestamp} ] }` |
| `.evo/run_NNNN/infra_log.json` | `{ "events": [...] }` — frontier picks, infra notices |
| `.evo/run_NNNN/experiments/<exp_id>/` | Per-node artifacts |
| `.../attempts/NNN/outcome.json` | Attempt score/tasks (pareto frontier reads this) |
| `.../attempts/NNN/traces/*.json` | Per-task traces |
| `.../attempts/NNN/diff.patch`, `benchmark.log`, `.trackio_url` | Diff, logs, optional HF Trackio marker |
| `.../checks/NNN/check.json` or `gate_check.json` | Gate/run check summaries (dashboard `_checks_summary`) |
| `.evo/run_NNNN/worktrees/` | Git worktrees for experiments |
| `pool-<key>.json` / `remote-<key>.json` | Backend lease state (under workspace) |

Legacy fallback: if no `meta.json` but `.evo/config.json` exists, the workspace
*is* `.evo/` itself (`workspace_path` in `core.py`).

## How the experiment tree is stored

`graph.json` shape from `default_graph()` in `core.py`:

```json
{
  "root": "root",
  "next_id": 0,
  "workspace_notes": [],
  "nodes": {
    "root": {
      "id": "root",
      "parent": null,
      "children": [],
      "status": "root",
      "hypothesis": "synthetic root",
      "score": null,
      "eval_epoch": null,
      "gates": [],
      "branch": null,
      "worktree": null,
      "commit": null,
      "pruned_reason": null,
      "prune_kind": null,
      "created_at": "...",
      "updated_at": "..."
    }
  }
}
```

Child experiments are siblings under `nodes` keyed by id (`exp_0000`, …).
Edges are `parent` + `children[]`. Statuses the UI cares about: `active`,
`evaluated`, `committed`, `discarded`, `pruned`, `failed` (plus synthetic
`root`). `update_node` advisory-locks `graph.json.lock` and writes atomically.

**Frontier** (`frontier_nodes` in `core.py`): committed leaves with no
committed/active (non-invalidated) child. Strategy ranking lives in
`frontier_strategies.py`; scratchpad and `/api/frontier` both call `pick`.

## Flask routes (`plugins/evo/src/evo/dashboard.py`)

Static UI: `plugins/evo/src/evo/static/` (`index.html`, `app.js`, `style.css`).
`GET /` serves `index.html`. Poll loop in `app.js` `fetchAll()` hits stats +
graph + runs + workspace + frontier together.

### Read

| Method | Path | Returns |
|---|---|---|
| GET | `/` | `index.html` |
| GET | `/api/stats` | Metric, best/baseline scores, status counts, frontier size, epoch |
| GET | `/api/graph` | Full `graph.json` with `_public_node` enrichment (redacted backends, checks, effective_status, lineage block) |
| GET | `/api/tree` | Plain text `ascii_tree` (box-drawing) |
| GET | `/api/scatter` | `[{id, score, status, epoch}, …]` non-root |
| GET | `/api/node/<exp_id>` | One enriched node |
| GET | `/api/node/<id>/traces` | Latest attempt's `traces/*.json` map |
| GET | `/api/node/<id>/traces/<task_id>` | One `task_<id>.json` |
| GET | `/api/node/<id>/log/<path>` | Log text; `?tail=N` / `?offset=M`; bare names redirect to latest attempt |
| GET | `/api/node/<id>/logs` | List `.log`/`.out` in latest attempt |
| GET | `/api/node/<id>/trackio` | Optional Trackio URL + sparkline scalars |
| GET | `/api/active` | Nodes with `status == active` |
| GET | `/api/scratchpad` | Plain text from `build_scratchpad` |
| GET | `/api/annotations` | Raw annotations.json |
| GET | `/api/runs` | Run list from meta + per-run config |
| GET | `/api/frontier-strategy` | Registry + current + default |
| GET | `/api/frontier` | Strategy-ranked picks (`?seed=N`, default 0 for stable UI) |
| GET | `/api/workspace` | Execution/runtime/backend summary |

### Write

| Method | Path | Effect |
|---|---|---|
| POST | `/api/node/<id>/prune` | Body `{reason, kind: exhausted\|invalid, yes?}` → status pruned |
| POST | `/api/runs/<run_id>/activate` | Flip `meta.active` |
| POST | `/api/frontier-strategy` | Persist strategy into config.json |
| POST | `/api/workspace/execution` | Execution settings |
| POST | `/api/workspace/runtime-env` | Runtime env sources |
| POST | `/api/workspace/runtime` | Runtime settings |
| POST | `/api/workspace/runtime-variables` | Runtime variables |
| POST | `/api/direct` | Queue inject event (workspace or per-exp) + touch markers |

## How the tree is rendered

Three consumers, one source (`graph.json`):

1. **Dashboard timeline** (`static/app.js`). Loads `/api/graph` into
   `state.graph`. `buildVisibleRows()` does a tidy-tree layout: spine-first
   child sort (path to best committed score on row 0), post-order row
   assignment, collapse/scope filters. `renderTimeline` draws HTML bars + an
   SVG connector layer. Status chips and view modes (`all` / `frontier`)
   filter without recomputing frontier locally — frontier ids come from
   `/api/frontier`. Scatter strip is a separate SVG of score-over-time from
   the same node set (stats/graph poll; `/api/scatter` exists but the main
   strip builds from `state.graph`).

2. **CLI / `/api/tree`**. `ascii_tree` walks `children` with `├──`/`└──`,
   one line per node: `id status score=… epoch=… gates=N hypothesis`.

3. **Scratchpad** (`scratchpad.build_scratchpad`). Bounded markdown for
   agents: Status line → compact Tree (2-space indent, glyphs A/C/E/D/P/F,
   `★` on best path, collapses irrelevant subtrees with `(+N best=…)`) →
   Frontier → Awaiting Decision → Gates → Recent (only if tree overflows
   cap 25) → Annotations → What Not To Try → Infra Log → Notes →
   Drill-downs menu. Caps: frontier 50, awaiting 10, annotations 15, notes 20.

Node detail drawer (diff / traces / logs / prune / Trackio) hits the
`/api/node/...` routes above when you click a timeline bar.

## Quick mental model

```
scripts/dashboard.py  →  evo.dashboard.create_app (Flask)
                              │
                              ├─ reads  .evo/meta.json → run_NNNN/
                              ├─ graph  ← graph.json
                              ├─ UI     ← static/app.js polls /api/*
                              └─ text   ← /api/tree, /api/scratchpad

scripts/graph.py      →  evo tree      → ascii_tree(graph)
scripts/scratchpad.py →  evo scratchpad → build_scratchpad(root)
```

No separate graph DB here. The "experiment tree" is one JSON file per run.
The lab's graphify/FalkorDB backend is a different store; queue item 2 is
about feeding *that* into this dashboard later.
