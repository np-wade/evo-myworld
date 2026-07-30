# result: arxiv-suite (T1)
seat: claude (main) + arxiv-eval
question: prompt → report over a full day of arXiv, by normal scraping only
metric: max — discovery F1 vs the API oracle; parse fidelity vs LaTeX gold
gate: no fabricated papers; saved PDFs non-corrupt + in manifest
oracle: arXiv API (full-day listing) + LaTeX e-print sources — GRADER ONLY
package: arxiv-eval/  •  run: `python3 -m arxiv_eval pipeline`

Seed task: "List all arXiv papers published 2026-07-14; pick the 5 most
beneficial to a local AI system; save the PDFs; deliver."

## Pipeline scorecard (out/2026-07-14/)
HARD: discovery F1 0.900 (recall 0.926 / prec 0.876, 257 found vs 243 gold),
title accuracy 0.991, save 5/5, parse 5/5, 34 requests, 55.2s.
ADVISORY: pick-5 pool overlap 4/5.

## Stage races — full field

### Stage 1 Discover  (results-run1.json)
- 🏆 **list-month** (listing scrape) — recall 1.000 after pagination fix
  (raw race showed 0.638 pre-fix; truncation was the cause).
- ⚔️ ran, lost: searxng/* (found ≤11, precision 0), ddg-serp/* (0–3 found;
  ddg blocks curl_cffi at 100% but not urllib — notable), all SERP = wrong
  tool for exhaustive discovery.
- ⏳ deferred (available()-gated OFF): google-serp/*, bing-serp/* (risky flag
  `ARXIV_EVAL_RISKY=1`); scrapling initially errored (browserforge dep) then
  fixed. Not-yet-built: browser-search, HeadlessX.

### Stage 2 Filter  (results-filter-run1.json)
- 🏆 **abs-bisect** — F1 0.900 in 22 fetches. Insight: arXiv IDs are
  submission-sequential → target day is a contiguous ID band; binary-search
  /abs/ pages to find its edges.
- ⚔️ ran, lost: passthrough / annc-d0 / annc-d1 / annc-d1d2 — all F1 0.080
  (the new month UI dropped per-day headings, so announce-day set-ops can't
  fire). Kept for sources that still expose day headings.

### Stage 3 Fetch  (results-fetch-run1.json)
- 🏆 **scrapling** — p50 129ms. All three backends 5/5 byte-exact PDFs, 0 blocks.
- ⚔️ close: curl_cffi (142ms), urllib (246ms) — same perfect accuracy.

### Stage 4 Parse  (results-parse-run1.json)
- 🏆 **pymupdf** — heading-recall 0.972 @ 46ms/paper.
- ⚔️ ran, lost: pdfminer (0.972 but 623ms, 13× slower), pypdf (0.931).
- ⏳ deferred: OCR heavyweights **olmocr / MinerU / rust-paddle-ocr**
  (docker/GPU) — unlock equation/table-count metrics the text baselines can't.

## Files
Package `arxiv-eval/arxiv_eval/*.py`; results `arxiv-eval/results-*.json` +
`pipeline-run1.json`; deliverable `arxiv-eval/out/2026-07-14/`; fixtures
`arxiv-eval/fixtures/2026-07-14/` (243-paper gold + 18-paper pool, 18/18 PDFs +
LaTeX + gold fields); handoff `arxiv-eval/HANDOFF.md`.

## Graduates
Winning chain: list-month → abs-bisect → scrapling fetch → pymupdf parse.
Top evo frontier: abs-bisect edge-scan (recover ~7% band-edge recall); OCR
parse candidates; a real stage-5 extract race.
