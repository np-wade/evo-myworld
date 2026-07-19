# Queue — Codex
1. [x] Map the plugin internals: plugins/evo/hooks/, bin/, src/evo/, and how
   evo-drain / evo direct deliver messages. Write world/codex/internals-map.md
   (what fires when, host differences claude-code vs codex vs cursor).
2. [x] Identify the 3 cheapest extension points for adding a custom frontier
   strategy. Append findings to FIELD-NOTES.md.
3. [ ] PORT-PLAN.md Track A, deliverable A2 — RACE RULE applies (≥2 candidate schemas/patterns from searches, raced in the evo-hq harness before adoption): world/codex/assigner-bridge/ —
   Planner-JSON → evo run config + subagent briefs. Read
   /home/npwad/coding/docker-envs/projects/assembly-office/docs/HOW-ASSEMBLY-OFFICE-BUILDS-APPS.md first.
3. [ ] BRANCH BUILD (priority, from Nicholas 2026-07-19): build your seat's
   real SPACE in this app — world/codex/ becomes a working MODULE with genuine
   CONNECTIVITY to evo (a skill, hook, dashboard surface, gate, or CLI the app
   actually uses), not just documents. Then leave a bench experiment:
   world/codex/experiment.env (BASE_CMD = behaviour without your module,
   NEW_CMD = with it) per bench/BENCH.md, so the difference your module makes
   is visible on the bench each cycle. Exemplar: world/backend/ is a working
   module. Creative variants come LATER — right now: make it exist, make it
   run, show its difference on the bench.
