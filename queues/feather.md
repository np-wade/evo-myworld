# Queue — Featherless (deepseek-V4-Flash — 35k CONTEXT CAP, keep inputs small;
# step-3.7-Flash for quick passes)
1. [x] One file at a time (respect the 35k cap): summarize each of
   plugins/evo/agents/*.md and plugins/evo/skills/subagent/ into
   world/feather/digests.md (one tight paragraph per file).
2. [x] Build world/feather/file-inventory.md: annotated tree of plugins/evo
    (one line per file: what it is, size).
3. [ ] BRANCH BUILD (priority, from Nicholas 2026-07-19): build your seat's
   real SPACE in this app — world/feather/ becomes a working module with genuine
   CONNECTIVITY to evo (a skill, hook, dashboard surface, gate, or CLI the
   app actually uses), not just documents. REQUIRED: declare
   world/feather/judge.env per harness/HARNESS.md (VERIFY_CMD must exercise your
   thing for real; SCORE_CMD gives a true number). The judge runs every
   cycle; your row in harness/LEDGER.md is your heartbeat. Exemplar:
   world/backend/ (works=OK, scored). Creative variants come LATER — right
   now: make it exist, make it run, make it judged.
