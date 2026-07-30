# The 4-Test Suite — proving the document-processing app across situations

Proposed 2026-07-26. Status: **DESIGN — awaiting Nicholas's sign-off per test.**
Test 1 (arXiv) is BUILT and green; this plan generalizes what made it work into
three more tests, each covering a *situation* the app will really face that
arXiv doesn't touch. All follow the same shape (the "oracle trick" — see
`bench-factory` skill): a privileged truth channel the app is FORBIDDEN to use
grades a normal-scraping app path, deterministically, no LLM judge in the
scored lane.

## What made Test 1 work (the reusable pattern)

1. **One prompt in → one report out** (table + saved files + manifest).
2. **Oracle trick:** arXiv API + LaTeX sources = grader-only gold.
3. **Stage grid**, each stage raced with available()-gated candidates.
4. **Two-track scoring:** machinery hard-scored vs gold (what evo optimizes);
   judgment calls advisory-only.
5. **Frozen fixtures** → offline-reproducible; live tier optional later.

## Situation coverage map (why these four)

| Situation | T1 arXiv | T2 Substack | T3 Video | T4 Watchdog |
|---|---|---|---|---|
| Exhaustive discovery vs throttling | ✔ | | | |
| Paginated/lazy archive crawling | ✔ | ✔ | | |
| Paywall/partial-content honesty | | ✔ | | |
| Media → text transform (ASR) | | | ✔ | |
| Long-doc parse fidelity (PDF/OCR) | ✔ | | | |
| HTML → clean markdown | | ✔ | | |
| Recurring diff/monitoring | | | | ✔ |
| Noise vs signal discrimination | | | | ✔ |
| Delivery mechanics (save+manifest) | ✔ | ✔ | ✔ | ✔ |

---

## Test 2 — Substack / newsletter pull ("the archive crawl")

**Seed prompt:** "Find every post `<newsletter>.substack.com` published in the
last 60 days; save the 10 most recent as clean markdown; deliver a table +
files."

- **Oracle trick (grader-only):** Substack's RSS (`/feed`) + JSON archive API
  (`/api/v1/archive?sort=new`) give the definitive post list with dates,
  titles, authors, paywall flags. App path = HTML archive pages / sitemap /
  SERP only — API+RSS forbidden.
- **Stage grid:** discover (archive-scroll scrape vs sitemap.xml vs SERP) →
  filter (date window) → fetch (backend race, JS-render question: archive is
  lazy-loaded → first real test for a headless-browser candidate vs static) →
  extract (HTML→md race: trafilatura vs readability vs css-rules — adapters
  already exist in scrapler-eval) → report.
- **Hard score:** post-set P/R/F1 vs API gold; field accuracy (title/date/
  author/url); content fidelity (normalized text similarity vs RSS full-content
  for free posts); **paywall honesty gate** — a paywalled post must be marked
  truncated, never padded/fabricated (NeMo-gate style, instant fail).
- **Advisory:** "pick the 3 best posts about X" relevance.
- **Fixtures:** freeze 2-3 newsletters (one free, one mixed-paywall, one
  high-volume) — archive JSON + RSS + saved HTML of ~30 posts.
- **New muscle tested:** lazy-load pagination, paywall honesty, HTML→md.

## Test 3 — Video → transcript ("the transform test")

**Seed prompt:** "Get me the transcript of `<talk URL>`; produce a clean
timestamped transcript + a table of sections/topics; save transcript.md."

- **Oracle trick (grader-only):** pick ~10 videos WITH creator-uploaded
  captions (conference talks are reliable). Official captions = gold,
  pulled grader-side once and frozen. App must produce its own transcript.
- **Stage grid:** resolve/fetch media (yt-dlp — corpus `yt-dlp_yt-dlp`) →
  transcribe RACE: (a) auto-caption scrape, (b) local ASR on downloaded audio
  (corpus `ufal_whisper_streaming`; faster-whisper worth pulling into corpus),
  (c) page-transcript scrape when the host shows one → segment/clean →
  report.
- **Hard score:** WER/CER vs gold captions; timestamp drift (median |Δ| per
  aligned segment); wall-clock + CPU cost (this is the local-AI angle — can a
  local box transcribe a 30-min talk in reasonable time?); save mechanics.
- **Advisory:** section/topic table quality.
- **Fixtures:** frozen audio files + gold captions → the ASR race is fully
  OFFLINE and rerunnable; only the fetch stage needs network.
- **New muscle tested:** media handling, the "transform" leg of the app
  (documents in one modality → another), local-compute budgeting.

## Test 4 — Watchdog / page-change monitor ("the Datadog play")

Nicholas has wanted this separately (memory: page-change monitor, "a play on
Datadog"). As a benchmark it is the cleanest of all four because WE author the
truth.

**Seed prompt:** "Watch these 12 pages; each run, report what changed since
last run — what's new, what's gone, what moved."

- **Oracle trick:** no external gold needed — freeze page-version pairs
  (v1, v2) with KNOWN injected changes: price edits, new article added,
  section removed, reworded paragraph, plus **cosmetic churn traps**
  (timestamps, session tokens, rotating ads, reordered but identical lists).
  The injection manifest IS the answer key. 100% offline, perfectly
  deterministic.
- **Stage grid:** snapshot (fetch+normalize) → diff RACE: content-hash
  baseline vs text-diff vs DOM-structural diff vs css-selector-scoped watch
  (changedetection.io approach — needs pulling into corpus; `obsei` +
  `koala73_worldmonitor` are in-corpus adjacents) → classify (real change vs
  churn) → report (change table + before/after snippets).
- **Hard score:** change detection P/R per injected change; **false-alarm rate
  on churn traps** (the metric that separates toys from tools); diff
  localization accuracy (did it point at the right element); latency per page.
- **Advisory:** change-summary readability.
- **New muscle tested:** statefulness (memory between runs), signal-vs-noise
  discrimination, recurring-job mechanics — the app's "monitoring" product leg.

---

## Also still missing INSIDE Test 1 (stage gaps, from HANDOFF)

- Stage 5 extract race (BAML / llm_extract vs the css/rule baseline).
- OCR heavyweights for stage 4 (olmocr / MinerU / rust-paddle-ocr) — unlock
  equation/table-count metrics.
- abs-bisect edge-scan (recover the ~7% band-edge recall).
- Index/search stage (Meili vs tantivy vs qdrant over the report corpus) —
  turns the report into a queryable library (search Jobs B/C from the lab).
- Live tier (a fresh date graded by a fresh grader-side API call).

## Rollout proposal

1. Sign off test designs (this doc) — edit/veto per test.
2. Build order: **T4 watchdog first** (fully offline, fastest to green, and
   it's the product leg Nicholas already wants), then **T2 Substack**, then
   **T3 video** (heaviest deps).
3. Each build = `bench-factory` skill run: scaffold → oracle build → selftest
   → stage races → pipeline → wire into evo HQ.
4. End state: 4 benchmarks × evo optimize loops, one shared leaderboard store
   (scrapler-eval core), the app assembled from per-stage winners.
