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
