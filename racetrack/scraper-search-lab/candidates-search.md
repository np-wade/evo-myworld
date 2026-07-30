# Search candidates (the layer to pair with scraping)

Corpus root: `~/coding/docker-envs/filing-cabinet/library-base/repos/`
All folders verified present in corpus.

"Search" splits into three jobs around scraping. You likely want **one winner
per job**, chained: **discover URLs → scrape → index/query**.

---

## Job A — Web / meta-search (DISCOVER what to scrape)
Turn a query into a ranked list of target URLs to hand the scraper.

| Candidate | Corpus folder | Role / why it's a contender |
|---|---|---|
| **SearXNG** ⭐ | `searxng_searxng` | Self-hosted meta-search — aggregates Google/Bing/DDG/etc, **no API keys**, privacy-preserving. Best default discovery layer for the lab. |
| **HeadlessX** | `saifyxpro_HeadlessX` | Wraps AI search APIs (Tavily / Exa) + scraping in one box — search-and-fetch combined. |
| **local-deep-researcher** | `langchain-ai_local-deep-researcher` | Iterative search→summarize→re-search loop (local LLM). For deep multi-hop discovery. |
| **deep-research-starter** | `harveyai_deep-research-starter` | Streamlit deep-research pipeline (search + synthesize). |
| **browser-search** | `Johell1NS_browser-search` | Browser-driven search + readability — search from inside a stealth browser. |

## Job B — Full-text search (INDEX + query what you scraped)
Store scraped content, query it by keyword/facet. Metric = relevance + latency + footprint.

| Candidate | Corpus folder | Role / why it's a contender |
|---|---|---|
| **Meilisearch** ⭐ | `meilisearch_meilisearch` | Fast, typo-tolerant, turnkey full-text engine. Easiest to stand up + query. |
| **Tantivy** | `quickwit-oss_tantivy` | Embeddable Rust Lucene-like library — no server, lives in-process. |
| *(elasticsearch)* | *not raced by default* | Heavyweight; too big for the WSL box unless we specifically test scale. |

## Job C — Vector / semantic search (RAG over scraped content)
Embed scraped content, retrieve by meaning. Metric = recall@k / MRR, build time, **storage footprint**.

| Candidate | Corpus folder | Role / why it's a contender |
|---|---|---|
| **Qdrant** ⭐ | `qdrant_qdrant` | Production vector DB — payloads, facets, filtering. Best all-round semantic store. |
| **LEANN** | `StarTrail-org_LEANN` | Low-storage RAG index — tiny footprint (the WSL-friendly angle). |
| **FAISS** | `facebookresearch_faiss` | Vector-similarity library, GPU-capable — the raw-speed baseline. |
| **Annoy** | `spotify_annoy` | Lightweight approximate-NN — minimal deps, fast to try. |

## Job D — Retrieval orchestration (optional: search+scrape → grounded answer)
If we want the pipeline to *answer questions* over scraped data, not just return pages.

| Candidate | Corpus folder | Role |
|---|---|---|
| **Haystack** | `deepset-ai_haystack` (+`-experimental`, `-cookbook`) | Full retrieval/RAG pipeline framework. |
| **ragbits** | `deepsense-ai_ragbits` (+`create-ragbits-app`) | Modular RAG building blocks. |
| **aichat** | `sigoden_aichat` | CLI chat with embeddings + RAG built in. |
| **WikiChat** / **STORM** | `stanford-oval_WikiChat`, `stanford-oval_storm` | Grounded, citation-first retrieval + article generation. |
| **paper-search-mcp** | `openags_paper-search-mcp` | Academic search specialist (arXiv/SSRN/DOI) — if research sources matter. |

---

## Recommended pairing to actually build
**SearXNG (discover) → spider-den scraper (best Class-2/3 winner) → Meilisearch
(keyword) + Qdrant (semantic).** Race Jobs A/B/C separately, then wire the three
winners into the grand-final pipeline.
