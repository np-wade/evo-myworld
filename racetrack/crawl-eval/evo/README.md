# T5 evo benchmark — optimize the fetch-escalation policy

Wires T5 (Internal Crawl + Search) into `/evo:optimize`. The optimizable unit is
a **fetch-escalation routing policy**: given cheap probe signals about a target,
pick the CHEAPEST fetch tier that reaches the content. Grounded in the real T5
servers/tools, so the score reflects actual scraping behavior.

## Contract (same as `tests/fixtures/*/benchmark.py`)
- **Target file** evo edits: `agent/policy.py` (`solve(signals) -> tier`)
- **Benchmark:** `python benchmark.py --agent agent/policy.py`
  → prints `{"score", "tasks"}`, writes traces to `$EVO_TRACES_DIR/task_<id>.json`
- **Gate:** `python gate.py --agent agent/policy.py` (exit 0 pass / 1 regressed)

## Run it (MUST use the crawl-eval venv — needs curl_cffi + playwright)
```
cd racetrack/crawl-eval
.venv/bin/python evo/gate.py      --agent evo/agent/policy.py   # exit 0
.venv/bin/python evo/benchmark.py --agent evo/agent/policy.py   # {"score":...}
```

## Scenarios (real servers stood up per task)
| task | server | minimal tier | why |
|---|---|---|---|
| plain | SiteServer `/about` | **static** | normal page — cheapest wins |
| ja3_wall | HardenedServer `/` | **impersonate** | JA3/TLS wall — needs a browser fingerprint |
| js_nav | SiteServer `/store` | **browser** | links built by `fetch()` — needs JS |
| js_challenge | HardenedServer + JS | **browser** | TLS wall + JS challenge |

Reward per task: reach with the minimal tier → 1.0; reach but over-provisioned →
0.7; miss → 0.0.

## The optimization gradient
`agent/policy.py` ships a **naive baseline** (always `static`): nails `plain`,
fails all three walls → **score ≈ 0.25**. The target evo should discover is the
empirically-proven escalation ladder (see `../results/crawl-suite.md`):
```
if signals["static"]["reached"]:      return "static"
if signals["impersonate"]["reached"]: return "impersonate"
return "browser"
```
which scores **1.0**. That ladder is exactly what the JA3 / HTTP-2 / challenge
races proved: static for endurance, impersonate for a fingerprint wall, a full
browser for a JS/behavioral challenge — keeping TLS+h2 fingerprints consistent.

## Registering with evo
Point `/evo:optimize` at this benchmark (target `agent/policy.py`, benchmark
`benchmark.py`, gate `gate.py`), using `racetrack/crawl-eval/.venv/bin/python` as
the interpreter. The hard score is deterministic and offline; reuse
`scrapler-eval` metrics/store for leaderboard/provenance if desired.
