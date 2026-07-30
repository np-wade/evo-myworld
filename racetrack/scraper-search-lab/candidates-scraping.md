# Scraping / browser candidates ("better than Playwright")

> Full 10-section expanded pool (browsers, anti-bot, recon, OCR/doc, harvesters,
> archiving, agents, dashboard) + misfiled-repo corrections:
> see [candidates-expanded.md](candidates-expanded.md).


Corpus root: `~/coding/docker-envs/filing-cabinet/library-base/repos/`
All folders below are verified present (36/36 candidates in corpus).

Grouped into **weight classes** so matchups are fair — you can't race a no-JS
fetcher against a full browser on a JS-heavy page.

---

## Class 1 — No-JS fetchers (fastest / cheapest)
Beat Playwright by *not being a browser at all* when the page doesn't need JS.

| Candidate | Corpus folder | Role / why it's a contender |
|---|---|---|
| **curl-impersonate** | `lwthiker_curl-impersonate` | TLS/JA3 fingerprint impersonation — passes Cloudflare on static pages with no browser. The speed/cost champion. |
| **Scrapling** (static mode) | `D4Vinci_Scrapling` | Stealthy HTTP fetch + adaptive selectors; spider-den's current base. |
| httpx baseline | *(std lib / stub)* | Control group — plain requests, no stealth. |

## Class 2 — Stealth browsers (the main event — real Playwright replacements)
For JS + anti-bot. Metric leans hardest on **evasion** + **completeness**.

| Candidate | Corpus folder | Role / why it's a contender |
|---|---|---|
| **cloakbrowser** | `cloakhq_cloakbrowser` | Anti-detect CDP browser, humanized input — undetected by design. |
| **camofox-browser** | `jo-inc_camofox-browser` | Camoufox — hardened anti-fingerprint Firefox; beats vanilla PW on detection. |
| **invisible_playwright** | `feder-cr_invisible_playwright` | Playwright + SOCKS/Firefox stealth prefs, patched fingerprints. |
| **Scrapling** (patchright mode) | `D4Vinci_Scrapling` | Dynamic fetch via patchright + zendriver escalation (bundled). |
| **playwright** (baseline) | `microsoft_playwright` | The thing we're trying to beat — reference contender. |

## Class 3 — Full engines / orchestrators (end-to-end)
Fetch + render + extract in one. Metric leans on **completeness + throughput**.

| Candidate | Corpus folder | Role / why it's a contender |
|---|---|---|
| **crawl4ai** | `unclecode_crawl4ai` | Async crawler engine + LLM markdown; spider-den already leans on it. |
| **HeadlessX** | `saifyxpro_HeadlessX` | Headless browser API with anti-detection + Tavily/Exa search hooks. |
| **browserless** | `browserless_browserless` | Headless-Chrome-as-a-service — pool/scale many browsers. |
| **Scrapegraph-ai** | `ScrapeGraphAI_Scrapegraph-ai` | LLM graph extraction pipeline — spider-den's extraction ideas source. |

## Class 4 — Extractors (content out of HTML)
Same fetched HTML in, structured content out. Metric = **field accuracy vs a ground-truth key**.

| Candidate | Source | Role |
|---|---|---|
| markdown / trafilatura | spider-den `extractors/markdown.py`, `article.py` | Readability-style article/markdown. |
| css_json | spider-den `extractors/css_json.py` | Schema-driven CSS selectors. |
| adaptive (self-healing) | spider-den `extractors/adaptive.py` | Selectors that repair themselves (Scrapling idea). |
| llm_extract | spider-den `extractors/llm_extract.py` | LLM structured extraction. |
| Scrapegraph-ai | `ScrapeGraphAI_Scrapegraph-ai` | Multi-step LLM extraction. |

---

## Grand final
Winner(Class1) → Winner(Class2/3) → Winner(Class4), assembled into one pipeline,
raced against **spider-den's current default** (`http_static` + markdown).

## Honorable mentions (in corpus, swap in if a class needs more entrants)
- `Johell1NS_browser-search` — cloakbrowser + readability glue pattern
- `ythx-101_x-tweet-fetcher` — nitter/camofox X scraping specialist
- `Mahanaicoach_google-maps-scraper-kit` — maps specialist
- `alibaba_page-agent` — agentic page navigation
- `mitmproxy_mitmproxy` — intercept/replay + capture XHR/JSON APIs directly
- `lissy93_web-check` — site recon (headers/DNS/tech fingerprint)
- `obsei_obsei` — Observer→Analyzer→Informer; closest in-corpus to a change monitor
