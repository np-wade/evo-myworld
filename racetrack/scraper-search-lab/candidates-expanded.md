# Expanded candidate pool (Nicholas's 10-section add, 2026-07-25)

Corpus root: `~/coding/docker-envs/filing-cabinet/library-base/repos/`
**All 59 repos below verified present in corpus.** This file extends
[candidates-scraping.md](candidates-scraping.md) and
[candidates-search.md](candidates-search.md) with the full submitted list.

Key distinction the racetrack cares about:

- **RACE** = competing alternatives for the same job → they go in a bracket and
  fight; one winner per class.
- **ACCESSORY** = a pipeline stage or add-on that isn't competing with anything
  (OCR, doc conversion, dashboard, task queue). Added once, not raced — but we
  still pick the best when two cover the same job.

See the **Corrections** section at the bottom for repos that were filed under
the wrong role.

---

## §1 — Existing upstreams (already adapted, NOT raced)
These are spider-den's current baseline; they're the *incumbents* the challengers
must beat, credited in `spider-den/SOURCES.md`. Not entrants — they're the
control group.

| Repo | Powers |
|---|---|
| `D4Vinci_Scrapling` | `fetchers/http_static.py`, `extractors/adaptive.py`, stealth chrome |
| `unclecode_crawl4ai` | `engine/browser_adapter.py`, `extractors/markdown.py`, `css_json.py`, `deepcrawl/crawler.py` |
| `ScrapeGraphAI_Scrapegraph-ai` | `graphs/smart.py`, `config/models_registry.py` |
| `Mahanaicoach_google-maps-scraper-kit` | `specialists/google_maps.py` |
| `ythx-101_x-tweet-fetcher` | `specialists/x_twitter.py` |

---

## §2 — Core browser / crawl engines  → **RACE (Class 2 & 3)**
Folds into the existing Class-2 (stealth browsers) and Class-3 (full engines)
brackets. New entrants marked ➕.

| Candidate | Corpus folder | Bracket | Note |
|---|---|---|---|
| playwright (baseline) | `microsoft_playwright` | C2 | the thing to beat |
| browserless | `browserless_browserless` | C3 | remote headless cluster / CDP pooling — the **scale** entrant |
| ➕ puppeteer | `puppeteer_puppeteer` | C2 | CDP automation alternative (Node) |
| ➕ selenium | `SeleniumHQ_selenium` | C2 | WebDriver reference; legacy-site nav |
| saifyxpro_HeadlessX | `saifyxpro_HeadlessX` | C3 | lightweight headless daemon + search hooks |
| ➕ remorses_playwriter | `remorses_playwriter` | C2 | Playwright control + `storageState` session persistence |

## §3 — Stealth / anti-bot evasion  → **RACE (Class 2 evasion sub-metric)**
These compete on the *evasion* metric specifically.

| Candidate | Corpus folder | Note |
|---|---|---|
| feder-cr_invisible_playwright | `feder-cr_invisible_playwright` | webdriver/canvas/WebGL spoof patches for `playwright_adapter.py` |
| cloakhq_cloakbrowser | `cloakhq_cloakbrowser` | anti-detect CDP browser |
| jo-inc_camofox-browser | `jo-inc_camofox-browser` | Camoufox hardened Firefox |
| lwthiker_curl-impersonate | `lwthiker_curl-impersonate` | TLS/HTTP2 fingerprint (also Class-1 fetcher) |
| ➕ cloudflare_pingora | `cloudflare_pingora` | **ACCESSORY** — proxy-rotation framework, not a browser; big Rust build |
| ➕ Tallyb_cucumber-playwright | `Tallyb_cucumber-playwright` | **ACCESSORY** — Cucumber/Gherkin BDD *test* harness; a recipe/step pattern, not a scraper (see corrections) |

## §4 — OSINT recon & network interception  → **ACCESSORY (pre-scrape recon stage)**
Not raced against the scrapers — they run *before/around* a scrape. Pick best-of.

| Candidate | Corpus folder | Note |
|---|---|---|
| lissy93_web-check | `lissy93_web-check` | DNS/SSL/headers/tech-stack/sitemap/robots recon — best default recon |
| projectdiscovery_nuclei | `projectdiscovery_nuclei` | template WAF/tech/endpoint probing (security tool, secondary use) |
| mitmproxy_mitmproxy | `mitmproxy_mitmproxy` | capture SPA JSON/XHR APIs during a browser run |
| FiloSottile_mkcert | `FiloSottile_mkcert` | local CA for HTTPS MITM decrypt (enables mitmproxy) |
| alibaba_page-agent | `alibaba_page-agent` | in-browser Re-act **agent** loop + DOM/bbox extraction (more §9; see corrections) |

## §5 — Document processing, OCR & text post-proc  → **ACCESSORY (post-fetch extract)**
Two sub-jobs that DO race: (a) PDF/image→markdown, (b) office-file→data.

**(a) PDF / scanned-doc → markdown — RACE this bracket:**
| Candidate | Corpus folder | Note |
|---|---|---|
| allenai_olmocr | `allenai_olmocr` | VLM PDF→markdown w/ equations+tables |
| opendatalab_MinerU | `opendatalab_MinerU` | academic/multi-column PDF→structured MD |
| PaddlePaddle_PaddleOCR | `PaddlePaddle_PaddleOCR` | multilingual OCR (Python, heavy) |
| zibo-chen_rust-paddle-ocr | `zibo-chen_rust-paddle-ocr` | Rust PaddleOCR — lighter WSL angle |
| Stirling-Tools_Stirling-PDF | `Stirling-Tools_Stirling-PDF` | full PDF suite (OCR/split/redact) — ACCESSORY, not really racing |

**(b) office / text — ACCESSORY:**
| Candidate | Corpus folder | Note |
|---|---|---|
| ShayHill_docx2python | `ShayHill_docx2python` | .docx text/table/image extract |
| SheetJS_sheetjs | `SheetJS_sheetjs` | xlsx/csv parse+export |
| jgm_pandoc | `jgm_pandoc` | universal format converter |
| BoundaryML_baml | `BoundaryML_baml` | typed/streaming JSON extraction schema lang |
| hardikpandya_stop-slop | `hardikpandya_stop-slop` | LLM "slop" filter (guide/refs, not a runtime lib) |

## §6 — Specialized harvesters & source scrapers  → **ACCESSORY (specialists, add-on modules)**
Each is a source specialist like the existing google_maps/x_twitter — added, not raced.

| Candidate | Corpus folder | Note |
|---|---|---|
| yt-dlp_yt-dlp | `yt-dlp_yt-dlp` | media/subs/metadata, 1000+ sites — clear keep |
| oxylabs_how-to-scrape-google-scholar | `oxylabs_how-to-scrape-google-scholar` | Scholar scraper — **tutorial repo, not a lib** (reference code) |
| searxng_searxng | `searxng_searxng` | meta-search — belongs in **Search Job A** (discover), see candidates-search.md |
| obsei_obsei | `obsei_obsei` | reddit/youtube/appstore harvester |
| Panniantong_Agent-Reach | `Panniantong_Agent-Reach` | multi-channel agent tool-reach framework |
| ChenLiu-1996_CitationMap | `ChenLiu-1996_CitationMap` | citation-tree harvester (academic) |
| WUBING2023_PaperSpine | `WUBING2023_PaperSpine` | paper-structure harvester (academic) |
| Johell1NS_browser-search | `Johell1NS_browser-search` | in-browser SERP scraping (also Search Job A) |
| ⚠ bgreenwell_lstr | `bgreenwell_lstr` | **MISFILED** — dir-tree TUI viewer, not OSINT (see corrections) |
| ⚠ bgreenwell_xleak | `bgreenwell_xleak` | **MISFILED** — Excel/spreadsheet terminal viewer (see corrections) |
| ⚠ bgreenwell_doxx | `bgreenwell_doxx` | **MISFILED** — .docx terminal viewer (see corrections) |

## §7 — Task queue, cache, storage & indexing  → **ACCESSORY + RACE (search jobs B/C)**
| Candidate | Corpus folder | Role |
|---|---|---|
| Nukesor_pueue | `Nukesor_pueue` | ACCESSORY — background job runner for /crawl, /capture |
| LMCache_LMCache | `LMCache_LMCache` | ACCESSORY — LLM KV-cache; only helps if **self-hosting the LLM** (see corrections) |
| quickwit-oss_tantivy | `quickwit-oss_tantivy` | RACE — Search Job B (full-text), vs Meilisearch |
| qdrant_qdrant | `qdrant_qdrant` | RACE — Search Job C (vector), the favorite |

## §8 — Archiving, capture & offline packaging  → **ACCESSORY**
| Candidate | Corpus folder | Note |
|---|---|---|
| tw93_Pake | `tw93_Pake` | ⚠ **MISFILED** — Tauri web→desktop-app wrapper, NOT an HTML archiver (see corrections) |
| monolith | *not in corpus* | the real single-file-HTML archiver (planned pull per SOURCES.md) |
| transmute-app_transmute | `transmute-app_transmute` | ⚠ **MISFILED** — self-hosted file **converter** (pandoc-like + REST); belongs in §5 |
| koala73_worldmonitor | `koala73_worldmonitor` | real-time news/geo dashboard — closer to §10 UI / a monitor |

## §9 — AI web agents & research automation  → **RACE (Search Job A / D)**
| Candidate | Corpus folder | Role |
|---|---|---|
| langchain-ai_local-deep-researcher | `langchain-ai_local-deep-researcher` | iterative local research loop — Search Job A/D |
| harveyai_deep-research-starter | `harveyai_deep-research-starter` | deep-research pipeline — Search Job A/D |
| stanford-oval_storm | `stanford-oval_storm` | multi-perspective synthesis — Search Job D |
| openinterpreter_openinterpreter | `openinterpreter_openinterpreter` | ACCESSORY — agent runtime to *drive* the browser |
| cuga-project_cuga-agent | `cuga-project_cuga-agent` | ACCESSORY — enterprise generalist agent harness |
| superagent-ai_superagent | `superagent-ai_superagent` | ACCESSORY — agent/tool-routing framework |

## §10 — Dashboard UI & output viz  → **ACCESSORY (front-end only)**
| Candidate | Corpus folder | Role |
|---|---|---|
| apache_echarts | `apache_echarts` | crawl-metrics charts in the :8971 dashboard |
| harveyai_react-doc-viewer | `harveyai_react-doc-viewer` | preview scraped PDF/DOCX/screenshots in dashboard |
| shshemi_tabiew | `shshemi_tabiew` | TUI for JSON/CSV output from `bh spider` CLI |
| StarTrail-org_PixelRAG | `StarTrail-org_PixelRAG` | ⚠ **MISFILED from §3** — visual RAG (screenshots→retrieval), a Search Job C variant, not stealth |

---

## CORRECTIONS — repos filed under the wrong section

Verified against each repo's README/CARD in corpus:

1. **`tw93_Pake` (§8 archiving)** — FALSE. Pake is a **Tauri wrapper that turns a
   web app into a native desktop app**. It does *not* produce single-file HTML
   archives. That job belongs to **monolith** (not yet in corpus; a planned
   pull). → Reclassify: either drop, or keep as a desktop-shell option for the
   dashboard (overlaps `projects/evo-desktop`).

2. **`transmute-app_transmute` (§8 archiving/page capture)** — FALSE. Transmute
   is a **self-hosted file-format converter** (images/video/audio/docs/
   spreadsheets) with a REST API — a pandoc peer. → Move to **§5 document
   processing / conversion**.

3. **`bgreenwell_lstr` / `xleak` / `doxx` (§6 "OSINT & data-leakage harvesting")**
   — FALSE, all three. They're bgreenwell's **terminal file viewers**:
   - `lstr` = interactive directory-**tree** TUI (a `tree`/`ls` replacement).
   - `xleak` = **Excel/spreadsheet** terminal viewer/extractor (.xlsx/.ods/.csv).
     The name reads like "data leak" but it's "eXcel leak → expose Excel."
   - `doxx` = **.docx** terminal viewer/exporter (LaTeX equations, tables).
   → `xleak`/`doxx` overlap `SheetJS`/`docx2python` → **§5 (b) office files**.
   `lstr` is a CLI tree viewer → **§10 UI/CLI** or drop (not scraping-relevant).

4. **`StarTrail-org_PixelRAG` (§3 "Playwright screenshotting / stealth / anti-bot")**
   — MISFILED. PixelRAG is a research codebase for **visual RAG — retrieving over
   web *screenshots* instead of text** (arXiv paper). It has nothing to do with
   stealth or anti-bot evasion. → Move to **§7/Search Job C (vector/semantic),
   visual variant** — it competes with Qdrant-over-text, not with camofox.
   (This is the same PixelRAG as the `[[pixel-search-sidecar]]` on :30001.)

### Borderline (kept, but flagged)
- **`cloudflare_pingora` (§3)** — a proxy/networking *framework*, not a browser;
  an accessory for a proxy-rotation layer, and a heavy Rust build. Keep as
  ACCESSORY, not a Class-2 entrant.
- **`Tallyb_cucumber-playwright` (§3)** — a Cucumber/Gherkin **BDD test harness**
  for Playwright, not a scraping "recipe engine." Usable as a step/recipe
  *pattern* (dismiss-cookie → scroll → wait), but it's a test framework.
- **`alibaba_page-agent` (§4 recon)** — actually an in-browser **GUI agent**
  (observe→think→act loop). Does DOM/a11y-tree + bbox extraction, so the recon
  use is real, but it fits **§9 agents** better.
- **`oxylabs_how-to-scrape-google-scholar` (§6)** — a **how-to/tutorial** repo,
  not a maintained library. Reference code only.
- **`LMCache_LMCache` (§7 storage/indexing)** — an **LLM KV-cache for inference
  serving** (vLLM prefix reuse). Only cuts cost if you **self-host the extraction
  LLM**; it does not store/index scraped content. Accessory, conditional.
- **`hardikpandya_stop-slop` (§5)** — a guide + reference phrases, not a drop-in
  runtime library; treat as a filter *ruleset*.
