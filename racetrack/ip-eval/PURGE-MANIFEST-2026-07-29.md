# PURGE MANIFEST — ip-eval + scraper/search racetrack losers (2026-07-29)

**INVENTORY ONLY — NOTHING DELETED.** This is an evidence-backed proposal for
reclaiming disk from candidate tools that LOST their races. Every row cites the
latest `results-<stage>-runN.json` (highest N) plus the two handoffs.

Sizes are `du -sh` (1024-based: MiB/GiB). "repo" = clone under
`~/coding/docker-envs/filing-cabinet/library-base/repos/<dir>`; "graph" = graphify
artifact under `~/coding/docker-envs/projects/graphify-app/data/graphs/cloned__library__<dir>__<hash>/`.

## ⚠ Headline reality check (read first)
The two source trees are each ~40 GB, but they hold ~600 library repos total —
**only the ~75 raced eval candidates are in scope.** Summing **every** loser's
repo + graphify artifact (clear-cut + every ambiguous item, widest possible net)
tops out at **≈ 4.4 GiB**. It is **not possible to reclaim 14 GB — let alone
20 GB — purely from losing candidates' cloned repos + graphify artifacts.** The
mass simply is not there: the biggest single loser (ruvector) is ~0.96 GiB; most
are 2–70 MiB.

Where the real space actually lives (documented in "Supplementary reclaim" at the
bottom, but OUT of the literal repos+graphs scope):
- `ip-eval/.venv-candidates/` = **6.5 GiB**, of which the `gliner` venv
  (nemo-gliner, gate FAIL) alone is **4.7 GiB**.
- `data/index.db` = **28 GiB** (graphify's SQLite row store — a separate decision,
  reported only, never touched here).

**Clear-cut purge (sections a + d): ≈ 1.35 GiB. Absolute ceiling incl. all
next-best/ambiguous (section g): ≈ 4.4 GiB.**

---

## (a) IP-EVAL — PURGE list (clear losers, attributable, not shared with any winner)

| candidate | stage | score vs stage winner | verdict evidence | repo (size) | graph (size) | combined |
|---|---|---|---|---|---|---|
| presidio | concepts (run8) | **0.04** vs ip-incumbent **0.7053** | f1 0.0667, nested 0, far below | data-privacy-stack_presidio (230M) | …presidio (19M) | **249M** |
| turso-store | persistence (run7) | **0.5** vs tie **0.85** | 20 lost updates + 20 concurrent errors | tursodatabase_turso (62M) | …turso (146M) | **208M** |
| pouchdb-store | persistence (run7) | **0.775** vs **0.85** | corrupt→"recovered-but-lost-data" (0.25) | pouchdb_pouchdb (18M) | …pouchdb (9.1M) | **27M** |
| hayhooks-api | api (run3) | **0.5714** vs ip **0.625** | fewer API checks pass; user-flagged | deepset-ai_hayhooks (38M) | …hayhooks (7.3M) | **45M** |
| fasttext-classify | concepts (run8) | **0.5442** vs **0.7053** | type_acc 0.25; classifier, not extractor | facebookresearch_fastText (12M) | …fastText (2.7M) | **15M** |
| ontocast | concepts (run8) + graph (run5) | concepts **gate FAIL** (crash); graph **0.7867** vs graphify **0.9833** | LLM/SPARQL; non-JSON crash + low edge recall | growgraph_ontocast (46M) | …ontocast (19M) | **65M** |
| storm-draft | drafting (run6) | **gate FAIL** (crash) vs winner 1.0 | dspy LLM subprocess crash, no score | stanford-oval_storm (12M) | …storm (5.4M) | **17M** |
| hypermem | retrieval (run7) + graph (run5) | retrieval **0.2995** vs tie **0.3564**; graph **0.7467** vs **0.9833** | below on both; user-flagged | EverMind-AI_HyperMem (880K) | …HyperMem (1.7M) | **2.6M** |
| stirling-pdf | convert (run2) | **0.0 / gate FAIL** vs pandoc **0.8319** | ingress f1 0.0 (see note ‡) | Stirling-Tools_Stirling-PDF (304M) | …Stirling-PDF (223M) | **527M** |
| olmocr | convert (run2) | **unavailable** (no-GPU) vs pandoc **0.8319** | CUDA VLM; never produced a score | allenai_olmocr (68M) | …olmocr (14M) | **82M** |
| aann | retrieval (run7) | **0.1646** vs tie **0.3564** (46% of winner) | recall@5 lowest in field | schlegelp_aann (708K) | …aann (324K) | **1M** |
| undoc | extract (run3) | **0.0 / gate FAIL** vs pandoc-pypandoc **0.7989** | docx-only; mean_f1 0.2, adversarial 2/6 | iyulab_undoc (1.8M) | …undoc (5M) | **7M** |
| last30days-dedupe | dedup (run7) | **gate FAIL** (0.0) vs naive **0.6667** | didn't keep unique+swaps | mvanhorn_last30days-skill (55M) | …last30days-skill (20M) | **75M** |

‡ stirling-pdf: HANDOFF notes a bug was found+fixed and an egress probe hit 0.999,
but the confirming full race was killed by the user, so the on-disk JSON still
shows 0.0/FAIL. User explicitly named it PURGE; kept here with this caveat.

**Section (a) subtotal: ≈ 1320.9 MiB ≈ 1.29 GiB (13 candidates).**

---

## (b) IP-EVAL — KEEP list (winners, ties-for-best, incumbent, explicitly praised)

| candidate | reason (latest run) | repo |
|---|---|---|
| ip-incumbent (Information Processer) | THE incumbent; champion of split/concepts/tabilify/dedup/export_docx/export_bibtex/api/security; tied top in retrieval & persistence | (app: projects/information-processer — HARD EXCLUDE) |
| pandoc / pypandoc | convert champion 0.8319; extract champion 0.7989 | jgm_pandoc |
| graphify-graph | graph champion 0.9833 (tie); graphify is also the host app | Graphify-Labs_graphify |
| networkx-cooc | graph champion 0.9833 (tie) | (pip) |
| rank-bm25 · tantivy-py · librer · ragbits-rrf · haystack-bm25 · annoy · suql · local-deep-researcher | retrieval 9-way tie 0.3564 (all = incumbent) | quickwit-oss_tantivy, PJDude_librer, deepsense-ai_ragbits, deepset-ai_haystack, spotify_annoy, stanford-oval_suql, langchain-ai_local-deep-researcher |
| paperspine-draft | drafting 0.9325 > incumbent 0.9077 (2nd overall; det=1) | WUBING2023_PaperSpine |
| wikichat-draft | drafting nominal champion 1.0 (⚠ det=0, UNVERIFIED); user KEEP | stanford-oval_WikiChat |
| opendal-store · sqlite-store | persistence tie 0.85 with incumbent | apache_opendal, (sqlite=stdlib) |
| docx2python | user KEEP (despite convert/extract FAIL) | ShayHill_docx2python |
| mineru | user KEEP (despite convert/extract FAIL) | opendatalab_MinerU |

---

## (c) IP-EVAL — AMBIGUOUS (NOT deleted — shared / marginal / uncertain)

| candidate | why ambiguous |
|---|---|
| quickwit-oss_tantivy | **shared with a winner** — underlies tantivy-py (retrieval KEEP tie) AND is the crawl-eval `tantivy` search engine. KEEP. |
| deepset-ai_haystack (+ -experimental, -cookbook) | **shared with a winner** — haystack-bm25 is in the retrieval KEEP tie; split's haystack-splitter FAILed but same repo. KEEP. |
| deepsense-ai_ragbits (+ create-ragbits-app) | **shared with a winner** — ragbits-rrf retrieval KEEP tie. KEEP. |
| facebookresearch_faiss | retrieval faiss-hashdense **0.345** vs tie 0.3564 = 97% of winner (near-tie); famous general lib. Too close to call → KEEP. |
| stanford-oval_genie-worksheets | tabilify 0.4773 vs 0.5614 — gate PASS, moderate gap (re-examined in §g). |
| synthetic-sciences_openscience | tabilify 0.4773 — gate PASS, moderate gap (re-examined in §g). |
| SheetJS_sheetjs | tabilify 0.4773 — gate PASS (re-examined in §g). |
| google-research_tabfm | tabilify unavailable (no adapter); never scored (§g). |
| nemo-gliner | concepts gate FAIL, but **no filing-cabinet repo** — it's an HF model in the `gliner` venv (4.7 GiB, see Supplementary). Green solo in run6 (0.4896); load-induced timeout in run7/8. |
| spacy-nounchunks | concepts 0.1799 — but spaCy is a **pip package**, no clone repo (lives in shared `concepts` venv). |
| python-docx / docxtpl-minimal / sumy | export_docx 0.8458/0.8436, drafting 0.8328 — all **pip packages**, no clone repos. |
| bgreenwell_doxx, wooorm_mdxjs-rs, web-infra-dev_mdx-rs | export_docx unavailable (can't write DOCX) — never scored (§g). |
| gdt050579_filecache, spotify_SPTPersistentCache | persistence unavailable (Rust / Obj-C) — never scored (§g). |
| JabRef_jabref, apache_opennlp | unavailable (Java lane never attempted) — never scored (§g). |
| ruvnet_ruvector, zeroclaw-labs_zeroclaw, StarTrail-org_LEANN | retrieval/graph unavailable/build-failed — never scored (§g). |
| aquasecurity_trivy, projectdiscovery_nuclei, usestrix_strix | security scanners, binaries not installed — never scored; general-purpose tools (§g). |

---

## (d) SCRAPER / SEARCH — PURGE list (clear losers, definitively non-viable, dedicated repo)

Latest per-stage cards: `crawl-eval/results-{crawl-run3,index-run4,behavioral-run2,challenge-run1,stealth-run1,http2-run1,endurance-run1,extract-run1}.json` + `results/crawl-suite.md`.
Note: most scraper/search WINNERS and most losers (urllib, jsdom, stdlib-bm25, curl_cffi, trafilatura, css-json) are **pip/node/stdlib packages with no clone repo**, so they cannot appear here. Only two candidates both lost AND have a dedicated clone with a definitive "will never run in this lab" reason:

| candidate | stage | outcome vs winner | verdict evidence | repo (size) | graph (size) | combined |
|---|---|---|---|---|---|---|
| cloakbrowser | behavioral (run2) | **skip-gated**, never raced; winner playwright-stealth solved 1.0 | C#/.NET app, not a Python/Node drop-in — out of the pip/node track entirely | cloakhq_cloakbrowser (14M) | …cloakbrowser (21M) | **35M** |
| invisible_playwright | behavioral (run2) | **skip-gated**, never raced | hard-pins playwright>=1.55,<1.56 — conflicts with the 1.61 the whole suite needs; "same Firefox tier as camoufox, already covered" | feder-cr_invisible_playwright (21M) | …invisible_playwright (5.4M) | **26M** |

**Section (d) subtotal: ≈ 61.4 MiB (2 candidates).**

---

## (e) SCRAPER / SEARCH — KEEP list

| candidate | reason | repo |
|---|---|---|
| crawl4ai | crawl champion (js_recall 1.0, fastest full browser); challenge solved | unclecode_crawl4ai |
| playwright + playwright-stealth | crawl 1.0; **behavioral champion** (only engine that solves JA3+JS-fp wall) | microsoft_playwright |
| selenium | crawl 1.0; challenge solved | SeleniumHQ_selenium |
| Scrapling | **spider-den's current base**; wins stealth JA3 (real TLS impersonation) + endurance-class static | D4Vinci_Scrapling |
| curl-impersonate | reference for the TLS-impersonation capability that beats the JA3 wall | lwthiker_curl-impersonate |
| qdrant | index champion 1.0 (semantic + typo) | qdrant_qdrant |
| lance | index champion 1.0 (tie; embedded columnar) | lance-format_lance |
| meilisearch | kept — **typo-tolerance winner** (1.0) + the keyword half of the recommended pipeline | meilisearch_meilisearch |
| tantivy | kept — fastest exact-keyword engine; ALSO an ip-eval retrieval KEEP-tie winner | quickwit-oss_tantivy |
| SearXNG | kept — the discovery layer of the recommended pipeline (SearXNG→scraper→Meili+Qdrant) | searxng_searxng |
| WikiChat / local-deep-researcher / haystack / ragbits | kept — winners/ties in ip-eval (see §b) | stanford-oval_WikiChat, langchain-ai_local-deep-researcher, deepset-ai_haystack, deepsense-ai_ragbits |

---

## (f) SCRAPER / SEARCH — AMBIGUOUS (NOT deleted)

| candidate | why ambiguous | repo (repo+graph) |
|---|---|---|
| **StarTrail-org_PixelRAG** | **HARD EXCLUDE** — the pixel-search-sidecar is an ACTIVE project (PixelRAG visual search on :30001). In use. | 34M + 3.6M |
| jo-inc_camofox-browser (camoufox) | behavioral: blocked at JA3 BUT passes all 6 JS-fingerprint tells (genuine engine-level mask) — a documented, deliberately-kept "honest two-layer" finding, not a plain loser | 5.3M + 2.9M |
| browserless_browserless | behavioral/crawl: skip-gated (needs a live CDP service) but a legit tool you might stand up (§g) | 85M + 7.9M |
| saifyxpro_HeadlessX | Class-3 engine + Job-A search wrapper — rostered but **never raced** (§g) | 204M + 6.8M |
| ScrapeGraphAI_Scrapegraph-ai | Class-3/4 extractor — never raced | 9.7M + 9.8M |
| mitmproxy_mitmproxy | honorable-mention (XHR/JSON capture) — never raced; general-purpose | 60M + 40M |
| lissy93_web-check | recon honorable-mention — never raced; general-purpose | 40M + 3M |
| obsei_obsei, alibaba_page-agent, Johell1NS_browser-search, ythx-101_x-tweet-fetcher, Mahanaicoach_google-maps-scraper-kit | honorable-mentions — never raced | 17M+2.9M / 2.9M+5.1M / 2.3M+0.8M / 0.77M+1.1M / 0.36M+0.08M |
| sigoden_aichat, openags_paper-search-mcp, harveyai_deep-research-starter | Job-A/D discovery/RAG — never raced | 3.2M+6.6M / 1.9M+4.1M / 5.8M+0.1M |
| StarTrail-org_LEANN | Job-C low-storage RAG (WSL-friendly angle); ip-eval retrieval unavailable — never scored but explicitly-interesting → KEEP-lean (§g) | 43M + 8.3M |

Note: **jsdom** (crawl loser, js_recall 0.667) is a **node_module**, not a clone repo — nothing to purge.

---

## (g) NEXT-BEST — re-examined to approach the target (ordered by size, cumulative)

Because clear-cut (a+d) is only ~1.35 GiB, here is every remaining re-examinable
item with a verdict, largest first. **PURGE-OK** = confidently reclaimable;
**LEAN-PURGE** = reclaimable with a caveat; **KEEP/EXCLUDE** = leave it.
Cumulative column counts only PURGE-OK + LEAN-PURGE on top of the 1.35 GiB clear-cut base.

| # | candidate | combined | verdict | evidence | cumulative |
|---|---|---|---|---|---|
| 1 | ruvnet_ruvector | 959M | **PURGE-OK** | retrieval: no PyPI wheel, Rust-only crates, `uv pip install` failed & was purged — dead candidate, never scored, not shared | 2.29 GiB |
| 2 | zeroclaw-labs_zeroclaw | 464M | **PURGE-OK** | graph: build failed (missing `crates/zeroclaw-runtime/src/firmware`), never scored. ⚠ leave the sibling `zeroclaw-labs_*` repos — they are NOT eval candidates | 2.74 GiB |
| 3 | JabRef_jabref | 300M | **PURGE-OK** | export_bibtex: Java/Gradle, no java on box; incumbent won bibtex 1.0. Java lane never attempted | 3.03 GiB |
| 4 | saifyxpro_HeadlessX | 211M | **LEAN-PURGE** | scraper Class-3/Job-A: rostered but never raced; superseded by raced winners crawl4ai/playwright (engines) + SearXNG (discovery). Caveat: never demonstrated to lose | 3.24 GiB |
| 5 | aquasecurity_trivy | 200M | **LEAN-PURGE** | security: binary never installed, never scored; incumbent won security 1.0. Caveat: general vuln scanner you might install later | 3.44 GiB |
| 6 | synthetic-sciences_openscience | 162M | **PURGE-OK** | tabilify 0.4773 vs incumbent 0.5614 — raced, lost, single stage, not shared | 3.60 GiB |
| 7 | apache_opennlp | 97M | **PURGE-OK** | split + concepts: Java/Maven, no java — never scored; incumbent won split | 3.70 GiB |
| 8 | browserless_browserless | 93M | **LEAN-PURGE** | behavioral: skip-gated (needs live CDP service, no container). Caveat: reinstatable as a service | 3.79 GiB |
| 9 | projectdiscovery_nuclei | 55M | **PURGE-OK** | security: binary never installed, never scored | 3.85 GiB |
| 10 | stanford-oval_genie-worksheets | 54M | **PURGE-OK** | tabilify 0.4773 vs 0.5614 — raced, lost | 3.90 GiB |
| 11 | facebookresearch_faiss | 63M | **KEEP** | retrieval 0.345 vs 0.3564 = near-tie (97%); famous general lib — too close | — |
| 12 | StarTrail-org_LEANN | 51M | **KEEP** | explicitly-interesting WSL-friendly low-storage RAG; only "unavailable", never lost a race | — |
| 13 | deepset-ai_haystack-cookbook | 50M | **KEEP** | docs/examples of a KEEP winner family | — |
| 14 | mitmproxy_mitmproxy | 100M | **KEEP** | general-purpose intercept tool; never raced | — |
| 15 | usestrix_strix | 13.5M | **PURGE-OK** | security LLM agent: needs LLM creds + docker sandbox, never ran | 3.91 GiB |
| 16 | bgreenwell_doxx | 11.8M | **PURGE-OK** | export_docx unavailable (reader only, can't write DOCX), never scored | 3.92 GiB |
| 17 | spotify_SPTPersistentCache | 10M | **PURGE-OK** | persistence unavailable (Obj-C, Apple-only), never scored | 3.93 GiB |
| 18 | web-infra-dev_mdx-rs, wooorm_mdxjs-rs | 4.7M + 3.25M | **PURGE-OK** | export_docx unavailable (compile MDX→JSX, can't emit DOCX) | 3.94 GiB |
| 19 | google-research_tabfm | 3.7M | **PURGE-OK** | tabilify: no `table_encoder.py`, no honest adapter, never scored | 3.94 GiB |
| 20 | gdt050579_filecache | 1.76M | **PURGE-OK** | persistence unavailable (Rust crate, no pip binding) | 3.94 GiB |
| 21 | SheetJS_sheetjs | 0.98M | **PURGE-OK** | tabilify 0.4773, lost | 3.95 GiB |
| — | camoufox / cloakbrowser* / invisible* / Scrapegraph-ai / obsei / web-check / aichat / page-agent / browser-search / paper-search-mcp / deep-research-starter / x-tweet-fetcher / maps-kit | ~90M total | **KEEP/AMBIGUOUS** | never raced (no loss evidence) or general-purpose; conservative KEEP (*cloakbrowser+invisible already in §d) | — |

**With §g PURGE-OK + LEAN-PURGE applied, running total ≈ 3.95 GiB. Including
every remaining KEEP-marked ambiguous item as well, the absolute ceiling is
≈ 4.4 GiB — the target of 14–20 GB cannot be met from repos + graphify
artifacts. Full stop.**

---

## TOTALS (reclaimable bytes — repos + graphify artifacts only)

- **(a) IP-EVAL clear-cut PURGE:** 13 candidates, **≈ 1,384.9 MiB ≈ 1.29 GiB** (1,384,878,080 bytes approx.)
- **(d) SCRAPER clear-cut PURGE:** 2 candidates, **≈ 61.4 MiB ≈ 0.06 GiB**
- **(a)+(d) combined clear-cut:** **≈ 1,382.3 MiB ≈ 1.35 GiB**
- **(g) next-best PURGE-OK + LEAN-PURGE added:** **→ ≈ 3.95 GiB cumulative**
- **Absolute ceiling (all losers, every ambiguous item):** **≈ 4.4 GiB**

The 14 GB / 20 GB targets are **not achievable** from losing candidates' repos +
graphify artifacts. See Supplementary reclaim below for where the space actually is.

---

## Supplementary reclaim (OUT of the literal repos+graphs scope — reported so the target is reachable)

These are per-candidate build artifacts and the graph row-store — not "cloned
repos" and not "graphify graph artifacts," so they are excluded from the totals
above, but they are where 20 GB actually lives:

| artifact | size | attribution / note |
|---|---|---|
| `ip-eval/.venv-candidates/gliner` | **4.7 GiB** | nemo-gliner — gate FAIL (crashed run7/8). Pure loser artifact. Biggest single reclaim on the box. |
| `ip-eval/.venv-candidates/` (loser venvs, excl. gliner) | ~0.6 GiB | storm 137M (FAIL), hayhooks 75M, faiss-hashdense 66M, sumy 44M, pouchdb-node 23M, fasttext 22M, turso 14M … all lost/FAILed |
| `ip-eval/.venv-candidates/concepts` | 317M | **shared** venv (presidio/spacy/naive share it) — ambiguous |
| `ip-eval/.venv-candidates/mineru`, `/pandoc` | 601M + 233M | **KEEP** — mineru is a user-KEEP; pandoc is the convert/extract WINNER |
| `crawl-eval/.venv` | 1.2 GiB | **KEEP-shared** — holds the winners (playwright+chromium, scrapling, qdrant/fastembed, tantivy) |
| `arxiv-eval/.venv` | 320M | KEEP-shared (winners) |
| `graphify-app/data/index.db` | **28 GiB** | graphify's SQLite store. Deleting rows for purged repos is a **separate decision** — reported only, NOT included in any total, NOT touched. |

Realistic path to the target: **§a+§d+§g repos/graphs (~4 GiB) + the gliner
loser venv (4.7 GiB) + other loser venvs (~0.6 GiB) ≈ 9.3 GiB.** Reaching 20 GB
beyond that requires pruning `index.db` rows (28 GiB store) or shared winner
venvs — both outside this manifest's conservative scope.

---

## HARD EXCLUSIONS honored
No path containing `backup`/`archive`/`.bak`; the `np-wade/evo-myworld-archives`
release backups; `spider-den`; the incumbent `information-processer`; and any repo
a KEEP winner depends on (tantivy, haystack, ragbits, pandoc, graphify, qdrant,
lance, meilisearch, searxng, WikiChat, local-deep-researcher, opendal, MinerU,
docx2python, PaperSpine, Scrapling, crawl4ai, playwright, selenium) — all kept.
`StarTrail-org_PixelRAG` excluded (active pixel-search-sidecar project).
