# EverMind Raven Live Research Notes

These notes capture the findings from executing and analyzing key components of the **EverMind AI Raven** self-evolution and evaluation engines (`raven/eval_engine` and `raven/evolver`).

---

## 1. What was Run

We constructed a Python test script ([run_probes.py](file:///workspace/evo-myworld/world/gemini/run_probes.py)) in the local environment that imports and exercises several modular components from the Raven repository:
1. **`BeforeIterationHook`** ([before_iteration_hook.py](file:///library/repos/EverMind-AI_raven/code/raven/eval_engine/hooks/before_iteration_hook.py#L25)): A pruning gate that performs a crude character-length token estimation (`len(json.dumps(messages)) // 4`) and halts the conversation early if the budget is exceeded.
2. **`ToolAuditHook`** ([tool_audit_hook.py](file:///library/repos/EverMind-AI_raven/code/raven/eval_engine/hooks/tool_audit_hook.py#L26)): A deterministic safety filter that blocks specific tool calls specified in a denylist config before they execute.
3. **`compute_stability`** ([stability_bucket.py](file:///library/repos/EverMind-AI_raven/code/raven/evolver/analysis/stability_bucket.py#L117)): An evolver routine that aggregates $k$-attempt outcomes per task across directories and groups tasks into stability buckets (`stable_pass`, `borderline_2_3`, `borderline_1_3`, `stable_fail`).
4. **`extract_features`** ([proxy_features.py](file:///library/repos/EverMind-AI_raven/code/raven/evolver/analysis/proxy_features.py#L186)): An evolver routine that walks `result.json` and `session.jsonl` files to compute cheap, numeric metadata features (turn count, assistant message length averages, final exit status, docker-error occurrences).
5. **`build_trial_pool`** ([trial_pool.py](file:///library/repos/EverMind-AI_raven/code/raven/evolver/analysis/trial_pool.py#L71)): An evolver adapter that constructs unified `Trial` objects containing stability categories and numerical feature dictionaries prepared for K-means clustering.

---

## 2. Actual Outputs Pasted

The output printed by running the test runner against constructed toy trials and inputs:

```text
=== TESTING EVAL ENGINE HOOKS ===
BeforeIterationHook (under budget): pass_through=True, short_circuit_result=None, notes=[]
BeforeIterationHook (over budget): pass_through=True, short_circuit_result=I've hit the conversation token budget for this turn. Let me know if you'd like me to summarize or start fresh., notes=['token_budget_exceeded estimate=167']
ToolAuditHook (safe tools): pass_through=True, short_circuit_result=None, notes=[]
EvalEngine tool audit: blocking tool calls ['rm_rf']
ToolAuditHook (unsafe tools): pass_through=True, short_circuit_result=I tried to invoke a tool that's been blocked by policy: rm_rf. Please rephrase or escalate if you believe this is intended., notes=["tool_denylist_hit names=['rm_rf']"]

=== TESTING EVOLVER ANALYSIS MODULES ===
Task Stability Results:
  Task: task_a, Attempts: 3, Passes: 3, Bucket: stable_pass
  Task: task_b, Attempts: 3, Passes: 1, Bucket: borderline_1_3
Bucket Counts:
  stable_pass: 1
  borderline_2_3: 0
  borderline_1_3: 1
  stable_fail: 0

Proxy Features for task_b__attempt3:
  Trial ID: task_b__attempt3
  Task ID: task_b
  Turn Count: 10
  Final Exit Status: agent_timeout
  Has Tool Calls: True
  Assistant Text Length Avg: 15.0
  Docker Error Count: 2

Unified Trial Pool Objects:
  Trial ID: task_a__attempt1, Task ID: task_a, Attempt: 1, Passed: True, Stability: stable_pass, Proxy Features: {'turn_count': 2.0, 'has_tool_calls_ever': 1.0, 'assistant_text_length_avg': 15.0, 'docker_error_count': 0.0, 'exit_status_ordinal': 0.0}
  Trial ID: task_a__attempt2, Task ID: task_a, Attempt: 2, Passed: True, Stability: stable_pass, Proxy Features: {'turn_count': 3.0, 'has_tool_calls_ever': 1.0, 'assistant_text_length_avg': 15.0, 'docker_error_count': 0.0, 'exit_status_ordinal': 0.0}
  Trial ID: task_a__attempt3, Task ID: task_a, Attempt: 3, Passed: True, Stability: stable_pass, Proxy Features: {'turn_count': 2.0, 'has_tool_calls_ever': 1.0, 'assistant_text_length_avg': 15.0, 'docker_error_count': 0.0, 'exit_status_ordinal': 0.0}
  Trial ID: task_b__attempt1, Task ID: task_b, Attempt: 1, Passed: False, Stability: borderline_1_3, Proxy Features: {'turn_count': 5.0, 'has_tool_calls_ever': 1.0, 'assistant_text_length_avg': 15.0, 'docker_error_count': 0.0, 'exit_status_ordinal': 1.0}
  Trial ID: task_b__attempt2, Task ID: task_b, Attempt: 2, Passed: True, Stability: borderline_1_3, Proxy Features: {'turn_count': 4.0, 'has_tool_calls_ever': 1.0, 'assistant_text_length_avg': 15.0, 'docker_error_count': 0.0, 'exit_status_ordinal': 0.0}
  Trial ID: task_b__attempt3, Task ID: task_b, Attempt: 3, Passed: False, Stability: borderline_1_3, Proxy Features: {'turn_count': 10.0, 'has_tool_calls_ever': 1.0, 'assistant_text_length_avg': 15.0, 'docker_error_count': 2.0, 'exit_status_ordinal': 2.0}
```

---

## 3. How the Evolver/Eval Loop Mechanically Works

The Raven self-evolution architecture separates runtime execution and grading logic from candidate generation using a strict state machine rather than soft-prompt instructions:

1. **The Hook Chain** ([engine.py](file:///library/repos/EverMind-AI_raven/code/raven/eval_engine/engine.py#L31))
   During evaluations, an agent turn executes with three sequential gates:
   * **Before-Iteration**: Computes a fast token budget estimate on the conversation history. If it is over budget, it halts the iteration by returning a `short_circuit_result`.
   * **Pre-Tool-Execution**: Scans planned tool calls against a denylist to halt execution before calling disallowed or destructive routines.
   * **After-Iteration**: Evaluates final outputs against user goals using `EvalJudge` ([judge.py](file:///library/repos/EverMind-AI_raven/code/raven/eval_engine/judge/judge.py#L47)), mapping the turn to a strict enum verdict (`completed`, `failed`, `unknown`).

2. ** Bandit-Guided Cohort Selection** ([trial_pool.py](file:///library/repos/EverMind-AI_raven/code/raven/evolver/analysis/trial_pool.py#L71))
   To evaluate candidates cheaply, Raven implements a cold-start bandit:
   * Baseline runs across $K$ trials per task are analyzed to assign stability buckets.
   * Metadata metrics (such as docker errors, average text length, final exit status mapped to ordinals) are extracted per trial.
   * Standard K-means clustering runs on the `stable_fail` cohort. The bandit samples representative task subsets from each cluster to form a "diagnostic set," ensuring diverse pathology coverage while saving LLM evaluation budget.

3. **Multi-Stage Verification Funnel**
   * **Diagnosis**: Synthesizes a structured `failure_map.json` grouping proposes by `(PatchWhere, PatchWhy)` cells.
   * **Screening**: Runs candidates on the diagnostic set with $K=1$.
   * **Confirmation**: Runs surviving candidates on $K=3$ trials.
   * **Promotion Gates**: Candidates must exceed the baseline in a paired sign statistical significance test, have zero infrastructure errors (infra failure counted as 0 points with fixed denominator), and verify that their code was hit at runtime via an explicit `activation_beacon()` check.

---

## 4. Three Concrete Borrowable Mechanisms for our Lab Loop

We can integrate the following structural patterns from Raven into our `bench` and `racetrack` workflows to improve robustness and reduce runtimes under WSL limits:

### Mechanism 1: K-means Stratification for Racetrack Selection
* **The Pattern**: Group failing trials into feature vectors (using metrics like execution turn counts, tool invocation flags, error counts, and output length averages) and apply K-means clustering to select a diverse subset of tasks.
* **Our Integration**: Instead of running racetrack proposals against a uniform or random task split, we can extract cheap trial features from `evo-demo` or target benchmarks and select one representative task per cluster. This forms a high-signal, diverse diagnostic subset for our screening phase, protecting our WSL RAM/swap limits.

### Mechanism 2: Activation Beacon Gating for Score Attribution
* **The Pattern**: Candidates must execute a specific runtime call (`activation_beacon()`) during the trial, and the harness confirms the beacon fired before awarding score credit.
* **Our Integration**: When comparing code changes on the `bench` (via `bench/experiment.sh` or our custom UCB1 select strategy in `plugins/evo/src/evo/frontier_strategies.py`), we can verify that the patched symbol was actually executed. If a test case passes but the candidate code branch was never executed (a false positive or silent pass), the change is culled.

### Mechanism 3: Pre-Iteration Token & Budget Gating
* **The Pattern**: Track character/token volume on message exchanges inside ReAct loops and abort early with a synthetic response if it exceeds limits.
* **Our Integration**: Under WSL memory limits (12GB RAM, 24GB swap), long runaway loops are our leading crash cause. We can wrap our benchmark runners or subagent tasks with a pre-iteration token and turn gate. If a candidate loops out of control, we abort it before wasting context window limits or triggering system OOMs.
