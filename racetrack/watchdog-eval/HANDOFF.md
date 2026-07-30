# HANDOFF — watchdog "page-change monitor" benchmark (evo HQ, Test 4)

**Updated:** 2026-07-26. **For:** the next AI picking this up.
**One-line:** Test 4 is BUILT AND GREEN end-to-end, fully offline: 12 frozen
page-version pairs with a known injection manifest (10 real changes + 23 churn
traps), a 10-combo diff race, and a stateful pipeline scoring F1 1.000 /
false-alarm 0.000 / localization 1.000 at 0.46ms per page (dom-diff/strip).

---

## 0. Cleanup status (read first)

- **Nothing running. No containers stood up, no ports opened** — this
  benchmark is 100% offline by design (the oracle trick is self-authored
  fixtures, so there is no network surface at all).
- Containers `phonectl-emu` and `kimi-cli` are Nicholas's PRE-EXISTING ones —
  untouched.
- `.venv/` is inert files only (uv, python 3.12, sole dep: beautifulsoup4 for
  the gated soup-diff candidate). Host `python3` also runs everything —
  soup-diff just SKIPS (gating verified both ways). Nothing committed to git.

## 1. Context

- Test 4 of the suite (`../scraper-search-lab/test-suite-plan.md`, "Test 4 —
  Watchdog"), built per the bench-factory recipe as a sibling of `arxiv-eval`.
- Seed task: "Watch these 12 pages; each run, report what changed since last
  run — what's new, what's gone, what moved."
- **ORACLE TRICK (strongest form): we author the truth.** `fixtures_gen.py`
  deterministically writes 12 realistic page pairs (pricing, blog index, docs,
  product grid, changelog, team, FAQ, status, news, jobs, terms, landing) as
  `fixtures/set1/{v1,v2}/` plus `manifest.json` — the answer key. Injected:
  - **10 real changes:** price edit, new blog post, reworded install note,
    product removed + added, changelog entry added, team member removed,
    refund answer reworded, past-incidents section deleted, headline edited.
  - **23 churn traps** (must be IGNORED): rotating timestamps ×6, build/session
    tokens ×5, view/signup/freshness counters ×4, reordered-but-identical
    lists ×3, ad-slot rotations ×3, cache-buster query strings ×2. Three pages
    (jobs, terms, landing) are churn-ONLY — the naive-watcher false-alarm bait.
- Two-track scoring: detection machinery hard-scored vs the manifest;
  change-summary readability advisory only. No LLM judge anywhere.

## 2. What happened this session (2026-07-26)

### Races run (results at repo root)
| Stage | Winner | Score | File |
|---|---|---|---|
| Diff race (10 combos) | **dom-diff/strip** (dom-diff/raw ties) | score 1.000 — F1 1.000, FAR 0.000, loc 1.000, 0.59ms/page | results-diff-run1.json |
| E2E pipeline | dom-diff/strip stateful watch | F1 1.000, FAR 0.000 (0/23 traps), loc 1.000, 10/10 real hits, 20 churn diffs suppressed, 0.46ms/page, 0.04s wall | pipeline-run1.json |

Full leaderboard (score = F1 × (1 − false-alarm-rate)):

| candidate | score | F1 | FAR | localization | p50/page |
|---|---|---|---|---|---|
| dom-diff/{raw,strip} | 1.000 | 1.000 | 0.000 | **1.000** | ~0.5ms |
| css-scope/{raw,strip} | 1.000 | 1.000 | 0.000 | 0.000 | ~0.2ms |
| line-diff/{raw,strip} | 1.000 | 1.000 | 0.000 | 0.000 | ~0.3ms |
| soup-diff/{raw,strip} | 0.783 | 1.000 | **0.217** | 1.000 | ~1.5ms |
| content-hash/{raw,strip} | 0.000 | 0.000 | **0.348** | 0.000 | ~0.02ms |

### Key discoveries
- **Localization is the separator, not recall.** Three families tie at
  score 1.000; only dom-diff also points at the right element (loc 1.000) —
  it wins the tiebreak and feeds the pipeline.
- **Full-subtree diffing leaks churn (soup-diff, FAR 0.217):** diffing an
  element's whole `get_text()` makes ancestor mega-blocks (main#content) mix a
  real edit with embedded counters/reorders — the blob is real-labeled, so the
  traps inside it count as flagged. Excluding nested-id content (dom-diff)
  fixes it. That FAR gap is exactly the toy-vs-tool metric the test wanted.
- **content-hash is the cautionary baseline:** notices every page (including
  the 3 churn-only pages → FAR 0.348) but can't say WHAT changed → F1 0.
- **Positional pairing inside difflib replace blocks mispairs shifted lines**
  (an insertion above a modified line paired "On-call…" with "Cutting…").
  Fixed with greedy best-similarity pairing (ratio ≥ .5) in
  `differs._pair_lines` — that took line-diff/css-scope from FAR 0.217/0.087
  and prec 0.61/0.85 to clean 1.000/0.000.
- The classify stage is generic (no manifest peeking): ad-class/"Sponsored"
  text, moved-with-identical-token-multiset, and changed-tokens-are-all-
  volatile (dates/times/hex/bare counters). Documented trade-off: an edit
  whose only delta is a bare unitless number is suppressed; prices ("$35/mo")
  and worded edits always survive.

### Code layout (all in `watchdog_eval/`)
- `fixtures_gen.py` — grader-side deterministic author of set1 + manifest.
- `oracle.py` — loads the manifest; scores detections: change-level P/R/F1,
  **false-alarm rate on churn traps**, localization. Page-level wildcards earn
  no recall; on churn-only pages they're false positives + flag the traps.
- `snapshot.py` — normalize race dimension: raw vs strip-volatile (comments/
  script/style/meta/hidden-inputs/cache-busters) + shared visible-text lines.
- `differs.py` — the raced stage: content-hash, line-diff (difflib +
  similarity pairing + moved detection), dom-diff (stdlib html.parser id-keyed
  tree, nested-id exclusion, reorder detection), css-scope
  (changedetection.io-style main/article/*content* regions), soup-diff
  (bs4-gated). Per-page AND per-candidate try/except everywhere.
- `classify.py` — shared real-vs-churn stage (generic heuristics only).
- `race.py` — 10-combo grid, score = F1×(1−FAR), rank ties by FAR→loc→p50.
- `pipeline.py` — STATEFUL seed task: run 1 persists baseline to
  `out/set1/state/`, run 2 diffs current pages against the store, emits
  report.{json,md} + changes.json + hard/advisory scorecard.
- `cli.py` — `list | selftest | gen-fixtures | diff-race | pipeline`.

## 3. Commands

```
cd ~/coding/docker-envs/projects/evo-myworld/racetrack/watchdog-eval
.venv/bin/python -m watchdog_eval list        # candidate matrix (10 combos)
.venv/bin/python -m watchdog_eval selftest    # OFFLINE green gate: oracle +
                                              # scoring math + dom-diff/strip
                                              # recovers the injected set
.venv/bin/python -m watchdog_eval gen-fixtures [--force]  # (grader) re-author
.venv/bin/python -m watchdog_eval diff-race --runs 3      # the race
.venv/bin/python -m watchdog_eval pipeline    # stateful E2E + scorecard
```
Plain `python3` works too (soup-diff skips — no pip on host; use
`~/.local/bin/uv` for any dep work).

## 4. NEXT steps (in order of value)

1. **Wire as an evo benchmark** (the point) — reuse scrapler-eval's metrics/
   gates/leaderboard/store like arxiv-eval plans to. Optimize surface: the
   classify heuristics (churn-token grammar), dom-diff block granularity,
   css-scope region selection, similarity-pairing threshold.
2. **Harden set2** — the ceiling is hit (three combos at 1.000), so mint a
   nastier fixture set: JS-rendered markup noise, attribute-only real changes
   (href swaps), a real change embedded in a reordered list, churn INSIDE a
   real-changed element, bigger pages. `fixtures_gen` is the template; keep
   set1 frozen as the regression gate.
3. **Live tier** — point the same differs at real snapshotted pages fetched
   via `arxiv-eval`-style backends (urllib/curl_cffi/scrapling) with a
   re-snapshot grader; only then does a fetch stage (and politeness) enter.
4. **Multi-run statefulness** — v1→v2→v3 chains to score "what changed since
   LAST run" (not since baseline) and alert dedup across runs.
5. Pull changedetection.io into the corpus as a candidate donor (its
   filter/selector logic maps onto css-scope + classify).

## 5. File locations

Package: `~/coding/docker-envs/projects/evo-myworld/racetrack/watchdog-eval/`
— `watchdog_eval/` (code), `fixtures/set1/{v1,v2,manifest.json}` (frozen
truth), `results-diff-run1.json`, `pipeline-run1.json`, `out/set1/`
(report.json, report.md, changes.json, state/ = the baseline store — the seed
task's actual deliverable). Suite plan: `../scraper-search-lab/
test-suite-plan.md`. Pattern source: `../arxiv-eval/HANDOFF.md`. Recipe:
`~/.claude/skills/bench-factory/SKILL.md`.
