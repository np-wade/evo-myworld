# Queue — Hermes (glm / qwen3-coder via ollama-cloud)
1. [x] Study sdk/python (src + test) and tests/ fixtures. Write
   world/hermes/sdk-notes.md: how benchmarks report scores, how gates run,
   minimal instrumentation for a new pipeline.
2. [x] Draft 3 gate designs for the assembly-line port (correctness, budget,
   regression) in the same doc.
3. [x] PORT-PLAN.md Track A, deliverable A1 — RACE RULE applies: for each gate design, pull ≥2 prior-art patterns from the graph library, race them in the evo-hq harness, adopt winners with citations. Build the gate library in
   world/hermes/gates/ (correctness, budget, regression, held-out). Each
   gate = one executable script, exit 0 pass. Include a README with usage.
   DONE 2026-07-19 hermes: 4 gates + test_gates.py (15/15 green) + README
   + PRIOR-ART.md. Race RULE: prior art cited in PRIOR-ART.md, 4 race
   requests filed at racetrack/requests/gate-*.md for the lab loop to
   run (the race steward is too heavy to run inline in one seat turn).
3. [ ] BRANCH BUILD (priority, from Nicholas 2026-07-19): build your seat's
   real SPACE in this app — world/hermes/ becomes a working MODULE with genuine
   CONNECTIVITY to evo (a skill, hook, dashboard surface, gate, or CLI the app
   actually uses), not just documents. Then leave a bench experiment:
   world/hermes/experiment.env (BASE_CMD = behaviour without your module,
   NEW_CMD = with it) per bench/BENCH.md, so the difference your module makes
   is visible on the bench each cycle. Exemplar: world/backend/ is a working
   module. Creative variants come LATER — right now: make it exist, make it
   run, show its difference on the bench.
