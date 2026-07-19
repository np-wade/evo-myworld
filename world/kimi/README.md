# Kimi seat — `evo-river` dashboard surface

A small, creative front-end module for evo-myworld: render the experiment tree
as a horizontal **time-river** in the terminal and on the dashboard.

## What it is

- `world/kimi/evo_river.py` — CLI + library that reads evo's `graph.json` and
  draws a left-to-right river:
  - root upstream, later generations downstream
  - `*` marks frontier nodes
  - `▲` marks the current best spine
  - ANSI colors for status (committed, failed, discarded, active, ...)
- `world/kimi/test_evo_river.py` — pytest suite (stdlib + evo.core).
- `world/kimi/fixtures/demo-graph.json` — synthetic tree for manual demos and
  the bench.

## CLI usage

```bash
# Inside an evo workspace (reads .evo/<active-run>/graph.json)
uv run --project plugins/evo python world/kimi/evo_river.py

# Against a fixture
uv run --project plugins/evo python world/kimi/evo_river.py \
    --graph world/kimi/fixtures/demo-graph.json --metric min --no-color
```

## Dashboard surface

`/api/river` is wired into `plugins/evo/src/evo/dashboard.py` next to `/api/tree`.
It returns a plain-text river rendering of the active run.

## Bench

`world/kimi/experiment.env` compares the existing `evo tree` ASCII renderer
against the new river renderer on the same fixture. The lab loop re-runs it
each cycle and records whether outputs differ.

## Tests

```bash
cd world/kimi
uv run --project ../../plugins/evo --with pytest python -m pytest test_evo_river.py -q
```

## Why this module

Kimi's seat is front-end / creative. Before building a full UI, this proves
real connectivity to evo's graph data and gives the lab a second way to *see*
the experiment tree — useful when the dashboard is disabled in sandbox mode
(`evo tree` is the fallback; `evo-river` is the creative variant).
