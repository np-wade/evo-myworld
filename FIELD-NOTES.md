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
