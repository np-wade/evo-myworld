# race: gate-regression
seat: hermes
question: which regression-gate delta shape (absolute-delta vs percentage-drop) gives the best detection/false-positive tradeoff on a single-scalar proxy score?
metric: max detection accuracy across planted 5/10/20% regressions, minus false-positive rate on a no-change child
gate: exit 0 iff at tolerance=0.05 the gate detects all three planted regressions and false-fires on 0 of 10 no-change children

## candidate: absolute-delta
source: /library/repos/zavora-ai_adk-rust/code/adk-eval/src/baseline.rs:116-154
approach: per-metric per-case signed delta. Load a baseline JSON (`HashMap<metric, HashMap<case_id, f64>>`); regression when `baseline_value - current_value > tolerance`. No baseline → graceful skip, not fail. Returns `Vec<Regression>`.

## candidate: percent-drop
source: /library/repos/repowise-dev_repowise/code/scripts/kg_validate/kg_checks.py:347-367
approach: per-language drop ratio. If baseline exists and `1.0 - (cur/prev) > DENSITY_REGRESSION_TOLERANCE`, emit a `Smell("FAIL", ...)`. Single scalar per dimension, percentage-based. Skips zero baselines.