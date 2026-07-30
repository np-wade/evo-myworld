# arXiv benchmark — "prompt → report" (evo HQ end-to-end test)

Status: **STAGES 1-4 RACED LIVE + END-TO-END PIPELINE RUNNING (2026-07-26).**
Created 2026-07-25. Supersedes the parse-only race idea for the first test.

### As-built (updated 2026-07-26)
- Harness: `racetrack/arxiv-eval/` — `python3 -m arxiv_eval
  list|selftest|race|filter-race|fetch-race|parse-race|pipeline`.
- Oracle gold: `fixtures/2026-07-14/` — listing.json (**243 papers**, discovery
  gold), pool.json (18 local-AI candidates), **18/18 PDFs** + 18 LaTeX sources +
  18 gold-field files. Built via arXiv API (grader only; NOT the app path).
- **Stage 1 raced (results-run1.json):** the 429 wall from 7-25 is GONE —
  list-month passes with every backend (block 0.00). Pagination fix took recall
  0.638→1.000 (show=2000 truncates; now paginated). SERP bracket is useless for
  exhaustive discovery (≤11 IDs, 0 precision; DDG blocks curl_cffi but not
  urllib). SearXNG stood up + JSON API verified, same result — serp bracket is
  for needle queries, not full-day sweeps.
- **Stage 2 raced (results-filter-run1.json):** month UI has NO per-day
  headings, so announce-day filters can't run. Winner: **abs-bisect** — arXiv
  IDs are submission-time-sequential, so the day is a contiguous ID band;
  binary-search /abs/ pages finds it in ~22 fetches. **F1 0.900** (rec .926,
  prec .875) vs 0.080 passthrough. Band-edge noise is the residual — an
  edge-scan refinement is the obvious evo candidate.
- **Stage 3 raced (results-fetch-run1.json):** all 3 backends 5/5 on abs+PDF,
  byte-exact vs fixtures, 0 blocks. scrapling fastest (p50 129ms). Only listing
  pages get throttled ("Rate exceeded." 200-body — fetchers now flag it blocked).
- **Stage 4 raced (results-parse-run1.json, offline):** **pymupdf** wins —
  heading-recall 0.972 (ties pdfminer) at 46ms/paper, 13× faster. pypdf 0.931.
  OCR heavyweights (olmocr/MinerU/rust-paddle-ocr) not yet slotted in.
- **End-to-end `pipeline` cmd built:** discover→abs-bisect→pick-5(advisory
  keyword rubric)→fetch 5 PDFs→pymupdf parse→report.{json,md}+manifest(sha256),
  scored hard (machinery) + advisory (pick-5 pool overlap).

## What the app is (the thing this test proves works)

A document-processing app you drive with **a single prompt** and get back a
**report**. For arXiv, the report is:

1. a **table of every paper** matching the prompt's criteria (metadata rows), and
2. **saved files** of the papers that match — the PDF + a clean markdown/JSON
   version of each — for later reading.
3. (optional) a short synthesized summary over the matched set.

So the end-to-end is: **prompt → discover → filter by criteria → fetch → process
→ transform → report (table + saved files).** Each stage is a toggleable module
pulled assembly-line from the corpus; evo swaps candidates and keeps the winner.

## Why arXiv makes this scorable (the ground-truth trick)

Open-ended "find me papers about X" has no fixed answer. So we **scope the test
prompts to queries arXiv can answer definitively**, and use two gold sources:

- **Discovery / table gold = arXiv API.** A prompt like *"list every cs.LG paper
  submitted in the first week of Jan 2025 whose abstract mentions 'mixture of
  experts'"* maps to one deterministic arXiv API query. The API's result set IS
  the correct table. → score discovery by **precision / recall of returned IDs**,
  and table correctness by exact field match (title, authors, date, categories).
- **Per-paper field gold = LaTeX e-print source.** arXiv ships each paper's `.tex`
  source. Parse it once to get exact section headings, equation count, table
  count, bibliography — the gold for scoring how well the PDF→markdown parse and
  the structured extraction did. Abstract/authors come from the API.

Result: an end-to-end flow that's **deterministic and offline-reproducible**, no
LLM judge in the scored path. (A summary, if we include it, is advisory-only.)

## HARD RULE — normal scraping only (Nicholas, 2026-07-25)

The app under test must reach arXiv the **normal web way**: search engines +
scraping HTML listing/abstract/PDF pages. **NO arXiv API in the app path** —
API-based "special scrapes" are a later app feature, not the tested behavior.

The arXiv API is used in exactly ONE place: the **grader's oracle** that builds
the answer key (the true full-day list + per-paper gold). The grader is allowed
privileged truth; the app is not. This cleanly separates "what's correct" from
"how the app found it."

## Pipeline stages (candidates to race, from candidates-expanded.md)

| Stage | Job | Candidates raced (normal scraping) |
|---|---|---|
| 1 **Discover** | prompt → paper URLs | **SearXNG · Google-SERP-scrape · Bing-SERP-scrape · DuckDuckGo-scrape · arxiv.org/list HTML scrape · browser-search · HeadlessX** |
| 2 Filter | apply criteria (date/cat/kw) | rule filter (baseline) · llm_extract criteria-match |
| 3 Fetch | download abstract page + PDF | curl-impersonate · Scrapling-static · stealth-browser |
| 4 Parse | PDF → clean markdown | olmocr · MinerU · rust-paddle-ocr · pdftotext (baseline) |
| 5 Extract | markdown → structured fields | BAML · llm_extract · css/rule |
| 6 Report | table + saved files (+summary) | JSON/CSV table · tabiew view · Meili/Qdrant index |

evo's job: swap stage candidates, score against the oracle gold, commit the best.

## THE headline "intense" race — the discovery bracket

Stage 1 is where the intensity goes: **which discovery path pulls the full
2026-07-14 arXiv set fastest and most completely, by normal scraping?**
Each candidate is scored on:

- **speed** — wall-clock to assemble the candidate URL list (p50/p95 over runs)
- **completeness / recall** — fraction of the day's true papers found (vs oracle)
- **precision** — fraction of returned URLs that are real arXiv papers of that day
- **cost / robustness** — bytes+requests, block rate, variance across retries

This is the "which search engine pulls arXiv fastest" question, run as a real
head-to-head with an answer key. Winner feeds the rest of the pipeline.

## Scoring rubric (blended, reuses scrapler-eval metrics/gates/leaderboard)

- **Discovery**: precision/recall of paper IDs vs the API's definitive set.
- **Table**: per-field exact/fuzzy accuracy (title, authors, date, categories).
- **Saved files**: did it save exactly the papers meeting criteria? (set match)
- **Parse fidelity**: section-heading recall, equation-count Δ, table-count Δ vs LaTeX.
- **Extract**: field accuracy vs API+LaTeX gold.
- **Cost/latency**: normalized, as in the existing ladder field_stats.
- Gates (NeMo-Guardrails-derived): no fabricated papers, no missing-file claims.

## THE seed task (Nicholas, finalized 2026-07-25)

> "List all arXiv papers published on **2026-07-14**. Pick the **5 titles most
> beneficial to building a local AI system**. Save those PDFs to my device and
> deliver them to me."

This splits into a **deterministic half** and a **judgment half** — they must be
scored differently:

- **Deterministic (hard-scored vs gold):**
  - *Discovery completeness* — did it retrieve the COMPLETE 2026-07-14 listing?
    Gold = arXiv API listing for that date (precision/recall of IDs). This is the
    full day (hundreds–thousands of rows) — metadata only, cheap to freeze.
  - *Per-paper fields* — title/authors/date/categories exact vs API; parse
    fidelity (sections/equations) vs LaTeX for the 5 saved papers.
  - *Save + deliver mechanics* — were exactly the 5 chosen PDFs downloaded to the
    output dir, non-corrupt, and listed in a delivery manifest?
- **Judgment (soft-scored, NOT in the deterministic path):**
  - *"5 most beneficial to a local AI system"* is subjective — no arXiv gold
    exists. Scored by a **relevance rubric** (on-device inference, quantization,
    small/edge models, local serving, RAG, efficient training) via an LLM-judge
    OR keyword-relevance proxy. Reported as an ADVISORY sub-score so it never
    corrupts the deterministic leaderboard evo optimizes on.

This is the honest reconciliation: evo optimizes the *machinery* (find-all →
extract → save → deliver) on hard gold; the *pick-5* quality is tracked
separately so a lucky/unlucky selection can't move the real score.

## Frozen fixture set (start SMALL)

For 2026-07-14 freeze: `listing.json` = the full day's API metadata (discovery
gold, all IDs). Then a **candidate pool** of ~15–20 local-AI-relevant papers from
that day gets `abs.json` + `source.tex` + `paper.pdf` each, so the app has real
PDFs to pick-and-save from and we can hard-score the 5 it lands on. Derive
`expected_fields.json` per paper. All under
`scrapler-eval/scrapler_eval/fixtures/arxiv/2026-07-14/`. Live tier (a fresh
date, scored via a fresh API call) can come later.

## What actually runs when Nicholas says go

1. Build the 5-paper fixture set (needs one network fetch to arXiv API + e-print).
2. Add adapters for stages 1/4/5 candidates (available()-gated like the rest).
3. Register an `arxiv` tier in `ladder.json` + a report-scoring metric.
4. `python3 -m scrapler_eval race --tier arxiv` for the local leaderboard, then
   wire it as an evo benchmark for the optimize loop.

**Nothing above is built yet — holding for approval of this design.**
