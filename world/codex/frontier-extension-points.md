# Three cheapest custom-frontier extension points

Date: 2026-07-19  
Seat: Codex

## 1. Add one in-process picker at the registry/dispatch seam

The cheapest code extension is entirely inside
`plugins/evo/src/evo/frontier_strategies.py`: add one declarative entry to
`FRONTIER_STRATEGIES`, implement a picker with the existing
`(nodes, params, metric, outcomes, rng) -> ranked summaries` contract, and map
it in `PICKERS`. `validate_frontier_strategy()` supplies defaults and bounds;
`pick()` owns validation, deterministic RNG injection, dispatch, and rank
renumbering. This avoids changes to CLI parsing, persistence, and consumers.

Cost: one strategy function, one registry specification, one dispatch-map
entry, plus focused tests.

## 2. Use the existing config/override seam

Custom strategy selection already travels as
`{"kind": "...", "params": {...}}`. Persist it under `frontier_strategy` in
`.evo/config.json`, set it through the existing dashboard endpoint, or override
it for one call with `evo frontier --strategy ... --params ...`. The default is
also a single constant, `DEFAULT_FRONTIER_STRATEGY`. A new strategy therefore
needs no new config schema, command, migration, or dashboard form: the
dashboard gets its labels, descriptions, and parameter controls from the same
registry.

Cost: zero new transport/UI code after extension point 1.

## 3. Reuse `pick()` as the single consumer boundary

The CLI (`cmd_frontier`), dashboard (`/api/frontier`), and generated scratchpad
all resolve config and call the same `frontier_strategies.pick()` function.
Keeping a custom strategy behind this boundary makes it visible in all three
surfaces automatically. A score-only strategy can use the normalized node
summaries immediately. A task-aware strategy can consume the already-supported
`outcomes` mapping; only a genuinely new data dependency would justify adding
loader plumbing at each consumer.

Cost: zero consumer edits for score-based strategies; small, duplicated loader
edits only if the strategy requires data beyond nodes and outcomes.

## Recommendation

Start with a pure picker registered in `frontier_strategies.py`, select it via
the existing JSON config, and test it through `pick()` with a fixed seed. Do
not begin at the CLI, dashboard JavaScript, or scratchpad: those are already
downstream of the shared seam.

## Files read

- `/workspace/evo-myworld/CHARTER.md`
- Last 150 lines of `/workspace/evo-myworld/FIELD-NOTES.md`
- `/workspace/evo-myworld/queues/codex.md`
- `/workspace/evo-myworld/world/codex/internals-map.md` (search hit only)
- `/workspace/evo-myworld/plugins/evo/src/evo/frontier_strategies.py`
- `/workspace/evo-myworld/plugins/evo/src/evo/cli.py` (frontier command section)
- `/workspace/evo-myworld/plugins/evo/src/evo/dashboard.py` (frontier routes)
- `/workspace/evo-myworld/plugins/evo/src/evo/scratchpad.py` (frontier ranking helper)
