# Queue — Poe (qwen3.7-max agent-capable; minimax m3-t for chat/review)
1. [ ] Read plugins/evo/skills/discover/ and skills/optimize/. Write
   world/poe/skills-digest.md: exact flow, prompts, state files each skill
   touches — the operator's manual for the rest of the lab.
2. [ ] Copyedit CHARTER.md + FIELD-NOTES.md for clarity (suggest, don't
   rewrite core meaning) — append suggestions to FIELD-NOTES.md.
3. [ ] BRANCH BUILD (priority, from Nicholas 2026-07-19): build your seat's
   real SPACE in this app — world/poe/ becomes a working module with genuine
   CONNECTIVITY to evo (a skill, hook, dashboard surface, gate, or CLI the
   app actually uses), not just documents. REQUIRED: declare
   world/poe/judge.env per harness/HARNESS.md (VERIFY_CMD must exercise your
   thing for real; SCORE_CMD gives a true number). The judge runs every
   cycle; your row in harness/LEDGER.md is your heartbeat. Exemplar:
   world/backend/ (works=OK, scored). Creative variants come LATER — right
   now: make it exist, make it run, make it judged.
