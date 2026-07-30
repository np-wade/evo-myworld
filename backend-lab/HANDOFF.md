# Backend Lab — HANDOFF: running the tests

Audience: whoever (human or seat) picks this up next. Everything is docs-only
right now — no test code has been built yet. This file is the run-book for
turning the identified tests and race requests into executed results.

## 1. File paths — everything this pass produced

Catalog (converted from the dead :8765 page):
- `/home/npwad/coding/docker-envs/projects/evo-myworld/repository-catalog.md`
- `/home/npwad/coding/docker-envs/projects/evo-myworld/repository-catalog.index.json`
- original: `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack_repository_catalog.html`

Backend lab root: `/home/npwad/coding/docker-envs/projects/evo-myworld/backend-lab/`
- `README.md` — what the lab is, standing rules
- `INDEX.md` — roll-up: counts, all 16 races, headline findings, corrections
- `HANDOFF.md` — this file

storage-engine (`backend-lab/storage-engine/`):
- `README.md`, `CANDIDATES.md`, `TESTS.md`
- `requests/fts-engine-recall.md`
- `requests/embedded-vector-recall.md`
- `requests/hybrid-recall-rrf.md`
- `requests/graph-traversal-store.md`

interlinking (`backend-lab/interlinking/`):
- `README.md`, `CANDIDATES.md`, `TESTS.md`
- `requests/entity-id-dedup.md`
- `requests/cross-app-entity-resolution.md`
- `requests/link-retrieval-recall.md`
- `requests/llm-link-rerank.md`

pipelines (`backend-lab/pipelines/`):
- `README.md`, `CANDIDATES.md`, `TESTS.md`
- `requests/event-log-append-replay.md`
- `requests/cross-app-trace-stitching.md`
- `requests/live-tail-fanout.md`
- `requests/front-door-port-routing.md`

library-triage (`backend-lab/library-triage/`):
- `README.md`, `CANDIDATES.md`, `TESTS.md`
- `requests/triage-ranker-blend.md`
- `requests/repo-duplicate-detection.md`
- `requests/triage-cache-eviction.md`
- `requests/graph-reachability-extraction.md`

Key external references the tests lean on:
- race format + loop: `evo-myworld/racetrack/RACETRACK.md`, `evo-myworld/racetrack/run-race.sh`
- skip-cleanly pattern: `evo-myworld/world/backend/test_evo_graph.py`
- incumbent store schema: `graphify-app/src/search/db.js:18-52` (DB: `graphify-app/data/index.db`, 26GB, read-only via `evo-myworld/world/backend/evo_graph.py`)
- in-house challenger: `witt-spine/crates/spine-trunk/schema.sql`, `witt-spine/crates/spine-trunk/src/recall.rs`
- identity incumbent: `evo-myworld/plugins/evo/src/evo/graph/writeback.py`
- corpus: `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/` (616 repos, ~40GB, `CARD.md` each, `CARDS-META.json` one level up)

## 2. Build order (cheapest value first)

1. **Contract tests A1–A12** (`pipelines/TESTS.md`, group a). Pure file/port/schema
   checks, no heavy deps, minutes of work. Expect **A11 + A12 to FAIL** — they
   encode the real port collisions (8787, 8080); that's the point.
2. **Storage-engine races** (`storage-engine/requests/`) — highest strategic value;
   `hybrid-recall-rrf` decides the one-store question.
3. **Library-triage signals S1–S8** (`library-triage/CANDIDATES.md`) — all sources
   verified on disk; signals feed every triage race.
4. **Interlinking races** — `llm-link-rerank` is blocked until Ollama runs.
5. **Pipeline flow tests B1–B8** — after contract tests exist to lean on.

## 3. How to run a race (existing machinery)

```bash
# 1. human reviews a request, then files it:
cp evo-myworld/backend-lab/<section>/requests/<slug>.md \
   evo-myworld/racetrack/requests/<slug>.md

# 2. run it through the steward loop:
bash evo-myworld/racetrack/run-race.sh evo-myworld/racetrack/requests/<slug>.md

# 3. result lands in:
#    evo-myworld/racetrack/results/<slug>.md
#    request moves to racetrack/requests/done/
```

Race rules that bind any test you build (from `RACETRACK.md` + scrapler-eval CONTRACT):
- ≥2 candidates, each with a real repo path you actually read.
- Benchmarks: seconds not minutes; data generated or <10MB; ≤2 parallel heavy jobs (12GB box).
- Fixtures deterministic and checked in with answer keys; no candidate sees the key.
- Missing-dep candidate = skip + record, never crash.
- Core harness code pure stdlib; heavy deps only behind `available()` in adapters.

## 4. Environment facts / blockers

- Python evo plugin venv (host): `evo-myworld/plugins/evo/.venv-host/bin/python`
  (the root-owned `plugins/evo/.venv` breaks pytest collection — do not use it).
- JS tests in sibling apps run via `node --test` (node is available).
- `falkordb` and `ollama` docker images are already local; `meilisearch` (~150MB)
  and `qdrant` (~120MB) need a one-time `docker pull`.
- **Ollama daemon is DOWN** (`curl 127.0.0.1:11434` → 000). Blocks:
  `interlinking/requests/llm-link-rerank.md` and the LLM-judged triage tier.
  Start it before filing those.
- LEANN carries build risk (in-repo pip package); its race request already
  specifies skip-cleanly if the build fails.
- Full per-repo GROUP BY over the 26GB index.db took **375s** — never do it in a
  test; that's what `graph-reachability-extraction` is for. Use the skip-cleanly
  read-only pattern for big-DB tests.

## 5. Known-failing / known-stale (do not "fix" by deleting the test)

- A11/A12 (port collisions 8787 information-processer↔witt-link-server,
  8080 evo-dashboard↔localai) — fail until someone picks ports and updates the
  registry in `backend-lab/README.md` + the apps' configs.
- `world/backend/evo_graph.py:8` docstring says 597 repos/9.2M nodes — stale;
  index.db covers all 616 repos.
- `CARDS-META.json`: 301 carded + 316 uncarded = 617 ≠ 616 — data-quality flag (S8).
- `graphify-app/data/graphs_quarantine/` doesn't exist until first use —
  triage cull dry-runs must create it, never delete into the void.

## 6. Definition of done for the next pass

- [ ] A1–A12 contract tests executable and run; A11/A12 failing as documented.
- [ ] ≥1 storage-engine race executed with results in `racetrack/results/`.
- [ ] Triage signals extracted for all 616 repos; first keep/cull leaderboard reviewed by Nicholas (no deletions without sign-off).
- [ ] Race results visible where the lab can see them (note: wiring results into the Evo HQ dashboard was planned but deferred — the plan is archived in the kimi session plan file if resumed).
