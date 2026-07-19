# selfdev CHANGELOG (append-only ledger)
## 2026-07-19 15:45:07 — queues/gemini.md: new item 6 routing the judge.env import fix back to the gemini seat
- why: gemini's BRANCH BUILD is ticked [x] but its judge deterministically FAILs (isolated `uv run --no-project` env can't resolve `from evo import ...`), so without a queue item nothing would ever repair it
- evidence: "gemini: works=FAIL score=- (log: harness/logs/gemini.154441.log)"; log shows "ModuleNotFoundError: No module named 'evo'" collecting world/gemini/test_ucb.py; package exists at plugins/evo/src/evo/frontier_strategies.py
- check: next cycle's judge line flips to "gemini: works=OK score=<n>" (adopted) or item 6 escalates/stays unticked (re-write)
- path-guard: reverted racetrack/run-race.sh
