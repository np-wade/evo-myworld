# Queue — Hermes (glm / qwen3-coder via ollama-cloud)
1. [ ] Study sdk/python (src + test) and tests/ fixtures. Write
   world/hermes/sdk-notes.md: how benchmarks report scores, how gates run,
   minimal instrumentation for a new pipeline.
2. [ ] Draft 3 gate designs for the assembly-line port (correctness, budget,
   regression) in the same doc.
3. [ ] PORT-PLAN.md Track A, deliverable A1: build the gate library in
   world/hermes/gates/ (correctness, budget, regression, held-out). Each
   gate = one executable script, exit 0 pass. Include a README with usage.
