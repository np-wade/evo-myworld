# EVO UPDATE HANDOFF — crawl-eval T5 (2026-07-28)

Continuation of the T5 crawl-eval work after an offline interruption. Branch
`ai/claude-dashboard-design` in `~/coding/docker-envs/projects/evo-myworld`
(remote github np-wade/evo-myworld). All work below is **committed + pushed**.

## What changed this session

### ✅ T5 frontier completed (#2/#3/#4) — commit `707f91a`
- **#3 Behavioral / JS-fingerprint wall (Tier-R++)** — `crawl_eval/behavioral.py`
  stacks a JS-fingerprint probe (webdriver/chrome/plugins/languages/WebGL/canvas →
  6-bit mask) on the JA3 wall. Server-authoritative SOLVED (mask==FULL) vs DETECTED.
- **#2 Dedicated stealth-browser tier** (`crawl_eval/crawl.py` extension point):
  - `playwright-stealth` 🏆 **SOLVES** the combined JA3+JS-fp wall (reference).
  - `camoufox` installed & raced — **honest two-layer finding**: passes ALL SIX JS
    tells (verified GREASE-relaxed, genuine engine-level mask) but is **⛔ BLOCKED at
    JA3** on the combined wall — it spoofs the browser fp, NOT a browser TLS JA3.
    Docstring corrected (was overclaiming); race prints an honest footnote; **not
    faked past JA3**. Lesson for spider-den: JA3 and behavioral spoofing are
    INDEPENDENT capabilities a production escalation policy must satisfy together.
  - invisible_playwright / puppeteer-stealth / cloakbrowser / browserless remain
    `available()`-skip-gated with documented reasons.
  - Latest result artifact: `results-behavioral-run2.json`.
- **#4 Search deepening** — `lance` added as 2nd vector engine (ties qdrant 1.0);
  query set widened 9→16; the 0.889 pipeline miss root-caused (crawl4ai body echoes
  `<h1>`+nav → triple-counted title) and fixed via `_embed_text()` normalization.
  **Pipeline search_recall now 1.0 (16/16), all 4 gates pass.**
- Docs reconciled: `../results/crawl-suite.md` behavioral section + `HANDOFF.md`.

### ✅ evo workspace initialized (#1 scaffolding) — commit `faf9012`
- `evo init` → workspace **`run_0000`** at repo-root `.evo/`.
  - backend: **worktree**; instrumentation: **inline**; metric: **max**;
    `commit-strategy=tracked-only` (experiment commits never touch the untracked
    lab tree); `per-exp-timeout=900`.
  - target `evo/agent/policy.py` · benchmark `evo/benchmark.py` · gate `evo/gate.py`.
  - Gradient (smoke-verified): baseline **0.25 → optimal 1.0**.
- `.gitignore` extended for evo secret/transient state: `.evo/keyfile` (a real
  secret — never commit), `*.log`, `*.pid`, `run_*/infra_log.json`, `run_*/inject/`.
  Only durable config (`meta.json`, `run_*/config.json`, `project.md`, `graph.json`,
  `annotations.json`) is committed.
- Dashboard was auto-started then **stopped** (port 8080 closed).

## ⏸ #1 `/evo:optimize` — HELD, ready to launch
The loop was intentionally NOT run. To launch it:
1. Smoke first: `cd racetrack/crawl-eval && .venv/bin/python evo/gate.py --agent
   evo/agent/policy.py` (exit 0) and `.venv/bin/python evo/benchmark.py --agent
   evo/agent/policy.py` (→ `{"score":0.25,...}`).
2. **Interpreter gotcha (worktree mode):** experiment worktrees are fresh checkouts
   WITHOUT the gitignored `.venv`. Point evo's benchmark interpreter at the
   **absolute** `.venv/bin/python` (deps live there; edited `crawl_eval` source comes
   from the worktree via cwd). Otherwise the benchmark can't import curl_cffi/playwright.
3. Run serially on this 12GB box (`subagents=1`) — the benchmark launches real
   browsers; keep the box to itself.

## Repo hygiene / scaling notes
- Git-tracked repo is **~17 MB** (source + small result JSON/MD). The "12 GB feel"
  was ~7 GB of local venvs, which are gitignored + uv-cache-shared (`~/.cache/uv`).
- A **backup snapshot** of the racetrack labs' durable content exists at private
  repo `np-wade/evo-myworld-archives`, release `racetrack-builds-2026-07-28` (source
  + fixtures + `_archive_recipe/*.freeze.txt`). The labs themselves are **local and
  intact** — do NOT delete sibling labs (ip/arxiv/substack/video/watchdog) for disk;
  they are separate workstreams' projects.
- Uncommitted, still untracked (optional follow-up): `../results/*.md` sibling-lab
  result docs (the "knowledge layer") — commit to preserve findings in the lean repo.

## Frontier / next
- Run `/evo:optimize` (search the escalation policy 0.25→1.0).
- Open the PR for `ai/claude-dashboard-design` (branch is pushed; no PR yet).
- Wire the winning policy back into spider-den as production escalation logic
  (must satisfy JA3 **and** behavioral layers — camoufox proves they're independent).

Prior handoff: `HANDOFF.md` (T5 build). Result card: `../results/crawl-suite.md`.
