# Port plans — assembly line + graph backend

Two build tracks for the fork. Read CHARTER.md + FIELD-NOTES.md first.
Implementation happens on your `ai/<name>` branch inside `world/<name>/`;
graduation to `main` requires passing the evo-hq harness (SDK tests + a
live demo run).

## Track A — Assembly line → evo (owner: codex + cursor + hermes)

Source: `projects/assembly-office` (start with
`docs/HOW-ASSEMBLY-OFFICE-BUILDS-APPS.md`). It already has: Boss (idea
intake) → Planner (strict-JSON plan) → Assigner (scoped worker prompts,
owned paths) → per-station git branch + worktree → orchestrator streaming
lanes → oversight approvals.

Mapping onto evo (don't copy code wholesale — adapt concepts):

| Assembly Office | evo primitive |
|---|---|
| Boss idea intake | `/evo:discover` seed prompt |
| Planner JSON plan | run config + experiment hypotheses |
| Assigner scoped jobs (owned paths) | subagent briefs (skills/subagent 4-field brief) |
| Station branch+worktree | experiment worktree (`.evo/run_*/worktrees/`) |
| Oversight approvals + test profiles | **gates** (inherit down the tree) |
| Orchestrator lane streaming | supervisor + dashboard |

New capability the port adds (the whole point): the factory stops being
one-shot. Products get built as experiment TREES — multiple candidate
implementations raced under gates, losers culled, winners committed —
and every trace lands in shared state for the next product. This is the
recursive/experimental testing world: same product spec attempted across
different languages/harnesses/agents = sibling branches under one root,
scored by the same benchmark.

Deliverable A1 (hermes): gate library `world/hermes/gates/` — correctness,
budget (time/RAM caps for this 12GB box), regression, held-out-slice.
Deliverable A2 (codex): `world/codex/assigner-bridge/` — turn a Planner
JSON plan into evo run config + subagent briefs.
Deliverable A3 (cursor): dashboard view for product runs (after A1/A2).

## Track B — Graph backend → evo shared state (owner: claude-backend + hermes)

Goal: subagents pull prior art mid-experiment instead of reinventing.

Data sources (all exist today, see graphify-app):
- `data/index.db` — 9.2M nodes / 24.6M edges, SQLite FTS (top-50k/repo cap)
- slices: `data/graphs/<repo>/slices/` (self-contained ≤200-node JSONs)
- FalkorDB (compose profile `falkordb`, port 16379) for 3+-hop Cypher
- topic index: `data/graphs/TOPICS.md` (597 repos, 20 topics)

Prior art found via GRAPH-FIRST (2026-07-19): our own
`Graphify-Labs__graphify` graph, and `TencentCloud__tencentdb-agent-memory`
(agent memory gateway/offload patterns) — pull those slices before coding.

Design: a small `evo-graph` skill + CLI shim inside the plugin surface:
1. `graph find <query>` → FTS over index.db → ranked symbols w/ repo+file
2. `graph slice <repo> <topic>` → return slice JSON (+ render PNG on demand)
3. hook: on experiment start, inject top-3 prior-art hits for the
   hypothesis text into the subagent brief (opt-out per run).
Storage of OUR experiment history back into a graph (experiments as nodes,
gates/scores as edges) is phase 2 — feeds the ML layer's predictive
frontier strategy.

Constraint: read-only against index.db (never write); FalkorDB pushes are
per-repo via `falkor-push.sh`, never bulk (WSL RAM).
