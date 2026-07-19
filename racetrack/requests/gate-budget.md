# race: gate-budget
seat: hermes
question: which budget-gate shape (ratchet-%-vs-baseline or absolute-cap) catches spend regressions best on a 12GB WSL box under swap pressure?
metric: min false-positive rate over 20 synthetic budget.json runs where 18 are under-budget and 2 are spiked
gate: exit 0 iff the gate flags exactly the 2 spiked runs and passes all 18 under-budget runs

## candidate: ratchet
source: /library/repos/diegosouzapw_OmniRoute/code/open-sse/services/compression/harness/budgetGate.ts:46-62
approach: per-task ratchet. Compute mean compressed tokens per task group, compare each task's current mean to a frozen baseline, fail when `deltaPercent > tolerancePercent` (default 2%). Falling cost always passes. Returns `{passed, regressions[], tolerancePercent}`.

## candidate: absolute-cap
source: /library/repos/EverMind-AI_raven/code/raven/eval_engine/hooks/before_iteration_hook.py:41-73
approach: crude byte/4 token estimate of messages list; if estimate exceeds `config.max_iteration_tokens`, short-circuit the iteration with a synthetic halt. Rough estimator, no baseline — "above this number = fail."