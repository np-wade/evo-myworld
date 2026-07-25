# Scrapler Eval Harness

A **reproducible benchmark that races the scrapler's candidate tools** (fetchers,
stealth browsers, full engines, extractors, search layers) over a fixed ladder
and produces a trustworthy leaderboard — so spider-den adopts the winners by
score, not opinion. Built into evo (racetrack) from the 15 evo donor repos;
every module cites its donor in its header.

## Run it

```bash
cd racetrack/scrapler-eval
python3 -m scrapler_eval list                    # registered candidates + availability
python3 -m scrapler_eval selftest                # baselines vs the frozen fixtures (no deps, no network)
python3 -m scrapler_eval race --bracket brackets/class4-extractors.json --out result-class4.md
python3 -m unittest discover -s tests            # the whole test suite
```

`race` writes a markdown result: provenance header (git sha, host, python, ts),
overall + per-class leaderboards (normalized coverage, blended score, Elo, gate
pass-rate), and a **"why candidates lost"** failure-cluster table.

## How the numbers work
For each task: score 6 axes (retrieval, completeness, evasion, latency, cost,
robustness — each 0–1) → per-item `quality` blend → gates. Per candidate:
`coverage_total = Σ quality`, `normalized = 100·coverage/n`, a blended
`leaderboard` score (quality/evasion dominate, latency/cost tie-break), and a
head-to-head `elo`. Full spec: `CONTRACT.md`, axis definitions in
`scraper-search-lab/metrics.md`.

## Layout
- `scrapler_eval/interface.py` — shared types (the contract)
- `scrapler_eval/{metrics,gates,leaderboard,store,failure,provenance}.py` — core (pure stdlib)
- `scrapler_eval/harness.py` + `cli.py` — the run loop + CLI
- `scrapler_eval/ladder.py` + `fixtures/` — frozen tier0–2 pages + answer keys + loader
- `scrapler_eval/adapters/` — one Candidate per tool; heavy deps isolated + `available()`-gated
- `brackets/` — per-class race configs (class1 fetchers → class4 extractors)
- `tests/` — 184+ stdlib tests, no network, no heavy deps

## Adding a candidate
Drop `adapters/<tool>.py` exposing `CANDIDATES = [YourCandidate]`. It's
auto-discovered and registered. Gate real deps in `available()` (import inside
a try/except) so a missing dep skips the tool, never crashes the race. Handle
`file://` fixture URLs so it can be exercised on this box offline.

## Live tiers (next)
Frozen tiers 0–2 run today with zero deps. Tiers 3 (anti-bot) and 4 (detector
oracle) are live — add real target URLs to `fixtures/ladder.json` `live_tasks_todo`
and install the tool deps in a venv. Tier R = Nicholas's real targets.

## Run the REAL race (heavy tools)
Frozen-tier fetcher/extractor races run today with zero installs. To race the
browsers/engines for real, install one class's deps into an isolated venv and
race just that class (heavy — one at a time on a RAM-capped box):

```bash
./run-real-race.sh class4   # extractors (light: trafilatura, bs4)
./run-real-race.sh class1   # fetchers   (curl_cffi, scrapling)
./run-real-race.sh class3   # engines    (crawl4ai, scrapegraphai; set HEADLESSX_URL/BROWSERLESS_URL for those)
./run-real-race.sh class2   # browsers   (playwright+chromium/firefox, camoufox — heaviest)
```
For the live anti-bot / detector tiers, add real target URLs to
`fixtures/ladder.json` → `live_tasks_todo` (Tier R = your real targets, with what
"success" means for each), then re-run. The winner of each class feeds the
grand-final assembly into spider-den.
