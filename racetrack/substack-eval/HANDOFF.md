# HANDOFF — Substack "archive crawl" benchmark (evo HQ, Test 2)

**Updated:** 2026-07-26. **For:** the next AI picking this up.
**One-line:** The full prompt→report pipeline RUNS END-TO-END and is scored
across 3 real newsletters. `python -m substack_eval pipeline --pub all` (≈20s
& 12 requests per pub) delivers 10 clean-markdown files/pub with a table +
sha256 manifest; discovery recall 1.000 everywhere; the **paywall-honesty gate
passes on honest output and fires on fabrication** (proven in selftest).

---

## 0. Cleanup status (read first)

- **Nothing of mine is running. No ports opened, no containers stood up.**
  Substack needs no SearXNG/headless infra — nothing to tear down.
- Containers `phonectl-emu` and `kimi-cli` are Nicholas's PRE-EXISTING ones —
  untouched. arxiv-eval sibling package — untouched.
- `.venv/` is inert files only. Nothing committed to git this session.
- Fixtures (`fixtures/`, 32 MB) are frozen; `fetch_fixtures.py` is grader-only
  and re-runnable (skips existing).

## 1. Context

- Seed task: "Find every post from `<newsletter>.substack.com` published in the
  last 60 days; save the 10 most recent as clean markdown; deliver a table +
  files."
- **HARD RULE:** app path = NORMAL SCRAPING ONLY (archive HTML page,
  sitemap.xml, SERP). Substack's **RSS `/feed` and JSON `/api/v1/archive` are
  GRADER-ONLY** (oracle + fetch_fixtures). The app never touches them.
- **Pinned window:** the 60-day window is frozen at `ref_date=2026-07-26`
  (→ window_start `2026-05-27`), recorded in each `fixtures/<pub>/meta.json`.
  The scored path NEVER calls a live `now()`.
- Design spec: `../scraper-search-lab/test-suite-plan.md` ("Test 2 — Substack").
- Pattern copied from the arxiv-eval sibling (oracle trick, stage races,
  two-track scoring, available()-gated backends).

### Newsletters chosen (all verified live, none blocked)
| pub | base (custom domain) | window gold | paid-in-window |
|---|---|---|---|
| thezvi | thezvi.substack.com | 45 | 0 (all free) |
| astralcodexten | www.astralcodexten.com | 33 | 5 |
| noahpinion | www.noahpinion.blog | 34 | 10 |

`platformer` was rejected — its archive is frozen at 2024 (left Substack).
`astralcodexten`/`noahpinion` are Substack pubs on custom domains
(`<pub>.substack.com` 301s there; backends follow redirects). No blocks
observed on ANY surface (block rate 0.00 across all races).

## 2. Results

### Stage races (results-*.json at repo root)
| Stage | Winner | Key numbers | File |
|---|---|---|---|
| Discover | **sitemap** (any backend) | F1 0.927, **recall 1.000**, prec 0.874 | results-discover-run1.json |
| Extract | **trafilatura** | fidelity 0.968, title-acc 0.980, 30ms | results-extract-run1.json |
| Fetch | curl_cffi (all 3 perfect) | post/fields/paywall = 1.00, p50 113ms | results-fetch-run1.json |

**Discover leaderboard** (window gold thezvi=45 / acx=33 / noah=34, 2 runs):
```
candidate          brkt      F1  recall   prec  rawF1  found  p50ms  block
sitemap/scrapling  sitemap 0.927  1.000  0.874  0.056     45   99.8   0.00
sitemap/curl_cffi  sitemap 0.927  1.000  0.874  0.056     45  100.5   0.00
sitemap/urllib     sitemap 0.927  1.000  0.874  0.056     45  185.4   0.00
archive-html/*     archive 0.477  0.318  0.972  0.477     12  ~120    0.00
ddg-serp/*         serp    0.000  0.000  0.000  0.16       0  ~660    0.00
```
- **The lazy-load thesis is confirmed.** The static `/archive` page yields only
  ~12 posts (recall 0.318) — a headless scroller is the obvious next candidate
  and would be the first real headless win in the suite. `sitemap.xml` beats it
  outright (full history + `<lastmod>` in 1 request, recall 1.000).
- Sitemap precision 0.874 = `<lastmod>` of edited-old posts (and duplicate slug
  variants like `book-review-power-and-progress` vs gold `-874`) leaking into
  the window. Real, honest noise — the top precision/ordering evo target.
- **SERP (ddg) scores 0 after the date-window filter**: it finds some `/p/`
  slugs (rawF1 0.16) but exposes NO dates, so date-window drops them — exactly
  as it should for an exhaustive task. `bing-serp` gated behind
  `SUBSTACK_EVAL_RISKY=1`.

**Extract leaderboard** (51 free fixture posts, fidelity = token-Dice vs RSS):
```
extractor     fid-mean  fid-med  title  p50ms  fails
trafilatura      0.968    0.978  0.980   30.2      0
readability      0.919    0.932  0.902   36.9      0
css-rules        0.881    0.892  0.980    4.1      0
```
css-rules (stdlib baseline) is 7x faster and ties on titles; trafilatura wins
body fidelity. Both always-available.

### End-to-end pipeline scorecard (pipeline-run1.json; sitemap+archive
discover → date-window → curl_cffi fetch → trafilatura extract → md+manifest)
| pub | disc F1 | recall | prec | recent10 | title | date/auth/url | fidelity | **gate** | paid | req | wall |
|---|---|---|---|---|---|---|---|---|---|---|---|
| thezvi | 1.000 | 1.000 | 1.000 | 10/10 | 1.000 | 1.0/1.0/1.0 | 0.944 | **PASS** | 0 | 12 | 20.0s |
| astralcodexten | 0.957 | 1.000 | 0.917 | 8/10 | 0.875 | 1.0/1.0/1.0 | 0.975 | **PASS** | 1 | 12 | 19.2s |
| noahpinion | 0.810 | 1.000 | 0.680 | 7/10 | 1.000 | 1.0/1.0/1.0 | 0.973 | **PASS** | 2 | 12 | 19.1s |

- Every pub: **recall 1.000, 10/10 markdown saved, all paid posts flagged
  `truncated` with `(paywalled — free preview only)` and NEVER padded.**
- `recent10 8/10, 7/10` misses = date granularity: the app orders by day
  (sitemap `<lastmod>` / archive `<time>`), gold orders by exact `post_date`;
  same-day boundary swaps + leaked slug variants displace 2-3. Prefer archive
  `<time>` over sitemap `<lastmod>` and dedupe slug variants → top evo target.
- Advisory pick-3-about-AI: 3/3 pool overlap on all pubs (never hard-scored).

### PAYWALL HONESTY GATE — works
- **Hard-scored, deterministic, NeMo-gate style (one violation = FAIL).** Two
  prongs per gold-paid delivered post: (1) MUST be flagged `truncated`;
  (2) MUST NOT reproduce ≥90% of the true article (gold `word_count`) — i.e.
  can't output the whole paywalled piece an honest truncated fetch never held.
- Honest pipeline output **PASSES** all 3 pubs (paid posts get only their real
  on-page free lede — noahpinion legitimately serves ~40%, which passes).
- **Selftest proves it FIRES**: a fabricated full-content paid delivery
  (truncated flag dropped) and a padded delivery (flagged but ~full length)
  both FAIL; the honest short lede and all free posts PASS.
- Design note: the 90% floor came from a real false-positive during bring-up —
  an early `1.5×RSS-preview` rule failed ACX's paid post (RSS preview 9 chars,
  on-page free lede 156 chars). The fix: measure fabrication against the FULL
  article length, not the near-empty RSS preview. See `oracle.paywall_gate`.

## 3. Commands

```
cd ~/coding/docker-envs/projects/evo-myworld/racetrack/substack-eval
.venv/bin/python -m substack_eval list           # backends/candidates/pubs
.venv/bin/python -m substack_eval selftest       # OFFLINE green (gate proof)
.venv/bin/python -m substack_eval extract-race   # OFFLINE (fixture HTML)
.venv/bin/python -m substack_eval discover-race --runs 2   # LIVE, polite
.venv/bin/python -m substack_eval fetch-race     # LIVE
.venv/bin/python -m substack_eval pipeline --pub all       # END-TO-END + scorecard
# rebuild/extend fixtures (GRADER-ONLY, re-runnable, skips existing):
python3 fetch_fixtures.py [pub]
```
venv: `~/.local/bin/uv venv .venv --python 3.12` then
`uv pip install --python .venv/bin/python curl_cffi scrapling trafilatura
readability-lxml lxml playwright browserforge` (scrapling needs the last two
to import — same bite as arxiv-eval). Host python3 has NO pip; always use uv.
Politeness: every network race sleeps 1.5-2s between fetches.

## 4. NEXT steps (in order of value)

1. **Wire as an evo benchmark** — the point. Reuse scrapler-eval's
   metrics/gates/leaderboard/store (sibling dir). Optimize surface: discover
   date-source (archive `<time>` > sitemap `<lastmod>`) + slug-variant dedup
   (fixes precision 0.68→~0.95 and recent10), extractor choice, backend.
2. **Headless-scroll discover candidate** — a Playwright/scrapling dynamic
   fetcher that scrolls `/archive` past the lazy-load boundary. This is the
   suite's first genuine static-vs-headless showdown; today static archive =
   recall 0.318, sitemap already = 1.000, so the headless bar is "beat sitemap
   precision," not recall.
3. **LLM extractor candidate (advisory + gate stress-test)** — a BAML/LLM
   HTML→md extractor is the realistic fabrication risk; run it THROUGH the
   paywall gate to prove the gate catches a real hallucinating extractor.
4. **Field-accuracy edge**: ACX title-acc 0.875 = one HTML-entity/em-dash
   normalization miss in `extract_fields`; tighten `norm_text` or JSON-LD path.
5. Add a 4th high-volume pub if recall robustness needs more spread.

## 5. File locations

```
substack-eval/
  fetch_fixtures.py                 # GRADER-ONLY fixture builder (RSS+API)
  fixtures/<pub>/                   # frozen gold (3 pubs, 32MB)
    meta.json                       # pinned ref_date + 60-day window
    gold.json                       # definitive post list (API truth)
    feed.xml, rss/<slug>.html       # RSS full-content gold (fidelity)
    html/<slug>.html                # 30 saved post pages (extract-race corpus)
  substack_eval/
    oracle.py       # gold load, P/R/F1, field acc, fidelity, PAYWALL GATE
    fetchers.py     # urllib/curl_cffi/scrapling, available()-gated, redirects
    discover.py     # ArchiveHtmlScrape / SitemapScrape / SerpScrape candidates
    filter.py       # date-window (pinned) filter candidates
    fetch_stage.py  # stage-3 backend race (post/fields/paywall-detect)
    extract_stage.py# HTML->md race: css-rules/readability/trafilatura + gate helpers
    race.py         # discovery race (N runs, p50/p95, per-cand try/except)
    pipeline.py     # end-to-end seed task + score_pipeline (hard+advisory)
    cli.py          # list|selftest|discover-race|fetch-race|extract-race|pipeline
  results-discover-run1.json, results-extract-run1.json, results-fetch-run1.json
  pipeline-run1.json                # the scorecard above
  out/<pub>/                        # THE DELIVERABLE: report.{json,md} + md/ + manifest
```
Design spec: `../scraper-search-lab/test-suite-plan.md`. Memory:
`scraper-search-lab`.
