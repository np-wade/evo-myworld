# Evo + Graphify — System Onboarding

Practical onboarding + findings report. Read `BUILD-DROPOFF.md` (same dir) first for
build history; this doc tells you where everything is, how the two systems fit, and
what is currently broken. Target: ~10 minutes to full orientation.

All paths absolute. File:line citations were verified against the code on 2026-07-24.

---

## 1. System overview

Two cooperating repos, clean separation of concerns:

- **Evo** — `/home/npwad/coding/docker-envs/projects/evo-myworld`
  - Python orchestration plugin: `plugins/evo/src/evo/`
  - `std`-only Rust execution runner: `plugins/evo/bin/evo-env-runner/`
  - Owns the **experiment tree** (a git branch per node), a **mission DAG overlay**
    in `.evo/graph.json`, the dispatch/directive **agent lifecycle**, a
    content-addressed **artifact store**, and remote/environment **backends**.

- **Graphify** — `/home/npwad/coding/docker-envs/projects/graphify-app`
  - Node/Express code-graph search + **read-only** evidence / source-slice endpoints.
  - Indexes repos into per-repo `graph.json` files plus a shared ~28 GB SQLite FTS
    index at `data/index.db`.
  - Supplies **bounded, hash-addressed source evidence** — a cited slice, not a whole
    checkout. It never mutates and never schedules.

**How they fit.** Graphify is the immutable/read-only context provider: search →
bounded source range → SHA-256-addressed evidence. Evo consumes that evidence to grow
work: a goal becomes `research → build → verify → integrate` missions, each backed by
git lineage in the experiment tree, run through the existing dispatch / isolated
environment / gate pipeline, with outcomes written back as queryable state. The
governing rule (`BUILD-DROPOFF.md` §"Research basis"): *missions describe intent, the
experiment tree describes git lineage, Graphify provides read-only context, and an
independent verify mission is required before promotion.*

Closed loop today (deliberately not yet an autonomous scheduler):

```
Graphify search/context
  -> bounded, hash-addressed source slice
  -> durable research/build/verify/integrate mission
  -> existing Evo dispatch / isolated environment / gates
  -> evidence + outcome retained in Evo state
  -> dependent mission unlocked or blocked
```

---

## 2. Architecture map (per repo)

### Evo — orchestration (Python) vs execution (Rust) over versioned JSONL

- **State root `.evo/`** — schema owned by `plugins/evo/src/evo/core.py`.
  Layout: `meta.json` (active run pointer, host) → `run_NNNN/` workspace →
  `graph.json` + `config.json` + `experiments/`.
  Key seams: `core.py:167 workspace_path` (`.evo/run_0000/`), `core.py:183
  experiments_path`, `core.py:187 config_path`, `core.py:191 graph_path`,
  `core.py:132 _meta_path`. Legacy fallback treats bare `.evo/` as the workspace
  when there is no `meta.json` (`core.py:173`).

- **Execution boundary** — versioned JSONL over stdio. Python is the control plane;
  the Rust runner (`plugins/evo/bin/evo-env-runner/`) is the fast isolated executor
  (host + Docker modes). Bridge: `plugins/evo/src/evo/runner_bridge.py`
  (`RustRunnerClient`, one JSON request per line). Shared normalized test evidence:
  `plugins/evo/src/evo/language_adapters.py` (`test_envelope`, `language_adapters.py:61`).

- **Backends protocol** — `plugins/evo/src/evo/backends/`, dispatched by name in
  `backends/__init__.py:66` (`execution_backend` config key):
  - `worktree` (default) — fresh `git worktree` per experiment (`worktree.py`).
  - `gitdir` — in-place, shared git dir (`gitdir.py`).
  - `pool` — reused worktree pool (`pool.py`, `pool_state.py`).
  - `remote` — provisions a remote sandbox container (`remote.py`, `remote_state.py`,
    `sandbox_providers/`).
  - `environment.py` — versioned environment manifests + evidence envelopes + fixtures.

- **Missions** — `plugins/evo/src/evo/missions.py`. Durable DAG **overlay** stored in
  the same `.evo/graph.json`. `research/build/verify/integrate` kinds, bounded brief,
  acceptance conditions, dependency IDs, evidence refs, optional owning experiment,
  per-mission depth/child caps. Ready work unlocks only on successful deps
  (`missions.py:54 _refresh_ready`); claims are locked + idempotent per owner
  (`missions.py:150 claim`); cancel cascades to children (`missions.py:185`).
  Terminal set: `{"succeeded","failed","cancelled"}` (`missions.py:18`).

- **Artifacts** — `plugins/evo/src/evo/artifacts.py`. Content-addressed
  (SHA-256, `artifacts.py:58`) store: deterministic storage, export/import, restore,
  swap-with-backup, bounded diffs, staged script transforms. **Symlinks + path
  traversal are strictly rejected at every boundary** (`artifacts.py:106
  _reject_symlink`, `:126` normalized workspace-relative path check). CLI shuttle:
  `plugins/evo/bin/evo-artifact`.

- **Frontier / candidate selection** — `plugins/evo/src/evo/frontier_strategies.py`.
  Strategies ported/inspired from GEPA: `argmax` (`:34`), `top_k` (`:46`),
  `epsilon_greedy` (`:61`), `softmax` (`:78`), `pareto_per_task` (`:100`, the default,
  `:156`), `ucb1` (`:135`). Note the honest comment at `frontier_strategies.py:118`:
  this ports only GEPA *selection*; the "mutation + reflective LLM parts of GEPA live
  elsewhere" — i.e. candidate **generation is missing** (see §4).

### Graphify — scan → graph.json → SQLite index → engine → HTTP

- **Scan** — `src/scanner.js` / `src/cli-scan.js` produce per-repo enriched graphs
  under `data/graphs/<repo>/graph.json`.
- **Persistent index** — `src/search/db.js` builds `data/index.db` (SQLite, WAL,
  **FTS5 via `node:sqlite`**; `db.js:2`, `db.js:48 CREATE VIRTUAL TABLE nodes_fts`).
  This is the ~28 GB file — **do not open it during onboarding.**
- **Engine (two paths)** — `src/search/engine.js`. `sqliteMode()` (`engine.js:26-28`)
  routes through `data/index.db` in production, **unless `GRAPHIFY_FORCE_MEM=1`**, in
  which case it builds an in-RAM **MiniSearch** index (`engine.js:1`,
  `src/search-index.js:2`) over the enriched view and reranks by structural importance
  (degree, PageRank). Understands a facet DSL (`kind:`, `repo:`, `relation:`, `file:`,
  `lang:`, `type-glob:` — `engine.js:15-17`).
- **HTTP surface** — `src/server.js` (Express), plus read-only adapters:
  `src/evidence-server.js` (`/api/evidence*`) and `src/source-slice-server.js`
  (`/api/repos/:id/source`, `/api/tools/read-source-line-range`). Slice logic +
  guards: `src/source-slices.js`. CLI parity: `scripts/gfy.mjs`
  (`gfy source <repo> <file> <start> <end>`).

---

## 3. Confirmed flaws (ranked, with file:line)

Verified against current code. Each entry: what's wrong → one-line failure scenario.

### Evo

**(1) Rust runner stderr pipe is never drained — deadlock.**
`plugins/evo/src/evo/runner_bridge.py:44-57`. `Popen` opens `stderr=subprocess.PIPE`
but only a stdout reader thread is started (`:54-57`); nothing ever reads stderr.
*Failure:* a runner that writes >64 KB to stderr fills the OS pipe buffer and blocks
on write forever → no stdout response → killed at the 30 s timeout (`:77`), every run
lost.

**(2) No request/response id correlation — stream desync.**
`plugins/evo/src/evo/runner_bridge.py:59-89`. `_read_stdout` pushes any non-blank line
onto a FIFO queue (`:61-63`); `request()` writes a payload then blindly takes the next
queue item (`:71-74`) with no id matching. *Failure:* one stray/duplicate stdout line
(a stray log, a double-emit) permanently offsets the stream — every subsequent op
returns the *previous* op's result, silently.

**(3) Fixture `source` is an unguarded arbitrary-file read.**
`plugins/evo/src/evo/backends/environment.py:71-85`. `_safe_fixture_path` (`:39`)
guards the fixture **destination** (rejects `..`, `:44`), but the `source` branch does
`Path(str(value["source"])).read_bytes()` (`:77`) with **no allowlist and no traversal
guard** on the *source* path. Contrast `artifacts.py:106/:126`, which is strict.
*Failure:* an environment manifest with `{"source": "/etc/passwd"}` or
`{"source": "../../secret"}` exfiltrates any host-readable file into the sandbox.

**(4) Cross-process re-lease re-provisions a live sandbox — orphaned billed container.**
`plugins/evo/src/evo/backends/remote.py:287-288`. When a free slot is re-leased, the
code returns `needs_provision = (handle is None)` based only on *this* process's
in-memory `self._handles` (`:287`). *Failure:* process B leases a slot that process A
already provisioned; B's `_handles` is empty, so B provisions a **second** container
for the same slot — the first is never destroyed and keeps billing (orphan leak).

**(5) `finish_mission("blocked")` is a permanent dead-end.**
`plugins/evo/src/evo/missions.py:167-182`. `"blocked"` is an accepted completion status
(`:168`) but is **not** in `TERMINAL_STATUSES` (`missions.py:18`, only
`succeeded/failed/cancelled`). So a blocked mission is non-terminal, yet `_refresh_ready`
(`:54`) only promotes `ready` work — there is no path back from `blocked` to `ready`.
*Failure:* a mission marked `blocked` can never re-run, never complete, and never be
cancelled by the terminal guard → stuck forever, silently holding up dependents.

**Also (environment/tooling, not logic bugs):**
- **Broken root-owned venv.** `plugins/evo/.venv` is owned by `root`
  (verified: `drwxr-xr-x root root`), so `uv run evo` fails on this host. Use the
  native test venv in §5 instead.
- **Pytest mis-collection.** `language_adapters.py` exports a *source* function named
  `test_envelope` (`language_adapters.py:61`) — pytest collects it as a test and it
  errors. Harmless to prod, noisy in the suite.

### Graphify

> The auth (6) and extension-allowlist (7) flaws below are being fixed in a
> **parallel effort** — flag, don't re-patch here.

**(6) `LAUNCH_TOKEN` defaults to `''` → all `/api/*` unauthenticated.**
`src/config.js:20` (`process.env.GRAPHIFY_LAUNCH_TOKEN || ''`) +
`src/server.js:42-52`. `checkToken` short-circuits with `if (!LAUNCH_TOKEN) return
next();` (`server.js:43`) — an empty token disables auth entirely. *Failure:* default
deploy on a `0.0.0.0` bind exposes every endpoint, including mutating `POST`s, to the
network with no credential.

**(7) Source slices block traversal but have no extension allowlist.**
`src/source-slices.js:57` (`resolveSourceFile`). Traversal/symlink-escape/absolute
paths are correctly rejected (`:51-79`), but any repo-relative regular file is served —
there is no extension allowlist. *Failure:* `?file=.env` or `?file=config/keys.pem`
inside an indexed repo is happily returned as a numbered, hash-stamped slice.

**(8) The SQLite production path is effectively untested — mem vs sqlite diverge.**
`test/engine.test.js:6` sets `process.env.GRAPHIFY_FORCE_MEM = '1'` before importing the
engine, so **every** engine test exercises the in-RAM MiniSearch path and never
`data/index.db` (see the comment block at `engine.test.js:1-6` and the gate at
`engine.js:26-28`). *Failure:* behaviour that differs between the two backends — type
globs like `*()`, `repo:`-by-name resolution, `impact()` totals — can be correct in
tests (mem) and wrong in production (sqlite) with zero test signal.

**(9) Synchronous `JSON.parse` of up to 64 MB `graph.json` blocks the event loop.**
`src/graph-store.js:23`, `src/search/enrich.js:104`, `src/search-index.js:207` /
`:231` — all do `JSON.parse(fs.readFileSync(p, 'utf8'))` on a request path.
*Failure:* parsing one large repo graph freezes the single Node event loop for the
whole parse duration, stalling every concurrent request (the file's own comment at
`graph-store.js:8` acknowledges the cost).

---

## 4. Opik-inspired feature roadmap

**Context.** Opik (`comet-ml/opik`, Apache-2.0, cloned at
`/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/opik`) is a mature
LLM eval/observability/optimization platform. Evo today optimizes a **single opaque
scalar** (`--metric max|min`); its real sophistication is candidate **selection**
(`frontier_strategies.py` — argmax/top-k/ε-greedy/softmax/UCB1/Pareto-per-task, ported
from GEPA). Opik supplies the missing halves: **LLM-as-judge metrics** and candidate
**generation**. A curated, low-coupling port-kit is staged at
`/tmp/claude-1000/-home-npwad/36156436-050e-4416-8c20-0997a7766062/scratchpad/opik-portkit/`
(see its `MANIFEST.md`). We port **prompts, parsers, presets, and search logic** —
*not* Opik's cloud/`rest_api`/litellm shells — driving them with Evo's own Claude call
and `.evo/graph.json` state. Keep the Apache-2.0 NOTICE on anything adapted.

| Feature | What it adds | Evo seam |
|---|---|---|
| **G-Eval judge** *(being ported now → `judges.py`)* | Generic rubric-driven LLM-as-judge (CoT: derive eval steps → score 0–10 + reason, normalized to [0,1]). Turns the single opaque scalar into a qualitative layer. | Call from `cli.cmd_run` after a benchmark; write the score into the attempt `result.json`. Plugs into `verify` missions + the `evo:benchmark-reviewer` subagent. From `opik-portkit/judges/g_eval/`. |
| **MetaPrompt brief for `evo:ideator`** | LLM-critique-and-rewrite meta-prompts: "here's what failed" → concrete next candidate. Supplies the candidate **generation** that `frontier_strategies.py:118` admits "lives elsewhere". | New `failure_analysis`-style brief for the `evo:ideator` subagent. From `opik-portkit/optimizer-prompts/metaprompt_prompts.py`. Lowest effort, highest fit. |
| **Optuna parameter optimizer** | Bayesian/TPE search over call params (temperature, top_p, …) — Evo has *no* hyperparameter optimizer at all. | New `frontier_strategies` sibling or `evo config optimize`; optimize model/config knobs of a fixed target alongside prompt search, record each trial as an experiment. Adds pure-python `optuna` dep. From `opik-portkit/parameter-search/`. |
| **Multi-metric + spans/tracing evidence** | Trajectory-accuracy judge scores an *agent trajectory* (tool calls + steps), not just final output; spans give structured multi-metric evidence. | Feeds structured write-back (`BUILD-DROPOFF.md` objective 6) and scores Evo dispatch/explorer runs. From `opik-portkit/judges/trajectory_accuracy/`. |
| **Judge-based guardrails on generated actions** | Reuse the judge layer (hallucination/factuality templates) as guardrails gating agent-generated actions before they run. | Wrap the dispatch/directive agent lifecycle; a `verify` mission or pre-dispatch gate rejects unsafe generated actions. From `opik-portkit/judges/hallucination/`, `factuality/`. |

Suggested first three ports by effort (from the port-kit MANIFEST): (1) G-Eval judge
→ `evo judge` + auto-score on commit (~½ day); (2) metaprompt → new `evo:ideator` brief
(~hours); (3) Optuna optimizer → `evo config optimize` (~1 day, adds optuna).

---

## 5. Quick-start / useful commands

### Evo — native test setup (works around the broken root-owned `.venv`)

```bash
cd /home/npwad/coding/docker-envs/projects/evo-myworld
uv venv .venv-test && . .venv-test/bin/activate
uv pip install pytest portalocker requests flask
PYTHONPATH=plugins/evo/src python -m pytest tests/unit/test_missions.py -q
# Full unit suite: 803 pass. The ~13 failures are the broken root-owned
# plugins/evo/.venv + the test_envelope mis-collection, NOT product bugs.
```

Rust runner:

```bash
cargo build --manifest-path plugins/evo/bin/evo-env-runner/Cargo.toml
cargo test  --manifest-path plugins/evo/bin/evo-env-runner/Cargo.toml   # 5 pass
```

Missions / agents (existing lifecycle CLI):

```bash
evo mission create --title 'Research candidates' --kind research \
    --brief 'Read cited Graphify slices.'
evo mission list --status ready
evo agent list --running
evo agent steer --exp-id exp_0001 'Read the cited source range before editing.'
```

### Graphify — test WITHOUT touching the 28 GB DB

```bash
cd /home/npwad/coding/docker-envs/projects/graphify-app
GRAPHIFY_FORCE_MEM=1 node --test test/engine.test.js
# GRAPHIFY_FORCE_MEM=1 forces the in-RAM MiniSearch path; without it,
# searchNodes() routes through data/index.db (~28 GB) and hangs.
```

Retrieve only the cited source a task needs (the intended agent primitive):

```bash
node scripts/gfy.mjs source <repo-id> <source-file> <start-line> <end-line>
# 1-indexed inclusive; returns numbered text, effective range, total lines,
# truncation state, and a SHA-256 content hash. Capped at 500 lines / 5 MiB.
```

### Do-not-touch list (this host, right now)

- `plugins/evo/src/evo/judges.py` and any `.py` source — a concurrent process is
  editing code.
- `data/index.db` (~28 GB) — never open it; use `GRAPHIFY_FORCE_MEM=1`.
- `plugins/evo/.venv` — root-owned and broken; use `.venv-test` instead.
