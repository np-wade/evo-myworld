# result: watchdog-suite (T4)
seat: subagent (general-purpose) + watchdog-eval
question: detect what really changed between page versions, ignoring churn
metric: max — change F1; MIN false-alarm-rate on churn traps; max localization
gate: real changes not missed; churn not reported as change
oracle: self-authored injection manifest (WE own the truth) — 100% offline
package: watchdog-eval/  •  run: `python3 -m watchdog_eval pipeline`

Seed task: "Watch these 12 pages; each run report what changed since last run —
what's new, gone, moved." Stateful: run-1 persists a baseline; run-2 diffs it.

## Pipeline scorecard (out/set1/, dom-diff/strip)
HARD: F1 1.000, recall/precision 1.000, **false-alarm rate 0.000 (0/23 churn)**,
localization 1.000, real 10/10, 20 churn diffs suppressed, 0.46ms/page, 0.04s.
ADVISORY: 11 rows, snippet coverage 1.0.

## Diff race — full field  (results-diff-run1.json)
Score = F1 × (1 − false-alarm-rate). 12 page pairs: **10 real changes + 23
churn traps** (timestamps, tokens, counters, reordered-identical lists, ad
rotation, cache-busters); 3 pages are churn-only bait.
| candidate | score | F1 | FAR | localization | note |
|---|---|---|---|---|---|
| 🏆 **dom-diff** (strip/raw) | 1.000 | 1.000 | **0.000** | **1.000** | id-keyed element-tree diff |
| css-scope (strip/raw) | 1.000 | 1.000 | 0.000 | 0.000 | watch main-content regions only |
| line-diff (strip/raw) | 1.000 | 1.000 | 0.000 | 0.000 | difflib over visible text |
| ⚔️ soup-diff (strip/raw) | 0.783 | 1.000 | 0.217 (5/23) | 1.000 | bs4 full-subtree text — churn leaks in |
| ⚔️ content-hash (raw/strip) | 0.000 | 0.000 | 0.348 (8/23) | 0.000 | sha256 page-level — the cautionary baseline |

Localization is the separator at the top of the board (dom-diff points at the
exact element; css/line-diff find the change but not where). soup-diff shows the
designed toy-vs-tool gap: full-subtree blobs leak embedded churn. content-hash
is useless (any byte change trips it).
- ⏳ deferred: css-selector-scoped per-site watch config (changedetection.io
  style); a harder set2 (three combos hit the set1 ceiling).

## Files
Package `watchdog-eval/watchdog_eval/*.py`; results
`watchdog-eval/results-diff-run1.json` + `pipeline-run1.json`; deliverable
`watchdog-eval/out/set1/` (report.json/md, changes.json, state/); fixtures
`watchdog-eval/fixtures/set1/{v1,v2,manifest.json}` (12 page pairs); handoff
`watchdog-eval/HANDOFF.md`.

## Notes
Fully offline + deterministic; runs on bare host python3 (soup-diff cleanly
skips without bs4, proving available()-gating). Real bug fixed mid-race:
difflib positional pairing mispaired shifted lines → greedy best-similarity
pairing took line-diff/css-scope FAR 0.217/0.087 → 0.000. Top evo frontier: a
harder fixture set2 to break the current ceiling.
