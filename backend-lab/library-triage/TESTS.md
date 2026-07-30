# TESTS — library-triage (to build later)

Tests are numbered in build order. Budgets assume the 12GB RAM box; all fixtures
synthetic and <10MB (racetrack rule: seconds not minutes, `racetrack/RACETRACK.md:34`).

## 1. Signal-extraction correctness on fixture repos
- What: build 5 fixture repos with planted properties (one cited in a fake
  STAGE-style doc, one in a fake race request, one in a tiny fixture index.db
  with known degree sums, one "ported" via a fake SOURCES.md, one orphaned).
  Run each signal extractor from `CANDIDATES.md` against the fixtures.
- Metric: max |extracted_value − expected_value| across all fixture×signal cells.
- Gate: exact match on every cell; a signal that cannot see a fixture repo must
  report "no data", never 0-as-absence.
- Fixture: `fixtures/repos/{cited,raced,graphed,ported,orphan}_repo` + fixture copies
  of the provenance docs / index.db (SQLite, generated, <1MB).
- Budget: <60s end-to-end.

## 2. Ranker determinism
- What: run the winning blend/UCB1 ranker twice over the same frozen signal table.
- Metric: Kendall tau between run 1 and run 2 orderings (and set equality of the
  cull list).
- Gate: tau == 1.0 and identical cull sets; any RNG must be seeded and the seed
  recorded in the output header (pattern: `world/gemini/ucb.py` takes `rng`).
- Fixture: frozen signal table from test 1 (JSON, <100KB).
- Budget: <30s.

## 3. No-sole-weak-signal gate
- What: any repo whose keep score rests on exactly one *weak* signal
  (weak = catalog-cross-listing or last-touch alone; strong = provenance ref,
  race citation, graph reachability, graduated port) must land on a
  human-review list, never directly on keep.
- Metric: max precision of the flagger; recall over planted cases must be 1.0.
- Gate: 100% recall on 6 planted sole-weak-signal repos in the fixture; zero
  repos reach the keep list on one weak signal.
- Fixture: signal table with planted sole-weak rows (derived from test 1 fixture).
- Budget: <30s.

## 4. Leaderboard reproducibility from cache
- What: rebuild the full triage leaderboard from the cached signal table with
  extractors disabled (no filesystem, no index.db access).
- Metric: sha256 of rendered leaderboard.
- Gate: byte-identical output across two runs on different working directories;
  run must not open `graphify-app/data/index.db` or the library (assert via
  strace/access log or an access-guard shim).
- Fixture: cached signal table JSON (<1MB).
- Budget: <30s.

## 5. Cull-list dry-run safety (quarantine never deletes)
- What: run the cull pipeline in dry-run on the fixture library, then in
  "apply" mode against a throwaway copy.
- Metric: max number of bytes deleted (target 0); every culled path must be a
  `mv` into the quarantine dir, logged with before/after path.
- Gate: zero `unlink`/`rm` syscalls; 100% of culled items reappear under the
  quarantine dir (pattern: `graphify-app/src/config.js:12` QUARANTINE_DIR,
  indexed as first-class by `graphify-app/src/search/indexer.js:20-30`);
  quarantine dir is created if absent (it does not exist on disk today).
- Fixture: 20 dummy repo dirs (<10MB total) with a planted cull set.
- Budget: <60s.

## 6. Coverage — all 616 repos scored
- What: run the full extraction+ranking pass over the real library.
- Metric: min coverage fraction = scored_repos / 616; plus per-repo
  signals_attempted count.
- Gate: 616/616 rows in the output table; every row has signals_attempted ≥ 1
  and an explicit score or an explicit "no-signal" marker (never silently
  dropped); repos whose index.db `repos.status != 'ok'` (quarantined/failed
  graphs) must appear as named rows, not missing rows. Live DB measured to
  cover all 616 repos (2026-07-27) — the "597 repos" docstring at
  `world/backend/evo_graph.py:8` is stale and must not be asserted.
- Fixture: the real library + real index.db (read-only, `mode=ro` pattern at
  `world/backend/evo_graph.py:65`).
- Budget: <10 min wall, <4GB RSS (12GB box).
