# HANDOFF — arXiv "prompt → report" benchmark (evo HQ)

**Updated:** 2026-07-26. **For:** the next AI picking this up.
**One-line:** The full prompt→report pipeline now RUNS END-TO-END and is scored:
stages 1-4 raced live, winners chained into `python -m arxiv_eval pipeline`
(55s, 34 requests, discovery F1 0.900, 5/5 PDFs saved+parsed, pick-5 4/5).

---

## 0. Cleanup status (read first)

- **Nothing of mine is running. No ports open.** The SearXNG container
  (`searxng-arxiveval`) was stood up on :8888, raced, and **removed** with
  `docker rm -f`. Its config survives at `searxng-config/settings.yml`; restart:
  `docker run -d --name searxng-arxiveval -p 8888:8080 -v "$PWD/searxng-config:/etc/searxng" searxng/searxng:latest`
  then `export SEARXNG_URL=http://localhost:8888`.
- Containers `phonectl-emu` and `kimi-cli` are Nicholas's PRE-EXISTING ones.
- `.venv/` is inert files only. Nothing committed to git this session.

## 1. Context (unchanged)

- `bh` is dead; this benchmark tests the NEW document-processing app in evo HQ.
- Seed task: "List all arXiv papers published 2026-07-14; pick the 5 most
  beneficial to building a local AI system; save the PDFs; deliver."
- **HARD RULE:** app path = normal scraping only. arXiv API is grader-only.
- Design doc (updated with all results): `../scraper-search-lab/arxiv-benchmark.md`.

## 2. What happened this session (2026-07-26)

### Races run (results in `results-*.json` at repo root)
| Stage | Winner | Score | File |
|---|---|---|---|
| 1 Discover | list-month (any backend) | recall 1.000 after pagination fix | results-run1.json |
| 2 Filter | **abs-bisect** | F1 0.900 (rec .926 / prec .875), 22 fetches | results-filter-run1.json |
| 3 Fetch | scrapling (all 3 perfect) | 5/5 abs+PDF byte-exact, p50 129ms | results-fetch-run1.json |
| 4 Parse | **pymupdf** | heading-recall 0.972 @ 46ms/paper | results-parse-run1.json |
| E2E | pipeline cmd | F1 .900, title-acc .991, save 5/5, parse 5/5, pick-5 4/5, 55s/34 req | pipeline-run1.json |

### Key discoveries
- **The 7-25 blocking picture INVERTED:** arxiv.org/list no longer 429s naive
  urllib (block rate 0.00 everywhere). Throttling is intermittent and comes as
  HTTP-200 **"Rate exceeded."** bodies — `fetchers._blocked()` now detects this.
- **show=2000 truncates** big categories → pagination added to ListingScrape
  (recall 0.638→1.000). Month scrape = ~12 requests, ~30s.
- **New arXiv month UI has NO per-day headings** → announce-day filters can't
  work. Replacement insight: **arXiv IDs are submission-time-sequential**, so a
  day = contiguous ID band → `abs-bisect` binary-searches /abs/ pages (~22
  fetches for a 5.8k-ID month). Residual error is band-edge noise (ID order ≈
  submission order, not exactly) — **edge-scan refinement is the top evo
  candidate**.
- SERP bracket (ddg/searxng) is useless for exhaustive discovery (≤11 IDs,
  0 precision) — it's for needle queries. DDG blocks curl_cffi but not urllib.
- scrapling needed `playwright` + `browserforge` pips to even import (installed).
- Missing PDF 2607.12599 re-fetched → fixtures now **18/18 complete**.

### Code added (all in `arxiv_eval/`)
- `filter.py` — stage 2: FilterCandidate (announce-day set-ops, kept for sources
  with day headings) + **AbsBisect** (offline-tested with a fake backend:
  exact band in 16 probes vs 300 brute) + `filter-race` cmd.
- `fetch_stage.py` — stage 3 race: abs-ok/pdf-valid/pdf-exact(sha256 vs
  fixture)/block/p50 per backend + `fetch-race` cmd. FetchOut grew a raw
  `content: bytes` field for binary targets.
- `parse_stage.py` — stage 4 race (OFFLINE, fixture PDFs): pymupdf/pdfminer/
  pypdf, scored on gold section-heading recall + `parse-race` cmd.
- `discover.py` — pagination, day-heading parser (dormant on new UI), and
  `_entries_from` listing-metadata scrape (id→title/authors → free table rows).
- `pipeline.py` — end-to-end seed task + `score_pipeline` (hard track vs gold,
  advisory pick-5 pool overlap) + `pipeline` cmd. Output: `out/2026-07-14/`
  (report.json, report.md, pdf/, md/, sha256 manifest).
- `race.py` — per-candidate try/except so one broken candidate can't kill a race.

## 3. Commands

```
cd ~/coding/docker-envs/projects/evo-myworld/racetrack/arxiv-eval
.venv/bin/python -m arxiv_eval list          # candidate matrix
.venv/bin/python -m arxiv_eval selftest      # offline green
.venv/bin/python -m arxiv_eval race --runs 5 # stage-1 discovery race
.venv/bin/python -m arxiv_eval filter-race --runs 1   # stage-2 (network, polite)
.venv/bin/python -m arxiv_eval fetch-race    # stage-3 (network)
.venv/bin/python -m arxiv_eval parse-race    # stage-4 (offline)
.venv/bin/python -m arxiv_eval pipeline      # END-TO-END seed task + scorecard
```
Politeness: listing pages are the throttled surface — keep filter-race/pipeline
runs spaced out; the harness sleeps 1.5-2s between fetches already.

## 4. NEXT steps (in order of value)

1. **Wire as an evo benchmark** — this is the whole point. Reuse scrapler-eval's
   metrics/gates/leaderboard/store (sibling dir). The optimize surface: filter
   band edge-scan, pick-5 rubric, parse candidates, backend choice per stage.
2. **Stage 5 extract** — currently only listing-meta (title/authors, title-acc
   .991). Add abstract/categories extraction from saved abs pages or parsed md,
   scored vs gold; BAML/llm_extract candidates from the corpus.
3. **OCR heavyweights for stage 4** — olmocr / MinerU / rust-paddle-ocr behind
   the same Parser interface (docker/GPU scale; corpus repos verified present).
   They unlock equation/table-count metrics the text baselines can't touch.
4. **abs-bisect edge-scan** — recover the ~7% band-edge recall loss.
5. **Risky engines** (`ARXIV_EVAL_RISKY=1`) + day-URL probe
   (`arxiv.org/list/cs.LG/2026-07-14` — returned "Rate exceeded." when tried;
   unknown if the day-path even exists in the new UI).
6. Advisory relevance rubric beyond keywords (LLM-judge, advisory-only).

## 5. File locations

Same as before, plus: `results-{run1,filter-run1,fetch-run1,parse-run1}.json`,
`pipeline-run1.json`, `out/2026-07-14/` (the actual deliverable of the seed
task), `searxng-config/settings.yml`. Design doc updated:
`../scraper-search-lab/arxiv-benchmark.md`. Memory: `scraper-search-lab`.

`uv` note still applies: host python3 has no pip; use `~/.local/bin/uv`.
