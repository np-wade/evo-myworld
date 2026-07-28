# Racetrack results — the document-processing app test suite

Standing benchmark suite for the new document-processing app (prompt → report,
normal-scraping-only app path, arXiv-API-style privileged "oracle" as
grader-only truth). Each suite is a multi-stage race; winners chain into an
end-to-end `pipeline`. Two-track scoring: **machinery** is hard-scored vs gold
(what evo optimizes); **judgment** (picks/summaries) is advisory-only.

Built 2026-07-25/26. Visible-here index for the lab loop + dashboard.

| # | Suite | Situation proven | Package | Result card | Status |
|---|---|---|---|---|---|
| T1 | arXiv | exhaustive discovery vs throttling; long-doc PDF parse | `arxiv-eval/` | [arxiv-suite.md](arxiv-suite.md) | ✅ green, E2E |
| T2 | Substack | paginated/lazy archive crawl; paywall honesty; HTML→md | `substack-eval/` | [substack-suite.md](substack-suite.md) | ✅ green, E2E |
| T3 | Video | media→text (ASR); **stealth** across YouTube/Twitch/arbitrary | `video-eval/` | [video-suite.md](video-suite.md) | ✅ green, E2E |
| T4 | Watchdog | recurring diff/monitoring; signal-vs-churn | `watchdog-eval/` | [watchdog-suite.md](watchdog-suite.md) | ✅ green, offline |
| T5 | Crawl+Search | full-site crawl → index → query; browser-vs-fetcher + endurance | `crawl-eval/` | [crawl-suite.md](crawl-suite.md) | ✅ green, E2E |
| T6 | Information Processer | 8-stage pipeline races vs corpus competitors; self-authored oracle | `ip-eval/` | [ip-suite.md](ip-suite.md) | ✅ green, E2E |

**T5 (2026-07-27)** finally raced the unraced field — browser engines
(playwright, jsdom), the static fetchers head-to-head, and the search bracket
(bm25/tantivy) — against an AUTHORED internal site with planted traps (JS-nav
wall, robots, depth, dedup) + an endless procedural maze for endurance. Two
findings T1–T4 couldn't produce: (1) a browser only earns its ~340× latency cost
on JS-rendered content (js_recall 0→1); static backend choice is irrelevant to a
JS wall. (2) Endurance: plain urllib sustains ~477 pages/s vs a browser's ~1.5,
and stealth costs ~25% throughput. (3) Stealth: a **JA3-fingerprinting Tier-R
target** (`hardened.py`) blocks no-GREASE TLS — curl_cffi-impersonate + scrapling
beat it, plain urllib/curl are blocked; it's the impersonation, not the library.
Later hardened so nothing ties: 4 browser engines + jsdom (DOM-only, 0.667) + 4
search engines (qdrant 1.0 > meili 0.667 > bm25/tantivy 0.444 on a semantic/typo/
precision query set). Full stealth ladder built: JA3/TLS → HTTP/2 SETTINGS fingerprint (urllib can't do
h2; JA3 and h2 are independent layers a WAF cross-checks) → Cloudflare-style JS
challenge (only real browsers solve; stealth fetchers stall on JS, jsdom blocked
at JA3). Optimal = static-first, escalate to a TLS-impersonating fetcher on a JA3
wall and to a full real browser on JS/behavioral challenges. Original spec:
`../scraper-search-lab/HANDOFF-integration-and-T5.md`.

In-app: the evo dashboard's **Racetrack** page renders these suites + every
`results-*.json` leaderboard natively (`/api/racetrack` → `plugins/evo/src/evo/
racetrack.py`). Standalone fallback: `results/dashboard.html`.

Design docs: `../scraper-search-lab/test-suite-plan.md` (the 4-test rationale),
`../scraper-search-lab/arxiv-benchmark.md` (T1 detail). Factory skill to mint
more: `~/.claude/skills/bench-factory/SKILL.md` (`/bench-factory`).

## Next: wire into evo HQ
Each suite is `python3 -m <name>_eval pipeline` with a deterministic hard score.
To register as an evo benchmark: reuse `scrapler-eval` metrics/gates/leaderboard/
store; the optimize surface is the per-stage candidate swap (see each card's
"deferred contenders" — the eligible-but-unraced field is the first search
frontier).
