# Session handoff — Graphify↔Evo bridge built (retrieval + evidence write-back)

Date: 2026-07-24
Status: **all work is in the working tree; nothing committed anywhere.** Safe to
restart — nothing is mid-write; the evidence DB is only created on demand.

This session built the headline open item from the prior handoff: the
**Graphify brief-injection + experiment write-back** integration (roadmap
Milestone 3). It is additive — nothing existing was deleted or rewritten. Prior
context: `SYSTEM-ONBOARDING.md`, `GRAPHIFY-FIRST-HANDOFF.md`, `BUILD-DROPOFF.md`,
`DEVELOPMENT-ROADMAP.md`.

## Repos & locations
- Evo (lab home base): `/home/npwad/coding/docker-envs/projects/evo-myworld`
- Graphify (library index): `/home/npwad/coding/docker-envs/projects/graphify-app`
  — `data/index.db` is **27 GB** (9.2M nodes / 24.6M edges, 647 graph dirs);
  `GRAPH-FIRST.md` is the pull protocol.

## Test environment
Native pytest runs from the venv created in a prior session (system python has no pip):
```bash
cd /home/npwad/coding/docker-envs/projects/evo-myworld
. .venv-test/bin/activate            # or recreate: uv venv .venv-test && ...
export PYTHONPATH=plugins/evo/src
python -m pytest tests/unit -q
```
**Known environmental red (NOT code):** ~11 tests fail because
`plugins/evo/.venv` is root-owned (Docker build). Clear with
`sudo rm -rf plugins/evo/.venv`. Full suite otherwise collects **972** tests.

---

## What was built this session — `evo.graph` package

New first-class package `plugins/evo/src/evo/graph/` that **promotes, not
replaces,** the read-only phase-1 bridge `world/backend/evo_graph.py` (kept in
place, its 12 tests still green). Followed the graph-first protocol: pulled prior
art from the real index via SQL/FTS **before** writing code; every module cites
its source in-file.

| module | role | prior art (attributed in-file) |
|---|---|---|
| `graph/schema.py` | evidence vocabulary: 18 node kinds / 22 relations / 13 failure classes — makes the roadmap graph model executable | roadmap + OpenLineage naming |
| `graph/store.py` | read-only retrieval: reuses phase-1 FTS `find`/`slice`; ADDS bounded 1–2-hop `neighbors`/`callers`/`subgraph` over `edges` | graphify `serve.py`, tencentdb-agent-memory, PostHog `TraceNeighborsQuery` |
| `graph/candidates.py` | graph-candidates contract: provenance, `license=unverified` (needs manual check), repo-diverse rerank, JSON round-trip | GRAPHIFY-FIRST contract spec |
| `graph/writeback.py` | experiment evidence graph in a **separate** `.evo/graph/evidence.db` (source index stays immutable); MERGE-upsert nodes/edges, SHA-256 content-addressed artifacts, DERIVED_FROM/BEAT lineage queries | openwhisk `ArtifactStore`, airflow `OpenLineageAdapter`, HKUDS `SqliteStrategyStore`, FalkorDB MERGE |
| `graph/inject.py` | read-only brief injection; opt-out per run via `EVO_GRAPH_INJECT`; retrieval≠selection framing; injectable retrieval seam (token-free tests) | GRAPHIFY-FIRST "retrieval hook" |
| `graph/commands.py` | CLI dispatcher (kept out of the giant `cli.py`) | — |

**CLI (all live):**
`evo graph {find, neighbors, subgraph, slice, candidates, inject, record, lineage, stats, export}`
— data dir via `$GRAPHIFY_DATA` or `--data-root`.

**Wiring:** `cli.py` was **only appended to** — new `cmd_graph` + `graph`
subparser (461 insertions, no existing command changed). `main()` dispatches via
`args.func(args)`.

**Tests:** `tests/unit/test_graph_{schema,store,candidates,writeback,inject}.py`
— **59 passing** (+12 preserved phase-1 = 71 green together). Write-back is fully
hermetic (temp SQLite); retrieval tests skip cleanly when `index.db` is absent.

**Verified end-to-end** against the real 27 GB index + a real temp workspace:
retrieve → build candidates (found NixOS content-addressed store, etc.) → inject
into a brief → `record` experiments → gated `BEAT` comparison → `record_failure`
→ cite sources → walk `lineage`. `evo graph stats` showed the expected
node/edge/artifact counts.

### Files added this session (all untracked — need `git add`)
```
plugins/evo/src/evo/graph/{__init__,schema,store,candidates,writeback,inject,commands}.py
tests/unit/test_graph_{schema,store,candidates,writeback,inject}.py
```
### Existing files modified this session (additive)
```
plugins/evo/src/evo/cli.py     (cmd_graph + graph subparser only)
plugins/evo/README.md          (## Graphify bridge section)
world/backend/NOTES.md         (## Phase 2 addendum)
HANDOFF.md                     (this file)
```
Other `M` files in `git status` (CHARTER, lab-loop.*, ideator, skills, core.py,
backends/*, pyproject, racetrack/STATUS) are **pre-existing** changes from earlier
sessions — untouched this session, preserved as-is.

---

## Open / not done (next session)

- **Root-owned `plugins/evo/.venv`** blocks `uv run evo` + ~11 tests (needs `sudo`).
- **Graphify bridge — remaining wiring (capability exists, just not called from the live loop):**
  - auto-inject prior art into dispatch briefs during a run — call
    `inject_prior_art` from `cmd_run`/dispatch (gated on `EVO_GRAPH_INJECT`).
  - auto-`record` experiments on commit — call `EvidenceGraph.record_experiment`
    from `cmd_run` after a commit (and `record_failure`/`record_comparison` on discard/race).
  - incremental re-index of promoted commits; FalkorDB push of `evidence.db` for
    3+-hop lineage; dashboard feed off `evo graph export`.
- **Nix flake** (`plugins/evo/env/nixos/flake.nix`) added earlier, never built (no Nix on host).
- Mission-DAG dashboard endpoints / dispatch auto-attach — still not built.
- Next feature candidates: evolutionary/GEPA-reflective generation; multi-metric +
  spans evidence (upgrades the Pareto frontier); judge-based guardrails.

## Commit guidance
Nothing committed — matches the repo's standing posture. When ready, the new
graph package + its tests are a clean additive commit; `cli.py`/`README.md`/
`world/backend/NOTES.md` are the only touched-existing files from this session.
Preserve the unrelated pre-existing working-tree changes.

## Quick resume check (after restart)
```bash
cd /home/npwad/coding/docker-envs/projects/evo-myworld
. .venv-test/bin/activate && export PYTHONPATH=plugins/evo/src
python -m pytest tests/unit/test_graph_*.py world/backend/test_evo_graph.py -q   # expect 71 passed
python -c "from evo.cli import main; main(['graph','find','dedup','--limit','3'])"  # live retrieval
```
