# HANDOFF — crawl-eval (T5, Internal Crawl + Search)

**Built 2026-07-27.** Green, end-to-end. This is the benchmark that finally raced
the "unraced field" from `../scraper-search-lab/HANDOFF-integration-and-T5.md`:
full crawlers, browser/stealth engines, and the search-index bracket.

## Cleanup status (containers/ports/disk)
- **No containers or ports left running.** The site server binds an ephemeral
  localhost port only during a race (torn down in `finally`). The `meili-crawleval`
  docker container (:7700) was stood up for the index race then **removed**
  (`docker rm -f meili-crawleval`). Restart: `docker run -d --name meili-crawleval
  -p 7700:7700 getmeili/meilisearch:v1.10`.
- qdrant runs **local-mode** (`QdrantClient(":memory:")` + fastembed) — no
  container; fastembed downloaded a ~90 MB model to `~/.cache` on first use.
- Disk that lives on: `.venv/` (~890 MB — playwright chromium, selenium,
  crawl4ai, qdrant/fastembed, tantivy…), `node_modules/jsdom` (~27 MB), fixtures,
  `out/site1/`. Chromium system libs installed once via `sudo playwright
  install-deps chromium`. (Reclaimed 2.1 GB earlier by removing the stale
  `video-eval/.venv` — see its `.venv-REMOVED.txt` for the rebuild command.)

## Run it
```
cd racetrack/crawl-eval
.venv/bin/python -m crawl_eval selftest          # offline: scoring + JS-trap proof
.venv/bin/python -m crawl_eval list              # which candidates are runnable
.venv/bin/python -m crawl_eval crawl-race        # browser vs fetcher (JS wall)
.venv/bin/python -m crawl_eval endurance-race --seconds 10   # "how many turns"
.venv/bin/python -m crawl_eval stealth-race                  # JA3/TLS wall
.venv/bin/python -m crawl_eval http2-race                    # HTTP/2 fingerprints
.venv/bin/python -m crawl_eval challenge-race                # Tier-R+ TLS+JS
.venv/bin/python -m crawl_eval extract-race
.venv/bin/python -m crawl_eval index-race
.venv/bin/python -m crawl_eval pipeline          # E2E seed task + scorecard
```
`build` re-renders fixtures from `crawl_eval/site_spec.py` (idempotent). Host
python (3.14, no pip) runs the stdlib-only subset; the `.venv` (3.12) runs the
full field.

## The oracle trick
The site is **authored** — `crawl_eval/site_spec.py` is the single source of truth
(pages, links, the JS-only items, the query answers). `build_fixtures.py` renders
it to `fixtures/site1/` (raw HTML + gold); `site_server.py` serves it and keeps an
independent hit-log so robots violations + request counts are measured, not
self-reported. Because we own the site, gold is perfect and fully offline.

## Planted traps (each isolates one measured capability)
- **JS-nav wall** — `/catalog` links to `/item/1..5` only via `catalog.js`
  (injected DOM). Raw-HTML parsers see 0; JS engines see 5. → the browser-vs-
  fetcher contrast (js_recall).
- **robots wall** — `/private/secret` is Disallow:'d but linked from home.
  Fetching it = hard fail (measured server-side).
- **depth chain** — `/depth/deep` at depth 4. **pagination** — `/blog` × 3 pages.
  **duplicate** — `/products?ref=home` → canonical `/products` (dedup test).
- **endless maze** — `/maze/<id>` synthesized on the fly (fanout 3 + deep next +
  root), for the endurance race. Effectively infinite; tune via `--seconds`.

## Headline results (see ../results/crawl-suite.md for the tables)
Tests were HARDENED once every candidate started winning — both races now
separate the field into tiers instead of tying:
- **Crawl (3 tiers):** full browsers (crawl4ai/selenium/playwright) js_recall
  **1.0**; **jsdom 0.667** (DOM-only — no `fetch()`, misses the fetch-injected
  /store pages); static fetchers **0.0** (backend irrelevant to a JS wall).
  crawl4ai fastest full engine (7.4 s). greedy trips robots + dup.
- **Index (3 query tiers):** **qdrant 1.0** (only engine that does semantic +
  typo) > **meilisearch 0.667** (typo-tolerant, semantic 0) > **bm25 = tantivy
  0.444** (exact keyword only). Vector earns its ~5,000× build cost on the hard
  tiers; bm25 wins when queries are exact keywords.
- **Endurance:** urllib ~477 pg/s (~4.8k turns/10s) >> curl_cffi 413 > scrapling
  357 >> browsers ~1.5 pg/s. All stable (stopped on timeout, not error).
- **Stealth (Tier-R JA3 wall):** curl_cffi-chrome/safari + scrapling RESOLVE
  (browser JA3 w/ GREASE); urllib + curl_cffi-*without*-impersonate are BLOCKED
  (no GREASE). It's the impersonation, not the library. `hardened.py` peeks the
  ClientHello (MSG_PEEK), computes JA3, 403s no-GREASE fingerprints.
- **HTTP/2 fingerprint:** urllib can't speak h2; curl_cffi emits the correct
  DISTINCT full-Akamai fp per profile — SETTINGS|WINDOW_UPDATE|PRIORITY|pseudo-
  header order (Chrome m,a,s,p / Firefox m,p,a,s / Safari m,s,a,p). JA3 and h2 are
  independent layers — plain curl_cffi fails JA3 but looks Chrome at h2, so a
  WAF checking both catches the mismatch. (`http2fp.py` includes a minimal HPACK
  decoder for the pseudo-header order.)
- **Tier-R+ (TLS + JS challenge):** only real browsers (crawl4ai/playwright/
  selenium) SOLVE; stealth fetchers pass TLS but stall on JS (CHALLENGED);
  urllib + jsdom are BLOCKED at JA3 (jsdom = Node/OpenSSL TLS, no GREASE). Proves
  a hard target must escalate to a full browser, not just a stealth fetch.
- **Extract:** css-json ≥ trafilatura ≥ rule (all title_acc 1.0).
- **Pipeline (hard set):** crawl4ai + qdrant, all 4 gates pass.

## Architecture
```
crawl_eval/
  site_spec.py      authored site (pages + traps + query gold) — SOURCE OF TRUTH
  build_fixtures.py render spec -> fixtures/site1/ (raw HTML + gold)   [grader]
  site_server.py    serve locally + hit-log + endless /maze            [grader]
  hardened.py       Tier-R HTTPS target: peek ClientHello -> JA3 -> 403 no-GREASE
                    (+ optional js_challenge mode = Cloudflare-style JS wall)
  stealth.py        stealth race: which fetch strategy beats the JA3 wall
  http2fp.py        HTTP/2 raw-frame server: capture SETTINGS/WU/PRIORITY fp + race
  challenge.py      Tier-R+ race: TLS wall + JS challenge (fetchers vs browsers)
  oracle.py         score crawl(P/R/F1+js_recall+robots) / extract / search
  fetchers.py       static backends: urllib · curl_cffi · scrapling
  crawl.py          BFS driver + candidates: static ×N + browser (playwright,
                    jsdom, crawl4ai*, selenium*) ; render_jsdom.js helper
  extract.py        rule · css-json · trafilatura
  index.py          stdlib-bm25 · tantivy · meilisearch* · qdrant*   (*gated)
  race.py           crawl / endurance / extract / index races + formatters
  pipeline.py       E2E seed task + two-track scorecard + gates
  cli.py            list|build|selftest|crawl-race|endurance-race|extract-race|
                    index-race|pipeline
```
Every candidate is `available()`-gated (missing dep/container skips, never
crashes); per-candidate try/except in every race (scrapler-eval convention).

## Candidate coverage — ALL raced (nothing gated)
Every candidate in the unraced field is now installed and raced: 4 static
fetchers + greedy, 4 browser engines (crawl4ai, selenium, playwright, jsdom),
3 extractors, 4 search engines (bm25, tantivy, meilisearch, qdrant). To rerun
from a clean machine: recreate `.venv` (see below), `npm install jsdom`,
`sudo playwright install-deps chromium`, and `docker run` meilisearch for its
row. Any missing piece simply `available()`-skips.
```
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python playwright crawl4ai selenium \
  qdrant-client fastembed tantivy curl_cffi scrapling trafilatura browserforge
.venv/bin/python -m playwright install chromium
```

## Next (evo frontier)
1. **Routing policy** = the top optimization surface: static fetch by default,
   detect a JS-nav gap (empty container + injector script), escalate *that URL
   only* to a browser. Wins both races at once.
2. Stand up meili/qdrant for the full search bracket; add crawl4ai/selenium.
3. A **Tier-R hardened target** with a real anti-bot wall so the stealth
   fetchers' extra cost finally pays off (an owned site has no wall to beat).
4. Wire into `/evo:optimize` reusing scrapler-eval metrics/gates/leaderboard.

Relevant memories: `scraper-search-lab`, `spider-den-app`, `evo-lab-home-base`,
`graph-first-protocol`.
