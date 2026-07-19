# Queue — Gemini (3.x via Antigravity, both accounts available)
1. [x] Architecture review of the whole repo (top-down). Write
   world/gemini/arch-review.md: module boundaries, coupling, what breaks
   first under our 12GB-RAM WSL constraint, what to touch/not touch.
2. [x] Review CHARTER.md program order — risks & sequencing advice, append
   to FIELD-NOTES.md.
3. [x] LIBRARY EXPLORATION (auto-refill 2026-07-19): explore these
   corpus repos (at /library/repos/<name> in lanes, ~/coding/docker-envs/filing-cabinet/library-base/repos on host):
   - AlexisLspk__neuronbox
   - EverMind-AI__HyperMem
   - EverMind-AI__MSA
   Find ONE capability done notably well (or notably differently) across
   ≥2 of them (or 1 of them + 1 graph-library slice). Then FILE A RACE:
   write racetrack/requests/<slug>.md per racetrack/RACETRACK.md, with
   real citations. Also append 2-3 findings to FIELD-NOTES.md (signed).
   Small benchmarks only. If the repos are unsuitable, say why in
   FIELD-NOTES and tick this item anyway.
5. [x] BRANCH BUILD (priority, from Nicholas 2026-07-19): build your seat's
   real SPACE in this app — world/gemini/ becomes a working module with genuine
   CONNECTIVITY to evo (a skill, hook, dashboard surface, gate, or CLI the
   app actually uses), not just documents. REQUIRED: declare
   world/gemini/judge.env per harness/HARNESS.md (VERIFY_CMD must exercise your
   thing for real; SCORE_CMD gives a true number). The judge runs every
   cycle; your row in harness/LEDGER.md is your heartbeat. Exemplar:
   world/backend/ (works=OK, scored). Creative variants come LATER — right
   now: make it exist, make it run, make it judged.
6. [ ] FIX (selfdev 2026-07-19): your judge.env FAILS every cycle
   (harness/logs/gemini.154441.log): VERIFY_CMD runs pytest via
   `uv run --no-project`, an isolated env where world/gemini/test_ucb.py's
   `from evo import frontier_strategies` hits ModuleNotFoundError — the
   package lives at plugins/evo/src/evo/, never on that env's path.
   Fix world/gemini/judge.env only: put PYTHONPATH=plugins/evo/src in front
   of the pytest and SCORE_CMD invocations (or use uv's --with-editable
   plugins/evo). Then run VERIFY_CMD yourself from the repo root and only
   tick this when it exits 0. Exemplar of a passing setup: world/backend/judge.env.
