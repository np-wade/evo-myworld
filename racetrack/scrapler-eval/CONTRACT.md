# Scrapler Eval Harness — build contract

Goal: a **reproducible** benchmark that races the scrapler's candidate tools
(curl-impersonate, Scrapling, cloakbrowser, camofox, crawl4ai, HeadlessX,
browserless, Scrapegraph-ai, playwright baseline, extractors, search layers)
over a fixed ladder and produces a trustworthy leaderboard — so spider-den
adopts the winners by score, not opinion.

Everything builds against `scrapler_eval/interface.py` (the ONLY source of
truth for shared types). Do not change interface.py without updating this file.

## Package layout (each module = one build task, one donor lineage)

| Module | Builds | Donor(s) in corpus | Notes |
|---|---|---|---|
| `interface.py` | shared types (DONE) | EvoAgentBench task shape | pure stdlib |
| `metrics.py` | per-axis 0–1 scorers + IR metrics + `item_quality` | roboflow_supervision (metric primitives), EverMemBench (per-task scoring) | pure stdlib; precision/recall/nDCG/MRR ported |
| `gates.py` | executable pass/fail rails, `Gate.check(RunRecord)` | NVIDIA-NeMo_Guardrails (rails/flows) | each race declares gates; steward scratches failures |
| `leaderboard.py` | `rank()` coverage→normalized→blended + `arena_elo()` head-to-head | lm-sys_FastChat (arena elo), EverMemBench (leaderboard) | per-class + grand-final bracket |
| `store.py` | run store (JSONL), result cache by (candidate,task,cfg) hash, score history | comet-ml_opik (experiment tracking), facebookresearch_exca (caching), kairosdb→JSONL (score history) | cache short-circuit MUST be detectable (no fake reuse) |
| `failure.py` | per-task failure trace + clustering | latitude-dev_latitude-llm (event→incident grouping) | so you see WHY a candidate lost each item |
| `provenance.py` | run stamping + heartbeat | rustyhorde_vergen (build/run stamp), hertzbeat→simple heartbeat | reproducibility + 1-line/min status |
| `harness.py` | the run loop + callbacks (fetch→score→gate→record) | Lightning-AI_pytorch-lightning (loop/callbacks pattern), deepset-ai_haystack (composable stages) | 2-parallel max (WSL RAM), niced |
| `cli.py` | `python -m scrapler_eval race <bracket.yaml>` → leaderboard.md | storm (methodology/bracket) | ties everything together |
| `adapters/*.py` | one Candidate per tool | the 15 scrapler donors | heavy deps isolated; `available()` gate |
| `fixtures/` | frozen tier0–2 pages + answer keys + `ladder.yaml` | — | deterministic, re-runnable, checked in |

## Hard rules (evo anti-cheat, inherited)
1. Frozen tiers (0–2) must be deterministic and checked in with an answer key.
2. No candidate may see the answer key at fetch time (leakage = invalid race).
3. Cache reuse must be logged as reuse, never presented as a fresh run.
4. A candidate whose deps are missing is **skipped and recorded**, never crashes the race.
5. Every module ships pytest tests that run WITHOUT network and WITHOUT the heavy scraper deps (use the built-in synthetic fixtures).
6. Metrics/leaderboard/gates/store/failure/provenance = pure stdlib (no torch, no faiss). Only adapters may need extras.

## The item→leaderboard flow (what the numbers mean)
```
per task:   axes = metrics.score(fetch/extract result, task)      # 6 scraping axes, each 0..1
            q    = metrics.item_quality(axes, weight_class)        # 0..1 blend
            pass = all(gate.check(record) for gate in gates)
per cand:   coverage_total = sum(q)                               # "pages actually seen"
            normalized     = 100 * coverage_total / n_tasks
            leaderboard    = w1*quality + w2*evasion - w3*latency - w4*cost + w5*robustness
            elo            = arena_elo(head-to-head per shared task)
output:     per-class tables + grand-final bracket + WHY (failure clusters)
```
Weights live in the bracket yaml (per-class overridable), defaulting to
quality/evasion-dominant, latency/cost as tie-breakers.
