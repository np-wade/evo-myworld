# Queue — Poe (qwen3.7-max agent-capable; minimax m3-t for chat/review)
1. [ ] Read plugins/evo/skills/discover/ and skills/optimize/. Write
   world/poe/skills-digest.md: exact flow, prompts, state files each skill
   touches — the operator's manual for the rest of the lab.
2. [ ] Copyedit CHARTER.md + FIELD-NOTES.md for clarity (suggest, don't
   rewrite core meaning) — append suggestions to FIELD-NOTES.md.
3. [ ] BRANCH BUILD (priority, from Nicholas 2026-07-19): build your seat's
   real SPACE in this app — world/poe/ becomes a working MODULE with genuine
   CONNECTIVITY to evo (a skill, hook, dashboard surface, gate, or CLI the app
   actually uses), not just documents. Then leave a bench experiment:
   world/poe/experiment.env (BASE_CMD = behaviour without your module,
   NEW_CMD = with it) per bench/BENCH.md, so the difference your module makes
   is visible on the bench each cycle. Exemplar: world/backend/ is a working
   module. Creative variants come LATER — right now: make it exist, make it
   run, show its difference on the bench.
