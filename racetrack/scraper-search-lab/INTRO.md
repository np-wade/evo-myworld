# 🕷️🔎 Scraper + Search Lab — testing intro

Purpose: figure out **empirically** which scraping/browser stack and which
search layer are the best pieces to build into **spider-den**
(`projects/spider-den`), by racing them against each other in the evo
racetrack harness.

This folder is the **intro / staging area** — it lists every candidate and the
metrics that matter. It is **NOT** an auto-run race yet: the lab-loop only
picks up `racetrack/requests/*.md`, so nothing here fires until we promote a
bracket into a race request. Metrics are deliberately loose for now (per
Nicholas: "not that deep rn") — we lock exact weights when we cut the requests.

## The pipeline we're actually assembling

```
   SEARCH            SCRAPE / FETCH              INDEX / RETRIEVE
  (find URLs)   →   (get the page content)   →  (store + query it)
  searxng…          scrapling / cloakbrowser…    meilisearch / qdrant…
```

Three roles, three candidate pools. A "best overall" answer is the best piece
in **each** role, then the three winners assembled into one pipeline and run
against spider-den's current default as the grand final.

## Candidate pools (full lists in the sibling files)

- **[candidates-scraping.md](candidates-scraping.md)** — 15 fetch/browser/engine
  options, grouped into weight classes (no-JS fetchers, stealth browsers, full
  engines, extractors). These are the "better than Playwright" contenders.
- **[candidates-search.md](candidates-search.md)** — the search layer to pair
  with scraping: web/meta-search (discover URLs), full-text engines, and
  vector/semantic retrieval (index what you scraped).

Every candidate cites a **real repo in the corpus** at
`~/coding/docker-envs/filing-cabinet/library-base/repos/<folder>` so the race
steward can read its actual source and build a faithful arena.

## Metrics that matter

Full definitions + the scoring model in **[metrics.md](metrics.md)**. The short
version — every candidate runs a fixed **site/query ladder**; each item gets a
0–1 quality score; those sum to a per-candidate **total**, then a small set of
axes blend into one leaderboard number:

**Scraping candidates**
- **Retrieval success** — did we get the *real* content, not a block/challenge/empty page (the "how many pages you look and actually see it" count)
- **Content completeness** — fraction of expected content captured (matters for JS-rendered / lazy-loaded / infinite-scroll)
- **Evasion** — bot-detector pass score (bot.sannysoft / CreepJS / nowsecure)
- **Latency** — wall-clock per page
- **Cost / footprint** — proxy bytes + LLM tokens + RAM/CPU (WSL box is memory-limited)
- **Robustness** — success variance across retries (flakiness)

**Search candidates**
- **Relevance** — precision@k of returned URLs/results vs an answer key
- **Coverage / recall** — did it find the pages that exist
- **Freshness** — recency of results
- **Self-host / zero-key** — no paid API dependency (big plus for the lab)
- **Latency + cost** — and, for index/vector: recall@k, build time, query latency, **storage footprint**

## Battlegrounds (site/query ladder)

Nicholas: "both" — so a **standard difficulty ladder** for fairness *plus* the
**real spider-den targets** for relevance. Fetch mode is **hybrid**: frozen
HTML/HAR fixtures for the deterministic core score, plus a small **live**
anti-bot check (real Cloudflare) that can't be faked offline.

- **Tier 0 — static HTML** (baseline; every tool should win)
- **Tier 1 — JS-rendered SPA** (needs a real browser)
- **Tier 2 — lazy-load / infinite scroll** (needs scroll + wait logic)
- **Tier 3 — anti-bot / Cloudflare** (the stealth main event; live)
- **Tier 4 — public bot detectors** (bot.sannysoft, CreepJS, nowsecure — score the fingerprint directly)
- **Tier R — Nicholas's real targets** *(TODO: drop the actual URLs spider-den must scrape here)*

## How this becomes a race

When we're ready, each **weight class** becomes one file in
`racetrack/requests/` (e.g. `scrape-stealth-browsers.md`) naming its candidates
+ metric + gate. `run-race.sh` hands it to the steward, which implements each
candidate as its own evo experiment branch and writes a scored
`candidate | source | score | gate` table to `racetrack/results/`. See
`../RACETRACK.md` and `../run-race.sh`.

## Status / TODO

- [x] Candidate pools assembled (scraping + search), all cited to corpus repos
- [x] Metrics that matter drafted
- [ ] Nicholas to add real target URLs (Tier R)
- [ ] Freeze fixtures for tiers 0–2 (deterministic core)
- [ ] Lock metric weights + gates, then cut race-request files
- [ ] Separate track: build `changedetection.io` into the corpus for a
      page-change-monitor race (not in the library yet)
