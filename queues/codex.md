# Queue — Codex
1. [x] Map the plugin internals: plugins/evo/hooks/, bin/, src/evo/, and how
   evo-drain / evo direct deliver messages. Write world/codex/internals-map.md
   (what fires when, host differences claude-code vs codex vs cursor).
2. [ ] Identify the 3 cheapest extension points for adding a custom frontier
   strategy. Append findings to FIELD-NOTES.md.
3. [ ] PORT-PLAN.md Track A, deliverable A2 — RACE RULE applies (≥2 candidate schemas/patterns from searches, raced in the evo-hq harness before adoption): world/codex/assigner-bridge/ —
   Planner-JSON → evo run config + subagent briefs. Read
   /home/npwad/coding/docker-envs/projects/assembly-office/docs/HOW-ASSEMBLY-OFFICE-BUILDS-APPS.md first.
4. [ ] BRANCH BUILD (priority, from Nicholas 2026-07-19): build your seat's
   real SPACE in this app — world/codex/ becomes a working module with genuine
   CONNECTIVITY to evo (a skill, hook, dashboard surface, gate, or CLI the
   app actually uses), not just documents. REQUIRED: declare
   world/codex/judge.env per harness/HARNESS.md (VERIFY_CMD must exercise your
   thing for real; SCORE_CMD gives a true number). The judge runs every
   cycle; your row in harness/LEDGER.md is your heartbeat. Exemplar:
   world/backend/ (works=OK, scored). Creative variants come LATER — right
   now: make it exist, make it run, make it judged.
