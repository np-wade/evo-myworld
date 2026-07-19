# Kimi seat — front-end ideas for evo-myworld

> Read first: `/projects/evo-myworld/FIELD-NOTES.md` and `/projects/evo-hq/README.md`.  
> Constraint from the orchestrator: KEEP IT SMALL until the assembly-line port + backend land. These are wild, low-code-cost concepts — not a build plan.

## 1. Campfire command room
Instead of a sterile metrics table, the dashboard feels like a shared lab den. Each AI seat is a glowing presence around a central fire. Active experiments are sparks that drift upward; the current frontier is the hottest point. The vibe is "many minds working on the same object," which matches evo's parallel-subagent model (`README.md` / `FIELD-NOTES.md`). Implementation would stay inside the existing Flask + `static/app.js` shell (`FIELD-NOTES.md`) and use a lightweight SVG layer, not a heavy SPA framework.

## 2. Experiment tree as a time-river
Render `.evo/<active-run>/graph.json` (`FIELD-NOTES.md`) as a horizontal river: the root is upstream, winning branches flow wider and brighter, dead branches fade into sediment. Color encodes score heat; thickness hints at memory/CPU budget. This makes the tree-search concept from `README.md` immediately readable — you can *see* the search explore, fork, and cull.

## 3. Agent-presence orbit
Each seat (kimi, claude, codex, cursor, gemini, hermes, poe, feather) orbits the current frontier as a distinct glyph. Hovering a glyph shows that seat's latest `FIELD-NOTES.md` entry and the branch it is working on. It turns concurrency from an invisible background process into a social, spatial signal — useful when the lab is deliberately capping parallel agents to 2 because of WSL RAM limits (`FIELD-NOTES.md` gotchas).

## 4. Graph-first prior-art lens
A split-pane lens for the `GRAPH-FIRST` rule (`CHARTER.md`): code on the left, related graph-library slices (`TOPICS.md → slices → source`) on the right as a browsable constellation. When a subagent is forming a hypothesis, the UI surfaces prior art nodes ranked by relevance. This front-end supports the lab's culling discipline by making "at least 2 candidate implementations" visible before anyone writes code.

## 5. Lab-bench instrument panel
Replace abstract config with tactile metaphors: toggle switches for frontier strategies (`argmax`, `top_k`, `epsilon_greedy`, `softmax`, `pareto_per_task` — `README.md`), LED-style gate pass/fail indicators, and a memory gauge pinned to the 12 GB RAM + 24 GB swap ceiling (`FIELD-NOTES.md`). The dashboard should feel like hardware on the bench, not a cloud dashboard, reinforcing that this world runs on a real, resource-limited machine.

---
*Next step (after assembly port + backend): pick one idea, prototype it against the existing Flask dashboard, and race it against a plain table baseline.*
