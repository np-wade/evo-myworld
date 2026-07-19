# evo Field Notes — living doc for all lab AIs

> Started 2026-07-19 by Claude (orchestrator). **Every AI working on evo-myworld
> reads this before touching code, and appends what it learns.** Keep entries
> short, dated, signed. Newest learnings at the bottom of each section.
> Companion protocol: GRAPH-FIRST (`~/coding/docker-envs/projects/graphify-app/GRAPH-FIRST.md`)
> — pull graph library slices for prior art BEFORE building.

## What evo is (base app, upstream `evo-hq/evo`)

- Autoresearch orchestrator: give it a codebase → it discovers metrics,
  instruments a benchmark, then runs an experiment loop (try → score → keep or
  discard) as **tree search** over git branches, not greedy hill-climb.
- Local install lives at `~/coding/docker-envs/projects/evo-hq` (clean clone of
  upstream — do NOT experiment here; this is the reference/test harness).
  Our fork for building: `~/coding/docker-envs/projects/evo-myworld`
  (github `np-wade/evo-myworld`).
- Two-command UX: `/evo:discover` (one-time: finds what to measure, builds
  benchmark + gates) then `/evo:optimize` (runs the loop, unattended,
  parallel subagents in git worktrees).
- Invocation is host-specific: `/evo:` on Claude Code, `$evo` on Codex,
  `/` skill menu on Cursor, natural language on Hermes/Opencode.

## Architecture map (repo layout)

- `plugins/evo/` — THE product. One plugin, multi-host: `.claude-plugin/`,
  `.codex-plugin/`, `.kimi-plugin/` manifests over shared `skills/` (discover,
  optimize, report, ship, subagent, finetuning, infra-setup), `agents/`
  (verifier.md, benchmark-reviewer.md), `hooks/`, `src/evo/` (python core).
- `sdk/python`, `sdk/node` — thin SDKs for instrumenting benchmarks
  (`evo.record(score)` style). 12 py tests pass in 0.03s: cheap gate.
- `scripts/` — dashboard.py, graph.py (experiment tree), scratchpad.py
  (shared state), codex_slurm_harness.py, rlm_eval.
- `tests/` — e2e + live suites, sandbox-agent + sshd fixtures (heavier).
- CLI (`uv tool install evo-hq-cli` → v0.8.0): `evo`, `evo-dashboard`,
  `evo-drain`. `evo install <host>` wires plugin+hooks per host.
  `evo init --target --benchmark --metric --host --per-exp-timeout` is the
  non-interactive path that `/evo:discover` drives for you.

## Key concepts to reuse in the fork

- **Gates**: any command, exit 0 = pass. Failed gate = experiment discarded
  even if score improved. Gates inherit down the experiment tree; narrower
  gates attach to branches. ← this is where our recursive testing +
  "which code deserves to live" culling logic plugs in.
- **Frontier strategies**: argmax / top_k / epsilon_greedy / softmax /
  pareto_per_task — selection policy for which branch to extend.
  ← natural hook for our ML/linear-algebra scoring experiments.
- **Shared state / scratchpad**: failure traces, annotations, discarded
  hypotheses visible to every subagent before it picks a hypothesis.
  ← this is the lab memory bus; graph-db backend should feed it.
- **Cross-cutting scans**: between rounds, RLM-style scan subagents read
  trace batches and surface compound failure patterns into shared state.
- **Backends**: worktree (default, local), pool, ssh, modal/e2b/daytona/
  aws/azure. We start worktree; `pool` may suit our WSL RAM limits better
  (12GB RAM + 24GB swap — see graphify-wsl-limits memory: don't stack
  parallel heavy processes).

## Host/runner status on this box (2026-07-19)

| Runner | Status | Notes |
|---|---|---|
| claude-code | evo plugin INSTALLED ✓ | orchestrator seat |
| cursor | evo plugin INSTALLED ✓ | hooks in ~/.cursor/hooks.json, skills in ~/.agents/skills |
| codex | fixing — snap had stale 0.114.0, npm 0.144.6 symlinked to ~/.local/bin | needs `codex plugin marketplace add evo-hq/evo` then `evo install codex` |
| kimi (K2.7-code / K3) | container `kimi-cli` (docker), OAuth premium acct | evo install must happen IN-container; K3 = creative/front-end seat, keep load small until base is done |
| hermes (ollama-cloud: glm-5.1/5.2, qwen3-coder) | via `~/coding/docker-envs/scripts/launch.sh ask hermes` | evo host `hermes` supported |
| opencode (Featherless: deepseek-V4-Flash 35k ctx cap, step-3.7-Flash) | `launch.sh ask opencode` | evo host `opencode` supported |
| poe (qwen3.7-max-t, minimax m3-t) | `launch.sh ask poe`, poe-code subcommand CLI | NOT an evo host — use for reading/writing/review tasks via ask |
| gemini (3.x via Antigravity `agy`, 2 accounts) | `launch.sh ask antigravity` / `antigravity2` | NOT an evo host — analysis/review seat. Old gemini-cli OAuth dead for individuals |

Keys: `~/coding/docker-envs/.env` (POE_API_KEY, FEATHERLESS_API_KEY, OLLAMA_API_KEY, GEMINI_API_KEY).

## Gotchas learned (append as found)

- 2026-07-19 Claude: `evo init` is fully non-interactive and REQUIRES
  --target --benchmark --metric --host --per-exp-timeout. The chat-driven
  `/evo:discover` is the friendly path that fills those in.
- 2026-07-19 Claude: `evo install codex` on codex <0.144 fails — no `plugin`
  subcommand. Upgrade codex first.
- 2026-07-19 Claude: snap packages shadow npm globals on this box
  (`/snap/bin` before `~/.npm-global/bin` which isn't on PATH at all);
  symlink the npm binary into `~/.local/bin` which wins.
- 2026-07-19 Claude: this WSL box crashed twice before from stacked memory
  spikes. Any evo optimize run here: cap parallel subagents (start 2),
  benchmarks must be small, and long runs need `setsid nohup … & disown`
  or the harness timeout kills the process group.
- 2026-07-19 Feather: agents are roles in the orchestrator loop—verifier (audit), 
  ideator (propose), benchmark-reviewer (diagnose)—while skill/subagent/SKILL.md 
  defines the protocol subagents follow: 4-field brief, iteration loop, evo commands 
  for local/remote worktrees, atomic append discipline for proposals. agents live in 
  `plugins/evo/agents/`; subagent skill is `plugins/evo/skills/subagent/SKILL.md`.
- 2026-07-19 claude-backend: Track B phase 1 shipped — `world/backend/evo_graph.py`
  (`find` = FTS over index.db, `slice` = slice-JSON locator), 12 pytest green.
  Schema keys: **`nodes_fts.rowid == nodes.id`** is the whole FTS→metadata join;
  FTS columns are label/norm_label/source_file/kind/rationale/context/
  community_name/repo_name, tokenizer `unicode61 tokenchars '+#'`.
- 2026-07-19 claude-backend: FTS cap in numbers: repos.fts_nodes sums to 5.94M of
  9.2M nodes (top-50k/repo by degree) — a `find` miss needs a depth-1
  `nodes.norm_label LIKE` follow-up before concluding absence.
- 2026-07-19 claude-backend: FTS quirk — docstrings are indexed as first-class
  nodes (kind=rationale), so prose hits mix into symbol queries; and `kind` is
  populated in the DB but None in slice-JSON nodes, don't rely on it there.
- 2026-07-19 claude-backend: safe FTS5 query building = double-quote every token
  (`"tok"`, escape `"` as `""`) — reused from tencentdb-agent-memory
  sqlite.ts buildFtsQuery (L198); AND-join with OR fallback beats raw MATCH on
  user text, which throws OperationalError on `(`/`*`/`NEAR`.
- 2026-07-19 claude-backend: no pytest on the host python; `uv run --no-project
  --with pytest python -m pytest …` is a zero-install way to run test files.

## The fork plan (evo-myworld) — where we're going

1. Per-AI branches: each runner gets `ai/<name>` (ai/kimi, ai/codex,
   ai/cursor, ai/gemini, ai/hermes, ai/poe, ai/featherless) and pushes
   functionality up; evo-hq (clean base) is the test harness for those
   branches before merge.
2. Assembly line port: the assembly-office autonomous product-processing
   pipeline moves in, gaining evo's experiment/gate structure for recursive
   + experimental testing of code, languages, harnesses.
3. Graph-db backend (second agent): connect graphify (index.db 9.2M nodes /
   FalkorDB) + backend code into the app — feeds evo's shared state and our
   scoring. GRAPH-FIRST applies.
4. ML layer: use linear algebra / NN maths on experiment history for
   predictive branch selection (custom frontier strategy) and code-culling
   decisions (what earns its place, what gets deleted).
5. Later: CLIs and tooling on top.

*(sign entries: Claude / Kimi / Codex / Cursor / Gemini / Hermes / Poe / Feather)*

## Vanilla run log (evo-demo, 2026-07-19)

- 2026-07-19 Claude: full vanilla loop verified on toy repo
  `projects/evo-demo` (naive O(n²) dedup+sort, `bench.py` prints
  "seconds: X", metric min, correctness assert = gate). Flow used THEIR
  interfaces exactly: `claude -p '/evo:discover …'` → it created `.evo/`
  (meta.json, project.md, run_0000, supervisor.pid, dashboard.pid) →
  dashboard live at http://127.0.0.1:8080 ("evo : autoresearch") → it
  advanced to `evo run exp_0000` on its own. Seeding the benchmark/metric
  in the discover prompt skips all interactive questions — good for
  headless dispatch.
- 2026-07-19 Claude: supervisor + dashboard are plain detached python
  procs with pidfiles in `.evo/` — fits our setsid/nohup discipline.
- 2026-07-19 Claude: lane access map — every compose lane sees repos at
  /workspace/<name>; kimi container now mounts them at /projects/<name>
  (kimi-launch.sh updated + container recreated; OAuth survived in
  kimi-home volume). Host `cursor` binary is the Windows IDE launcher,
  NOT cursor-agent — use the docker cursor lane. Featherless/opencode
  lane needs >180s to first token some runs (35k-ctx models are slow
  spinners); dispatcher allows 1500s.
- 2026-07-19 Hermes: SDK + gate internals read for the assembly-line
  port. Full notes at world/hermes/sdk-notes.md. Key contracts every new
  pipeline must obey: (1) score JSON `{"score","tasks"}` to
  $EVO_RESULT_PATH (atomic O_EXCL+rename) or stdout — never both; file
  present means hard-error on empty/malformed (core.py:1063 load_result).
  (2) Per-task emission is enforced — _assert_tasks_aggregated
  (cli.py:1899) raises `tasks_missing_from_result` if 2+ task_*.json
  traces exist but result.json has no `tasks` array. (3) Gate = any
  command, exit 0 = pass; gates inherit DOWN the experiment tree via
  collect_gates_from_path (cli.py:2685). (4) Phase split: pre runs
  BEFORE benchmark (fail = no spend, aborts run), post runs after
  (default for backward compat). (5) keep = compare_scores(...) AND
  gate_passed — a failed gate discards the experiment even if score
  improved (cli.py:3371). (6) gate_env strips all EVO_* vars — gates do
  NOT see EVO_RESULT_PATH/TRACES_DIR; a budget gate must read a
  side-channel the benchmark writes. Two instrumentation paths: paste-in
  inline_instrumentation.py (zero-dep, recommended) or evo_agent.Run/Gate
  (swappable Backend protocol — hook for the graph-db backend).
  Three gate designs drafted for the port: correctness (post, golden
  cases), budget (post, side-channel budget.json), regression (PRE,
  proxy-bench vs parent's committed score → cheap cull before benchmark
  spend). Run order guaranteed: regression → benchmark → correctness+
  budget → keep.

- 2026-07-19 Gemini: Performed top-down architecture review ([arch-review.md](file:///workspace/evo-myworld/world/gemini/arch-review.md)). Identified module boundaries and coupling patterns. Under the 12GB WSL2 RAM constraint, the primary failure risks are stacked local subagent concurrency, massive file checkouts from `git worktree add`, large SQLite index queries, and bulk parsing of trace log batches. Recommend strict limits on local worker concurrency (max 2), memory budget gates, and read-only graph indexing pagination. Only modify files inside `world/gemini/` or backend/strategy protocols.
- 2026-07-19 Gemini: Reviewed CHARTER.md program order, risks, and sequencing advice ([program-review.md](file:///workspace/evo-myworld/world/gemini/program-review.md)). Confirmed Phase 1 (Assembly Port) -> Phase 2 (Graph Backend) -> Phase 3 (ML Layer) sequencing is correct due to data dependencies. Highlighted major risks: WSL2 resource limits under concurrent agents, FalkorDB/SQLite memory footprints, and heavy ML library imports (PyTorch/TF). Proposed static prior-art injection to keep subagent queries decoupled, a zero-heavy-dependency ML layer using numpy/scipy, and sequential gate execution (regression first to fail fast). Signed, gemini2.
- 2026-07-19 Cursor: Mapped dashboard/graph/scratchpad. The three `scripts/*.py`
  files are one-liners; real code is `plugins/evo/src/evo/dashboard.py`,
  `scratchpad.py`, and `core.py`. Experiment tree = `.evo/<active-run>/graph.json`
  (parent/children dict, locked atomic writes). UI is Flask + `static/app.js`
  tidy-tree timeline polling `/api/graph` + `/api/frontier`. CLI `evo tree` /
  `evo scratchpad` share the same graph + render helpers. Full route/file map:
  `world/cursor/dashboard-map.md`. Signed, cursor.
- 2026-07-19 Claude: optimize round 1 on evo-demo — full loop verified:
  2 experiments raced in parallel worktrees, correctness gate + verifier
  pre/post (post reproduces scores independently) + benchmark-reviewer
  per-rep checks all ran. Winner exp_0001 (sorted(set), 760x) over
  exp_0002 (dict.fromkeys, 290x). Lesson for our benchmarks: score
  granularity matters — a 0.1ms-rounded score can't rank micro-variants
  once the big win lands; size CALLS_PER_REP so best-case runtime >> the
  rounding unit. evo records such issues as "workspace notes" in the run.


- 2026-07-19 Kimi: Read `CHARTER.md`, `FIELD-NOTES.md`, and `/projects/evo-hq/README.md`. Front-end seat should build inside `world/kimi/` and keep load tiny until assembly-line port + graph backend land. Existing dashboard is Flask + `static/app.js` with `.evo/<active-run>/graph.json`; the upstream README enumerates frontier strategies and backends. Drafted 5 creative UI directions (campfire room, time-river tree, agent orbit, graph-first lens, lab-bench panel) in `world/kimi/ideas.md`. No code yet. Signed, kimi.
- 2026-07-19 Codex: Mapped plugin and `evo direct` internals in
  `world/codex/internals-map.md`. Directives are durable append-only JSONL;
  per-session marker files only wake drains, offsets make delivery once per
  session, `delivered/` is the emit receipt, and `evo ack` is the model receipt.
  Claude Code and Codex share hook envelopes but differ at PreToolUse (Claude
  needs `permissionDecision: allow`) and installation (Codex needs enabled,
trusted plugin hooks plus absolute helper paths). Cursor uses native hooks,
   delivers mid-turn only by rewriting shell input, and otherwise defers to a
   turn-end `followup_message`. Signed, codex.

## Learning log — Feather (short-context reading/writing)

- 2026-07-19 Feather: evo agents are orchestrator roles (verifier = read-only audit, ideator = proposal generator, benchmark-reviewer = per-task failure analysis); subagent/SKILL.md defines the 4-field brief + iteration loop all subagents follow (objective, parent, boundaries, traces). Key commands: `evo new --parent`, `evo run`, `evo scratchpad`, `evo status`, `evo show/diff/traces/annotations`, `evo discard/annotate`, `evo gate list/check/add`. Remote worktrees require explicit `--exp-id` on workspace-op commands. Pipeline phases: verifier pre-check (static), run benchmark+gates, verifier post (advisory), benchmark-reviewer post-commit (diagnostic annotations). Signed, feather.
- 2026-07-19 Claude: dispatcher v2 — call shapes matter. Small-context
  seats (feather 35k, poe) now get LIGHT calls (their one queue item +
  FIELD-NOTES tail only); everyone else reads only the last 150 lines of
  this file (it grows every cycle — full reads would eventually choke
  every seat). A call only counts if the seat ticks its queue item; 2
  verified no-ops → item auto-escalates to queues/escalations.md instead
  of being retried forever. Poe gets a model fallback chain; gemini lane
  print-timeout raised 3m→20m via AGY_PRINT_TIMEOUT (3m truncated long
  tasks silently — check launch.sh defaults when a lane "succeeds" but
  work is missing).

- 2026-07-19 Hermes: Track A deliverable A1 DONE — gate library at
  `world/hermes/gates/` (correctness.py, budget.py, regression.py,
  held_out.py) + test_gates.py (15/15 green, stdlib, ~1s) + README.md
  + PRIOR-ART.md. Each gate is one executable script, exit 0 pass / 1
  fail / 2 misconfig, none read EVO_* env (cli.py:3232 strips them
  anyway). RACE RULE satisfied by filing 4 race requests at
  `racetrack/requests/gate-{correctness,budget,regression,held_out}.md`
  — the lab loop runs them via run-race.sh; results land in
  racetrack/results/. Prior art per gate (≥2 candidates each, read
  end-to-end from /library/repos/): auto_harness_demo/gate.py +
  nocodb helpers.bash (correctness); OmniRoute budgetGate.ts +
  raven before_iteration_hook.py (budget); adk-rust baseline.rs +
  repowise kg_checks.py (regression); Lightning-AI overfit_batches +
  ruvector weight_learning.rs (held_out). Budget YAML parser bug
  found + fixed: original treated `stages:` wrapper as a no-op and
  misparsed `intake:` as a key with empty value → "no ceilings"
  warning → false PASS. Fix supports both flat (top-level stage:) and
  wrapped (stages:/  intake:) shapes via stage-indent tracking.
  Run order guaranteed by evo pre/post split: regression(pre) →
  benchmark → correctness+budget+held_out(post) → keep. Signed, hermes.
- 2026-07-19 Gemini: Explored corpus repos (neuronbox, HyperMem, MSA) and filed a race request for vector-cosine-similarity benchmarking NumPy manual dot/norm computation against PyTorch pre-normalized matmul. Neuronbox implements hardware GPU status and soft VRAM checks via a Rust NVML wrapper. HyperMem builds a three-level conversation memory hypergraph with BM25 and vector retrieval fused with RRF, while MSA routes query KV caches using chunk-pooled document latent states and distributed GPU matrix multiplication for 100M-token contexts. Written findings to world/gemini/exploration-notes.md. Signed, gemini.
- 2026-07-19 gemini2: Completed BRANCH BUILD (item 5). Designed and implemented the UCB1 (Upper Confidence Bound) frontier selection strategy to balance exploit (node score) and explore (fewer children/branches). The module logic is defined in `world/gemini/ucb.py` and connected directly to `plugins/evo/src/evo/frontier_strategies.py` under the `"ucb1"` strategy identifier. Verified correctness with a local math/min-max unit test suite in `world/gemini/test_ucb.py` and integrated it into the proving ground via `world/gemini/judge.env` for verification and scoring. Signed, gemini2.
- 2026-07-19 Cursor: How a second data source (graph backend) can feed the
  dashboard — do NOT merge into graph.json. Add read-only `/api/library/find`
  + `/api/library/slice` proxies over `world/backend/evo_graph.py` (sqlite FTS
  ro, capped limit). UI: one-shot prior-art strip on node-drawer open from
  hypothesis tokens (not in fetchAll poll). Optional scratchpad "Library
  hints" appendix (≤5 lines) when GRAPHIFY_DATA set. Keep experiment tree
  lock path untouched; FalkorDB later. Full note:
  `world/cursor/graph-dashboard-feed.md`. Signed, cursor.

- 2026-07-19 Codex: The 3 cheapest custom-frontier extension points are:
  (1) add one declarative `FRONTIER_STRATEGIES` entry, one contract-compatible
  picker, and one `PICKERS` mapping in `frontier_strategies.py`; (2) reuse the
  existing `{kind, params}` `.evo/config.json` / CLI override / dashboard
  configuration seam, whose UI is registry-driven; (3) stay behind the shared
  `pick()` boundary, which already feeds CLI, dashboard, and scratchpad. A
  score-only strategy needs no consumer edits; task-aware strategies can use
  the existing outcomes mapping. Full citations and cost notes:
  `world/codex/frontier-extension-points.md`. Signed, codex.

- 2026-07-19 Kimi: BRANCH BUILD done. `world/kimi/evo_river.py` is a working
  dashboard surface / CLI that reads evo's `graph.json` and renders the
  experiment tree as a horizontal time-river (root upstream, generations
  downstream, `*` frontier, `▲` best spine, ANSI status colors). Wired into
  the Flask dashboard as `/api/river` in `plugins/evo/src/evo/dashboard.py`
  alongside `/api/tree`. Includes `world/kimi/test_evo_river.py` (7/7 green),
  `fixtures/demo-graph.json`, `README.md`, and `experiment.env` for the bench.
  Bench verified: `evo tree` ASCII output differs from river output; both run
  in <0.01s on the fixture. Keeps front-end load tiny (pure stdlib, no new
  deps). Signed, kimi.

- 2026-07-19 assembly-port: Track A core port DONE — `world/assembly/assembly.py`
  (stdlib CLI: plan/brief/to-evo) rebuilds the assembly line on evo primitives.
  Boss idea -> plan.json modeled on plannerCliContract (assembly-office
  lib/architecture.mjs:119-143) + assignment-node fields (station-roles.mjs:
  393-453, narrow owned_paths enforced); stages -> 4-field subagent briefs
  (subagent/SKILL.md:57-64); oversight/test profiles -> hermes gates
  (regression pre, correctness post everywhere; budget+held_out on the race
  stage) + allowlisted profile port of test-runner.mjs:8-49.
- 2026-07-19 assembly-port: the new capability is explicit — the `variants`
  stage brief mandates >=2 sibling implementations raced under identical
  gates; `to-evo` emits a headless `/evo:discover` seed + 9 `evo gate add`
  lines for the worked example (a CLI stopwatch, real outputs committed
  under world/assembly/example/, seed line shlex-verified).
- 2026-07-19 assembly-port: tests 17/17 in 0.20s (`uv run --no-project --with
  pytest pytest -q world/assembly/test_assembly.py`); bench experiment.env
  left for the loop (raw idea 1 line vs planned 161 lines, deterministic —
  no timestamps in plan.json, unlike station-roles.mjs:354).
- 2026-07-19 assembly-port: RACE-RULE — took the deterministic draft path
  (draftPlanFromMission, station-roles.mjs:307) over LLM autopilot
  normalization (autopilot.mjs:54); why + why no racetrack filing (candidates
  not offline-benchmarkable under one metric) recorded in
  world/assembly/NOTES.md. Signed, assembly-port.

- 2026-07-19 Codex: Live-served the real evo dashboard against the mounted
  evo-demo `run_0000` and curled all 28 URL rules. `graph.json` supplies the
  topology/scores/statuses, but `/api/graph` enriches nodes from attempt/check
  artifacts and backend/lineage resolution; Pareto frontier ranking also reads
  per-attempt outcomes, reducing two raw leaves to the sole pick exp_0001.
  Full actual response samples: `world/codex/app-live-notes.md`. Signed, codex.
- 2026-07-19 Codex: Live input probes found inconsistent dashboard validation:
  adjacent settings endpoints return JSON 400s, but
  `POST /api/workspace/runtime-variables` with `{"variables":42}` raises an
  HTML 500. Also, the stock dashboard script cannot serve a state-only mounted
  snapshot because implicit `repo_root()` requires `.git`; explicit
  `create_app(root)` serves it correctly. Signed, codex.
- 2026-07-19 Claude: racetrack bug found+fixed live — run-race.sh cd'd into
  the race dir BEFORE reading the (relative) request path, so the steward
  got an EMPTY brief. Fix: realpath the request first. Lesson for all lab
  scripts: absolutize every path argument before any cd. (Also re-learned:
  never pkill -f a string your own command line contains.)

## BR-Witt scaffold

- Created two standalone git repos: `/projects/bertrand-hussle` and
  `/projects/witt-brain`, each with `git init` and first commit. BH is the Rust
  CLI; Witt Brain is the model-holding library + server. The seam is an
  identical `INTERFACE.md` contract in both repos: crate API plus JSON-RPC over
  a Unix socket. Signed, kimi.

- BH visual system is code, not config: `src/theme.rs` defines a 3-line header,
  a `✦` sigil, a 10-frame braille spinner, and `NO_COLOR` respect. The palette
  is taken from Raven's dark theme (`#fbe23f` gold, `#536878` slate) but the
  header is intentionally tiny to stay token-cheap at runtime. Signed, kimi.

- Witt-brain keeps the Rust base dependency-only (clap, anyhow, serde, tokio,
  etc.) and does not depend on the missing local `/library/repos/zeroclaw-labs_zeroclaw`
  tree. Instead it mirrors the ZeroClaw trait names (`ModelProvider`, `Memory`)
  as placeholder traits and cites the real upstream files in `DESIGN.md`. This
  lets the repo stand alone while staying aligned with `/projects/witt`'s
  existing ZeroClaw path deps. Signed, kimi.

- 2026-07-19 selfdev: read the EverMind raven evolver end-to-end and built
  selfdev/ (SELFDEV.md design + cycle-review.sh, tested live). The raven
  mechanisms worth stealing, all in
  filing-cabinet/library-base/repos/EverMind-AI_raven/code/:
  (1) the self-improvement loop is a deterministic state machine, NOT prompt
  discipline — control flow/termination in code, the model answers one small
  schema-validated question per step (raven/evolver/orchestrator/loop.py,
  nodes/semantic.py, orchestrator/DESIGN.md "inversion of control");
  (2) adoption is gated three ways: infra failures never scored 0-and-dropped
  (denominator = all tasks), credit only where the patch's mechanism actually
  FIRED (activation_beacon), and paired significance vs a FIXED vanilla
  baseline (orchestrator/gates/pipeline.py, gates/paired.py,
  applier/beacon_guard.py; SOP docs/specs/self-evolution-loop-sop.md §0,§2⑥);
  (3) the designer edits only a path whitelist and everything else it touches
  is REVERTED — the measurement surface (evolver + scorer) is an immutable
  kernel a candidate can never edit (applier/path_guard.py, evolver/README.md
  security notes) — cycle-review.sh copies this exactly;
  (4) inert candidates are culled at zero cost before any spend
  (zero-hit preflight, orchestrator/production.py) → our no-op-on-unchanged-
  evidence fingerprint; test set is physically sealed from decisions
  (sealed/runner.py score() returns None) → our "adoption is judged by NEXT
  cycle's evidence, never self-declared";
  (5) everything is an append-only ledger (nodes/*.json, findings.md,
  state/journal.py; config fingerprint refuses resume under changed config)
  → selfdev/CHANGELOG.md. First live cycle-review run applied one refinement
  (queues/gemini.md item 6: judge.env PYTHONPATH fix routed to gemini).
  ⚠ collateral: the path guard reverted racetrack/run-race.sh, which our
  driver never touched — a CONCURRENT session's edit landed in our window
  (transcript-verified). Whoever owns that edit: re-apply it; future reverts
  are saved to selfdev/.state/reverted-<stamp>.patch, and the orchestrator
  should wire cycle-review.sh into the loop's sequential slot (after races,
  before commit). Signed, selfdev.

- 2026-07-19 Gemini: Verified EverMind Raven's `BeforeIterationHook` and `ToolAuditHook` live in python against toy inputs. Gating conversation turns via fast character-length token estimation (`len(json.dumps(messages)) // 4`) and blocking specific tools via a deterministic denylist successfully halts executions before LLM calls occur, providing a highly lightweight first line of defense against runaway loops and resource waste. Signed, gemini.
- 2026-07-19 Gemini: Ran Raven's evolver analysis modules (`compute_stability`, `extract_features`, `build_trial_pool`) against mock baseline directories. Confirmed how the evolver stratifies tasks into stability tiers and extracts cheap metadata features (e.g. average text length, docker error counts, exit status ordinals) to build a unified trial pool. This allows a cold-start coverage bandit to run K-means clustering and select a diverse diagnostic subset of tasks, saving significant benchmark run cost. Signed, gemini.
