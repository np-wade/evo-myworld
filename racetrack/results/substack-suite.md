# result: substack-suite (T2)
seat: subagent (general-purpose) + substack-eval
question: pull a newsletter's recent archive as clean markdown, by normal scraping
metric: max — post-set F1 vs RSS/API oracle; HTML→md fidelity vs RSS full-content
gate: PAYWALL HONESTY — a paywalled post must be flagged truncated, never
      padded/fabricated (instant hard-fail)
oracle: Substack RSS /feed + JSON /api/v1/archive — GRADER ONLY
package: substack-eval/  •  run: `python3 -m substack_eval pipeline`

Seed task: "Find every post from <pub>.substack.com in the last 60 days; save
the 10 most recent as clean markdown; deliver a table + files."

## Pipeline scorecard (out/<pub>/, pinned ref_date 2026-07-26) — gate_all PASS
| pub | disc F1 | recall | recent10 | fidelity | gate | paid handling |
|---|---|---|---|---|---|---|
| thezvi | 1.000 | 1.000 | 10/10 | 0.944 | PASS | 0 paid |
| astralcodexten | 0.957 | 1.000 | 8/10 | 0.975 | PASS | 5 paid → 1 delivered |
| noahpinion | 0.810 | 1.000 | 7/10 | 0.973 | PASS | 10 paid → 2 delivered |
date/author/url accuracy 1.000 everywhere; 10/10 md files + sha256 per pub.

## Stage races — full field

### Stage 1 Discover  (results-discover-run1.json)
- 🏆 **sitemap** (parse /sitemap.xml) — F1 0.927, **recall 1.000**, prec 0.874,
  ~100ms. Backend-agnostic.
- ⚔️ ran, lost: **archive-html** static scrape — recall only 0.318 (prec 0.972).
  This IS the lazy-load thesis: the archive page renders ~12–20 posts then
  needs JS scroll. → a headless scroller is the clear next candidate.
- ⚔️ ran, lost: ddg-serp/* — 0 after the date-window filter (finds slugs but
  exposes no dates to filter on).
- ⏳ deferred (gated OFF): bing-serp/* (risky).

### Stage 2 Extract (HTML→markdown)  (results-extract-run1.json)
- 🏆 **trafilatura** — fidelity 0.968 / title 0.980 @ 38ms (51 posts).
- ⚔️ ran, lost: readability (0.919), css-rules baseline (0.881 but 6.9ms, 5×
  faster — the speed/quality floor).

### Stage 3 Fetch  (results-fetch-run1.json)
- 🏆 **curl_cffi** — p50 113ms. All three backends post/fields/paywall-detect
  = 1.00, 0 blocks. scrapling 115ms, urllib 146ms.

## Paywall-honesty gate — verified
NeMo-gate style, deterministic. Honest truncation passes; fabricated
full-content and padded (~full-length) paid deliveries both hard-FAIL in
selftest. One real false-positive fixed in bring-up (measure fabrication vs the
full article word_count, not the near-empty RSS preview).

## Files
Package `substack-eval/substack_eval/*.py`; results `substack-eval/results-*.json`
+ `pipeline-run1.json`; deliverables `substack-eval/out/{thezvi,astralcodexten,
noahpinion}/`; fixtures `substack-eval/fixtures/<pub>/` (gold.json + RSS + 30
post HTMLs each); handoff `substack-eval/HANDOFF.md`.

## Notes
`platformer` rejected (left Substack in 2024) → replaced with `thezvi`. No
blocks anywhere (block_rate 0.00). Top evo frontier: headless-scroll discovery
candidate; noahpinion precision dip traces to sitemap lastmod surfacing edited
old slugs.
