# HANDOFF — candidate integration + Test 5 (internal crawl+search)

**Written:** 2026-07-26. **For:** the next AI (or seat) picking this up.
**One-line:** Tests 1–4 are built, green, and visible in `racetrack/results/`.
This doc covers (a) the crawling/scraping tools that were NOT yet raced and how
to fold them in, (b) the design for **Test 5 — internal crawl + search**, which
is the natural home for most of those tools, and (c) every file location.

---

## 0. Where things stand

- **T1 arXiv / T2 Substack / T3 Video / T4 Watchdog** — all built, green,
  end-to-end. Result cards + HTML dashboard in `racetrack/results/`.
- The four tests exercised the **fetch layer** hard (Scrapling + curl-impersonate
  won almost everything) and touched one **parser** (beautifulsoup4 in T4). They
  did NOT exercise **full-site crawling**, **browser automation**, **stealth
  browsers**, or **source-specialist harvesters**. Those are the unraced field.

---

## 1. Report — what was NOT included (from the crawling/scraping list)

### Used in T1–T4
| Tool | Corpus folder | Where used |
|---|---|---|
| Scrapling | `D4Vinci_Scrapling` | fetch backend, all 4 tests (won T1 fetch) |
| beautifulsoup4 | `openkylin_beautifulsoup4` | T4 `soup-diff` differ candidate |
| playwright | `microsoft_playwright` | only as Scrapling's dependency, not a standalone candidate |
| **curl-impersonate** | `lwthiker_curl-impersonate` | via `curl_cffi` — the workhorse across ALL tests; **was not on the original list** (the key omission) |

### Named as a candidate but deferred (in a bracket, unrun)
| Tool | Corpus folder | Note |
|---|---|---|
| HeadlessX | `saifyxpro_HeadlessX` | listed as a deferred browser-discovery candidate in T1 |

### NOT included at all (the unraced field)
| Tool | Corpus folder | Natural role |
|---|---|---|
| crawl4ai | `unclecode_crawl4ai` | **T5 crawl engine** (LLM-friendly crawler) |
| Scrapegraph-ai | `ScrapeGraphAI_Scrapegraph-ai` | **T5** crawl+extract (graph/LLM pipeline) |
| camofox-browser | `jo-inc_camofox-browser` | **T5 stealth-browser** crawl engine |
| cloakbrowser | `cloakhq_cloakbrowser` | **T5 stealth-browser** crawl engine |
| invisible_playwright | `feder-cr_invisible_playwright` | **T5** stealth Playwright driver |
| puppeteer | `puppeteer_puppeteer` | **T5** headless-Chrome crawl engine |
| selenium | `SeleniumHQ_selenium` | **T5** classic browser-automation baseline |
| playwriter | `remorses_playwriter` | T5 accessory — NL→Playwright control |
| browserless | `browserless_browserless` | **T5** scalable headless-Chrome service (needs a container) |
| page-agent | `alibaba_page-agent` | T5 accessory — autonomous in-DOM scraping agent |
| Agent-Reach | `Panniantong_Agent-Reach` | accessory — multi-channel reach framework |
| appium | `appium_appium` | out-of-scope for web T5 (mobile-app automation) |
| CodeceptJS | `codeceptjs_CodeceptJS` | T5 accessory — high-level crawl-scenario engine |
| cucumber-playwright | `Tallyb_cucumber-playwright` | accessory — BDD driver, low priority |
| nuclei | `projectdiscovery_nuclei` | accessory — security crawl scanner, recon only |
| google-maps-scraper-kit | `Mahanaicoach_google-maps-scraper-kit` | source-specialist (Maps), its own future test |
| google-scholar (tutorial) | `oxylabs_how-to-scrape-google-scholar` | reference code, not a lib — skip as a candidate |
| x-tweet-fetcher | `ythx-101_x-tweet-fetcher` | source-specialist (X/Twitter), its own future test |

**Also missing from the original list but in the corpus** (flagged earlier):
`mitmproxy_mitmproxy` (network interception / API-endpoint recon),
`Johell1NS_browser-search` (in-browser SERP), and the harvesters
`yt-dlp_yt-dlp` (used in T3), `obsei_obsei`, `searxng_searxng` (used in T1).

---

## 2. How to include the unraced tools

Two mechanisms, both already proven in T1–T4:

### 2a. Fold browser/stealth engines into EXISTING tests as new candidates
Each test's stage modules take `available()`-gated candidates. A browser engine
is just another candidate class with a `.get(url)`/`.crawl(seed)` method:
- **T2 Substack discover** — add a **headless-scroll** candidate (Playwright /
  puppeteer / camofox) to finally beat the 0.318 static-archive recall. This is
  the single highest-value insertion: it's the one place a browser demonstrably
  wins (the lazy-load wall), and the slot is already marked DEFERRED.
- **T1/T3 stealth brackets** — add camofox-browser, cloakbrowser,
  invisible_playwright as stealth fetch strategies so the "how stealthy" race
  has real browser contenders, not just TLS impersonation. (Note: no anti-bot
  wall has appeared in-session yet — these only pay off once a hardened target
  is added, so pair them with a Tier-R target that actually blocks.)

Mechanics (same as every existing eval):
- Corpus-first: read the donor at `filing-cabinet/library-base/repos/<folder>`
  before writing the adapter (GRAPH-FIRST per [[graph-first-protocol]]).
- `available()`-gate on the dep/import/service so a missing piece SKIPS.
- Install via `uv` into the eval's `.venv` (host python has no pip):
  `~/.local/bin/uv pip install --python .venv/bin/python <dep>`.
- Node engines (puppeteer, browserless, CodeceptJS) need a node runtime and/or
  a container — gate them behind a service check, don't let them crash the race.
- Per-candidate try/except in the race loop (already standard).

### 2b. Race the full crawlers head-to-head in a new test — Test 5 (below)
crawl4ai, Scrapegraph-ai, puppeteer, selenium, browserless, page-agent belong
in a real multi-page CRAWL benchmark, which none of T1–T4 provide. That is T5.

---

## 3. Test 5 — Internal Crawl + Search (the crawler bracket)

**Situation none of T1–T4 cover:** start from a seed URL, follow links across a
whole site, and make the crawled corpus searchable — the full crawl→index→query
leg. "Internal" = we crawl a site whose complete page set + answers we OWN, so
the truth is authored (T4's strongest form of the oracle trick), no external API.

### Seed prompt
> "Crawl <site> completely; build a searchable index of every page; then answer
> these queries with the exact pages that satisfy them; deliver a report."

### Oracle trick (grader-only truth)
Stand up (or freeze) a **self-hosted internal site** with a KNOWN structure:
- authored page inventory = the complete URL set (discovery gold),
- per-page content we wrote = field/extract gold,
- a fixed query set with KNOWN correct answer-pages (search gold),
- planted traps: pages behind a JS-rendered nav (only a browser engine reaches
  them), duplicate/canonical pairs, a pagination trail, a robots-disallowed
  path (politeness gate), and a deep link only reachable at depth ≥3.
The site can be a static mirror served locally OR generated fixtures under
`fixtures/site1/`. Fully offline + deterministic once frozen.

### Stage grid (candidates raced, `available()`-gated)
| Stage | Job | Candidates (from the unraced field) |
|---|---|---|
| 1 Crawl | seed → full URL+content set (BFS, link-follow, depth limit, politeness) | **crawl4ai · puppeteer · selenium · playwright · browserless · camofox · cloakbrowser · invisible_playwright** + a stdlib `requests+linkparse` baseline |
| 2 Normalize | dedup, canonicalize, strip volatile | rule baseline (reuse T4 snapshot normalizers) |
| 3 Extract | page → title/body/links | trafilatura (T2 winner) · Scrapegraph-ai · css/rule |
| 4 Index | corpus → searchable | **meilisearch (keyword) · tantivy (keyword) · qdrant (vector) · lance** + a stdlib inverted-index baseline |
| 5 Query | queries → answer-pages | BM25 / vector kNN per index |
| 6 Report | table of pages + query answers + manifest | JSON/CSV + saved pages |

### Scoring (two-track, no LLM judge in the hard path)
- **Crawl completeness** — precision/recall of URLs vs the authored inventory
  (does a browser engine reach the JS-nav pages the static baseline can't?).
- **Crawl cost / politeness** — pages/sec, total requests, robots-respect gate
  (fetching a disallowed path = hard-fail), depth reached.
- **Extract fidelity** — vs authored page gold.
- **Search quality** — precision@k / recall of answer-pages vs the query gold
  (this is where meili vs tantivy vs qdrant finally race — Search Jobs B/C from
  `candidates-search.md`).
- **Advisory** — result-snippet readability only.

### Why "internal" is the right first cut
Owning the site means: perfect gold, zero politeness risk to third parties, and
a controllable JS-nav trap that PROVES when a browser engine earns its cost over
a plain fetcher — the exact question T1–T4 never forced because their targets
were reachable without a browser.

### Build order
1. `/bench-factory` scaffold → `racetrack/crawl-eval/` (package `crawl_eval/`).
2. Author `fixtures/site1/` + serve locally (or freeze) + `fetch_fixtures.py`
   builds the inventory/query gold.
3. Stdlib crawl + inverted-index baseline first → selftest green offline.
4. Add crawl-engine candidates (start crawl4ai + one browser engine), then the
   index candidates (meili/tantivy/qdrant — each may need a container; gate it).
5. `pipeline` end-to-end + `score_pipeline`; wire into evo HQ.
6. Remember to tear down any containers (browserless, meili, qdrant) — record
   cleanup status at the top of `crawl-eval/HANDOFF.md`.

---

## 4. Locations — everything

### The four built tests
| What | Path (under `~/coding/docker-envs/projects/evo-myworld/racetrack/`) |
|---|---|
| T1 arXiv | `arxiv-eval/` (pkg `arxiv_eval/`, `results-*.json`, `pipeline-run1.json`, `out/2026-07-14/`, `fixtures/2026-07-14/`, `HANDOFF.md`) |
| T2 Substack | `substack-eval/` (pkg `substack_eval/`, `results-{discover,extract,fetch}-run1.json`, `pipeline-run1.json`, `out/<pub>/`, `fixtures/<pub>/`, `HANDOFF.md`) |
| T3 Video | `video-eval/` (pkg `video_eval/`, `results-stealth-run1.json`, `results-asr-run1.json`, `pipeline-run1.json`, `out/youtube/UF8uR6Z6KLc/`, `fixtures/{youtube,twitch,arbitrary}/`, `HANDOFF.md`) |
| T4 Watchdog | `watchdog-eval/` (pkg `watchdog_eval/`, `results-diff-run1.json`, `pipeline-run1.json`, `out/set1/`, `fixtures/set1/`, `HANDOFF.md`) |
| T5 Crawl+Search | `crawl-eval/` (TO BUILD — this doc is the spec) |

### evo-HQ visibility surface
| What | Path |
|---|---|
| Results index | `racetrack/results/INDEX.md` |
| Per-suite cards | `racetrack/results/{arxiv,substack,video,watchdog}-suite.md` |
| HTML dashboard | `racetrack/results/dashboard.html` |
| Racetrack infra | `racetrack/RACETRACK.md`, `racetrack/run-race.sh`, `racetrack/STATUS` |

### Design / planning
| What | Path |
|---|---|
| 4-test suite plan | `racetrack/scraper-search-lab/test-suite-plan.md` |
| T1 design doc | `racetrack/scraper-search-lab/arxiv-benchmark.md` |
| Candidate pools | `racetrack/scraper-search-lab/candidates-{scraping,search,expanded}.md` |
| THIS handoff | `racetrack/scraper-search-lab/HANDOFF-integration-and-T5.md` |
| Sibling harness (reuse core) | `racetrack/scrapler-eval/` |

### Corpus + factory
| What | Path |
|---|---|
| Donor repos | `~/coding/docker-envs/filing-cabinet/library-base/repos/` (616 repos) |
| Bench-factory skill | `~/.claude/skills/bench-factory/SKILL.md` (`/bench-factory`) |

Relevant memories: `scraper-search-lab`, `evo-lab-home-base`,
`graph-first-protocol`, `spider-den-app`.

---

## 5. Next actions (priority order)
1. **T2 headless-scroll candidate** — highest-value single insertion (beats the
   0.318 static-archive recall; slot already DEFERRED).
2. **Build T5** via `/bench-factory` — races the whole unraced crawler field.
3. **Add a Tier-R hardened target** so the stealth-browser candidates
   (camofox/cloak/invisible_playwright) have a wall to prove themselves on.
4. **Wire T1–T4 into `/evo:optimize`** — the DEFERRED column is the search
   frontier; reuse `scrapler-eval` metrics/gates/leaderboard/store.
5. Source-specialist tests later: Maps (`google-maps-scraper-kit`), X
   (`x-tweet-fetcher`) — each its own small benchmark.
