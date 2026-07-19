# Queue — Hermes (glm / qwen3-coder via ollama-cloud)
1. [x] Study sdk/python (src + test) and tests/ fixtures. Write
   world/hermes/sdk-notes.md: how benchmarks report scores, how gates run,
   minimal instrumentation for a new pipeline.
2. [x] Draft 3 gate designs for the assembly-line port (correctness, budget,
   regression) in the same doc.
3. [ ] PORT-PLAN.md Track A, deliverable A1 — RACE RULE applies: for each gate design, pull ≥2 prior-art patterns from the graph library, race them in the evo-hq harness, adopt winners with citations. Build the gate library in
   world/hermes/gates/ (correctness, budget, regression, held-out). Each
   gate = one executable script, exit 0 pass. Include a README with usage.
4. [ ] BRANCH BUILD (priority, from Nicholas 2026-07-19): build your seat's
   real SPACE in this app — world/hermes/ becomes a working module with genuine
   CONNECTIVITY to evo (a skill, hook, dashboard surface, gate, or CLI the
   app actually uses), not just documents. REQUIRED: declare
   world/hermes/judge.env per harness/HARNESS.md (VERIFY_CMD must exercise your
   thing for real; SCORE_CMD gives a true number). The judge runs every
   cycle; your row in harness/LEDGER.md is your heartbeat. Exemplar:
   world/backend/ (works=OK, scored). Creative variants come LATER — right
   now: make it exist, make it run, make it judged.
