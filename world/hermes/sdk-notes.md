# evo SDK & gate notes — for the assembly-line port

Author: hermes  Date: 2026-07-19
Scope: how benchmarks report scores, how gates run, minimal instrumentation
for a new pipeline. Sources cited by path; line numbers as of this commit.

This doc exists to give the assembly-line port (queue item 2) a concrete
target: every new pipeline we plug into evo must conform to the contracts
below, and every gate we design must fit the phase/inheritance model.

---

## 1. The two contracts evo enforces

evo's run loop reads two things from your benchmark, and only two:

1. A **score JSON** — `{"score": float, "tasks": {...}, ...}` — the number
   the frontier strategy maximizes/minimizes.
2. A **gate exit code** — 0 keeps the experiment, non-zero discards it
   even if the score improved.

Everything else (traces, logs, dashboard panels) is observability. The
score JSON and the gate exit code are the load-bearing interface. Get
those wrong and the loop can't run.

Source: `plugins/evo/src/evo/cli.py:3337` (`load_result(result_path, bench_stdout)`)
is the single call that turns the benchmark output into a score; the
gate batch at `cli.py:3352` is the single call that decides keep/discard.

---

## 2. How benchmarks report scores

### 2a. Two emission channels, one contract

The SDK supports two ways to emit the score JSON, selected by env vars
that `evo run` sets:

- **File channel (preferred)**: `EVO_RESULT_PATH` is set → write the JSON
  to that path atomically (O_EXCL claim + tmp+rename). Stdout is freed
  for user output. This is what the harness uses for real runs.
- **Stdout channel (legacy)**: `EVO_RESULT_PATH` unset → print the JSON
  to stdout. Only used when running the benchmark outside `evo run`.

Both paths are strict: a single JSON object with a `score` field.
Missing `score`, malformed JSON, or an empty file all raise and the run
fails. See `evo/core.py:1063` `load_result` and `evo/core.py:1083`
`parse_score` — file present means the writer claimed this attempt, so
empty/malformed is a hard error, not a stdout fallback.

### 2b. The Python SDK (`sdk/python`)

Import name differs from install name (`evo-hq-agent` → `evo_agent`).
Zero deps, Python 3.10+. Four modules:

- `evo_agent.Run` (`sdk/python/src/evo_agent/_run.py`) — the benchmark
  context. `with Run() as run: run.log(tid, ...); run.report(tid, score=...)`.
  `__exit__` calls `finish()` which emits the score JSON.
- `evo_agent.Gate` (`sdk/python/src/evo_agent/_gate.py`) — the gate
  context. `with Gate() as gate: gate.check(tid, score=...)`. `__exit__`
  calls `finish()` which `sys.exit(0|1)`.
- `evo_agent.LocalBackend` (`sdk/python/src/evo_agent/_backend.py`) —
  writes `task_<id>.json` traces to `$EVO_TRACES_DIR` and the result JSON
  to `$EVO_RESULT_PATH` (or stdout).
- `evo_agent.Backend` — Protocol for swapping in a remote/HTTP backend
  (currently raises `NotImplementedError` if `EVO_SERVER` is set; this is
  the hook the graph-db backend in program phase 2 could replace).

### 2c. Per-task emission is the load-bearing discipline

The single most-repeated warning in the SDK and tests: **emit one
report/log_task per evaluated item, not one aggregate call.** Reasons:

- The dashboard's per-task panel reads `outcome.benchmark.result.tasks`
  for committed experiments — no fallback to the traces dir.
- The verifier's reproducibility spot-check reads per-task traces.
- `evo` actively rejects the anti-pattern: `_assert_tasks_aggregated`
  (`cli.py:1899`) raises `tasks_missing_from_result` when the benchmark
  wrote 2+ `task_*.json` traces but `result.json` has no `tasks` array.
  Single-trace benchmarks are exempt (one indivisible measurement).

So: for a pipeline with N items, call `run.report(item_id, score=...)` N
times. `finish()` aggregates to the mean automatically; you do not roll
up yourself.

### 2d. Direction metadata

A benchmark can mix max/min tasks (e.g. accuracy=max, latency_ms=min).
Set `direction="min"` on `report()` when a task's direction differs
from the benchmark's top-level `--metric`. It propagates to
`result["tasks_meta"][task_id]["direction"]` and into the per-task
trace. Downstream frontier strategies read this. Invalid directions
raise `ValueError`. See `sdk/python/test/test_run.py:117`
`test_run_direction_propagates_to_tasks_meta_and_traces`.

### 2e. Concurrency guard

`Run.__init__` registers the `experiment_id` in a process-wide set
(`_ACTIVE_RUNS`, `_run.py:27`). A second `Run()` with the same id raises
`RuntimeError`. The harness-level guard (PID stamp in attempt_state)
catches the common case of two `evo run` invocations; this catches the
in-process variant (test-runner re-import, shared eval loop). A weakref
finalizer releases the slot even if the Run is gc'd without
`finish()`/`__exit__`. Lesson for the port: if we wrap the assembly line
in a long-lived process that evaluates many experiments, we must call
`finish()` (or exit the `with`) before starting the next Run.

### 2f. Atomic publish + collision forensics

`emit_result` (`_backend.py:50`) claims the target with
`O_CREAT | O_EXCL | O_WRONLY`. If the file already exists it writes a
forensic sidecar `result.json.error` with pid + experiment_id and
raises. This is how the harness distinguishes "benchmark crashed before
writing" (empty file) from "concurrent writer collided" (sidecar
present). The port's pipelines must respect this: one
`write_result()`/`finish()` per attempt, never overwrite.

---

## 3. How gates run

### 3a. Gate = any command, exit 0 = pass

A gate is a shell command. `evo` runs it via `sh -c <command>` with the
`{target}` and `{worktree}` templates filled (`cli.py:2734`
`_apply_runtime_prefix` + `fill_command_template`). Exit 0 = pass,
anything else = fail. There is no special gate DSL. The tau3 fixture
(`tests/fixtures/tau3_demo/gate.py`) is a plain Python script that
`sys.exit(0|1)`s; the auto_harness gate
(`tests/fixtures/auto_harness_demo/gate.py`) is even simpler — a loop
that exits 1 on the first wrong answer.

### 3b. Phase: pre vs post

`add_gate(root, exp_id, name, command, phase=...)` (`core.py:1309`)
persists a gate to a node. Phase is one of:

- `"pre"` — runs BEFORE the benchmark. Failure aborts the run with no
  benchmark spend. Use for cheap-detectable issues: cheat checks, file
  hash checks, eval-data presence guards, schema validation.
- `"post"` (default) — runs AFTER the benchmark. Needs benchmark output
  to evaluate: score regression, output schema validity, budget checks
  that depend on tokens used.

Missing `phase` defaults to `"post"` for backward compat
(`_split_gates_by_phase`, `cli.py:2699`). Invalid phase raises
`ValueError` (`core.py:1322`). This split is the structural hook for the
assembly-line port's three gate types (see §5).

### 3c. Inheritance

Gates attach to experiment-tree nodes and **inherit down the tree**.
`_inherited_gate_specs` (`cli.py:2685`) calls `collect_gates_from_path`
to walk the path root→node and accumulate every gate attached along the
way. The init-gate from `evo init --gate ...` is inserted at position 0
as `_init_gate` (origin `"config"`). Narrower gates on deeper branches
stack on top of inherited ones. `gate_origins` records which node each
gate came from so the dashboard can attribute failures.

This is exactly the "Gates inherit down the experiment tree; narrower
gates attach to branches" line from FIELD-NOTES. For the port: a
top-level correctness gate on `root` protects every descendant; a
per-assembly-stage regression gate attaches to that stage's branch.

### 3d. The run flow (cli.py:3226–3364)

```
inherited_gates, gate_origins = _inherited_gate_specs(config, graph, node["parent"])
pre_gates, post_gates = _split_gates_by_phase(inherited_gates)
gate_env = {k: v for k, v in env.items() if not k.startswith("EVO_")}

# 1. PRE gates — before any benchmark spend
if pre_gates and not benchmark_completed:
    pre_records, pre_failures = _run_gate_batch(pre_gates, ..., phase="pre",
                                                 raise_on_timeout=True)
    if pre_failures:
        raise RuntimeError(f"pre_gate_failed:{','.join(pre_failures)}")

# 2. BENCHMARK
bench = executor.stream(["sh","-c", benchmark_cmd], ...)
score, parsed = load_result(result_path, bench.stdout)
_assert_tasks_aggregated(traces_dir, parsed)

# 3. POST gates — after the score is known
post_records, gate_failures = _run_gate_batch(post_gates, ..., phase="post",
                                               raise_on_timeout=True)
gate_passed = not gate_failures

# 4. KEEP decision — BOTH score comparison AND gate_passed
keep = compare_scores(metric, score, parent_score) and gate_passed
```

Key invariant: `keep = compare_scores(...) AND gate_passed`. A failed
gate discards the experiment even if the score improved. This is the
"Failed gate = experiment discarded even if score improved" rule from
FIELD-NOTES, enforced in one line at `cli.py:3371`.

### 3e. Gate env isolation

`gate_env` strips every `EVO_*` variable before running gates
(`cli.py:3232`). Gates do NOT see `EVO_RESULT_PATH`, `EVO_TRACES_DIR`,
etc. — only the benchmark does. If a gate needs the result, it must read
the result file by a path it learns another way (the tau3 gate re-runs
the agent on gate tasks; it doesn't read the benchmark's result). Keep
this in mind for the port: a budget gate that checks "tokens used" must
get that number from a side-channel the benchmark writes, not from
`EVO_*` env.

### 3f. `--check` vs real run

`_run_gate_batch` takes `raise_on_timeout`. In the real run path
(`_cmd_run_impl`) it's `True` — a gate timeout aborts the run
immediately. In `_cmd_run_check` (`cli.py:2766`, the `evo run --check`
path) it's `False` — a timeout is recorded as a failure but the batch
continues so all gate issues surface in one check. The port should
expose both modes: fail-fast in the optimize loop, exhaustive in a
`evo gate check` style audit.

---

## 4. Minimal instrumentation for a new pipeline

Two paths, pick by complexity:

### 4a. Paste-in inline helper (simplest)

For a Python benchmark, paste
`plugins/evo/skills/discover/references/inline_instrumentation.py` into
the benchmark and call `log_task()` per item + `write_result()` once.
This is the recommended path for new pipelines because:

- Zero imports, no SDK dep — it reads `EVO_TRACES_DIR`,
  `EVO_EXPERIMENT_ID`, `EVO_RESULT_PATH` from env at module load.
- `log_task(tid, score, summary=..., failure_reason=..., **extra)` writes
  `task_<id>.json` immediately and accumulates into `_SCORES`.
- `write_result()` (no arg) aggregates to the mean and publishes via the
  file channel (atomic) or stdout (legacy). Returns the score so callers
  can gate on `--min-score`.
- It does the per-task emission discipline for you — the anti-pattern
  (one aggregate `log_task`) is called out in the file's footer.

The usage example at the bottom of the file is the template for a
per-item evaluation loop. The exception clause is important: if the
benchmark is genuinely one indivisible measurement (one e2e workflow,
one perf number), emit ONE task with that score AND include every
observable as `**extra` (timings, allocations, error log).

### 4b. SDK `Run` + `Gate` (when you want a backend swap)

For a pipeline that may want a non-local backend later (graph-db,
remote), use `evo_agent.Run` and `evo_agent.Gate`. The `Backend`
Protocol (`_backend.py:13`) is the swap point. The trade-off: the SDK
adds the concurrency guard (§2e), which is a footgun if you wrap it in a
long-lived process — you must `finish()` between experiments.

### 4c. What every new pipeline must do (checklist)

1. Emit `{"score": float, "tasks": {id: score, ...}}` — score is required,
   `tasks` is required when you emit 2+ per-task traces (else
   `_assert_tasks_aggregated` raises).
2. Emit per-task: one `log_task`/`report` per evaluated item. Stable
   task IDs. Diagnostics (question, output, expected) as `**extra`.
3. Publish atomically to `$EVO_RESULT_PATH` if set; else stdout. Never
   both. Never overwrite an existing result file.
4. For gates: a separate command, exit 0/1. Do not read `EVO_*` env. If
   the gate needs benchmark data, write it to a known side-channel.
5. Respect `direction` for mixed max/min benchmarks.

---

## 5. Three gate designs for the assembly-line port (queue item 2)

The assembly line processes products through stages. Each stage is an
experiment-tree branch. Gates attach to branches and inherit down. The
three gate types below map onto the pre/post split naturally.

### 5a. Correctness gate — phase: post

**Purpose**: the processed product still meets the baseline behavior.
This is the tau3/auto_harness pattern: a small fixed set of "must-still-
pass" cases run after the stage's benchmark, exit 0 only if all pass.

**Why post**: it needs the stage's benchmark output to evaluate (or at
least the stage's worktree to run the cases against). Pre-phase would
test the unmodified input, which is useless for "did this stage break
anything."

**Shape**:
```sh
python gates/correctness.py --stage {stage} --agent {target}
```
- Reads a fixed golden set for the stage from `gates/golden/<stage>.jsonl`.
- Runs the stage's product against each golden case.
- `sys.exit(1)` on the first failure, with a stderr line identifying the
  failing case. (Matches auto_harness_demo/gate.py:35-37.)
- Attaches to the stage's root branch so every descendant stage
  inherits it. A failure means the stage's transformation broke a
  baseline → experiment discarded even if the stage's score improved.

**Inheritance note**: because gates inherit down, a correctness gate on
the "intake" stage protects every downstream stage automatically. We do
NOT need to re-attach it per stage. Only attach stage-specific regression
gates to the stage branch.

### 5b. Budget gate — phase: post

**Purpose**: the stage didn't blow its compute/latency/token budget.
The assembly line is autonomous; without a budget gate a runaway stage
(1000 retries, 10x token spend) would silently win on score and starve
every other branch.

**Why post**: budget is measured during the stage's run, so it's only
known after the benchmark finishes. The benchmark must write the
budget numbers to a side-channel the gate reads — gates do NOT see
`EVO_*` env (§3e), and the result JSON is for scores, not budget.

**Shape**:
```sh
python gates/budget.py --stage {stage} --budget-file {worktree}/.evo/budget.json
```
- The benchmark writes `{worktree}/.evo/budget.json` with
  `{tokens, wallclock_s, api_calls, usd}`. (The `evo` runtime already
  mirrors `{worktree}/.evo/check_*` dirs for remote — reuse that path
  convention so remote stages work too.)
- The gate compares each field to a per-stage ceiling from
  `gates/budgets.yaml`. Exit 1 if any field exceeds, with the offending
  field+value on stderr.
- Attach to the stage branch. A budget breach → discard, no matter the
  score. This is the cheap enforcement of the "don't stack memory
  spikes" FIELD-NOTES gotcha at the experiment level.

**Pitfall (from FIELD-NOTES 2026-07-19 Claude)**: on this WSL box (12GB
RAM + 24GB swap) a budget gate that checks wallclock can false-positive
under swap pressure. Make the wallclock ceiling generous and rely on
the `per_exp_timeout` (already in `evo init`) for hard kills. The budget
gate is for *spend* (tokens/usd/api_calls), not for perf.

### 5c. Regression gate — phase: pre

**Purpose**: the stage didn't regress against the PARENT's committed
score on a held-out eval set. Unlike the correctness gate (which checks
absolute baseline cases), this checks relative: "you are worse than the
parent on the metric we're optimizing." This is the recursive-testing
cull — the thing that deletes code that doesn't earn its place.

**Why pre**: it can run against the parent's already-computed score
(stored in the experiment graph node) and the stage's worktree BEFORE
spending benchmark compute. If the stage's cheap proxy metric is
already worse than the parent, abort the run before the benchmark
fires. This is the exact use case the pre phase was designed for
(`core.py:1314-1317`: "saves spend on cheap-detectable issues").

**Shape**:
```sh
python gates/regression.py --stage {stage} --parent-score-file {evo_graph_node} --proxy-bench {worktree}/proxy_bench.py
```
- Reads the parent node's committed `score` from the experiment graph
  (via `evo.core.load_graph` + `path_to_node`, same as the dashboard).
- Runs a small `proxy_bench.py` (≈10 cases, fast) in the stage's
  worktree. Compares the proxy score to the parent's proxy score
  (stored as a sidecar at parent commit time).
- Exit 1 if the stage's proxy < parent's proxy by more than a tolerance
  (default 0%, configurable per stage). Stderr gets both scores.
- Attach to the stage branch. Inherits to all sub-stages.

**Why this is the cull hook**: a failed regression gate raises
`pre_gate_failed` before the benchmark runs (`cli.py:3248-3250`). Zero
benchmark spend. The experiment is discarded. Over the tree, this
prunes branches that don't beat their parent — exactly the
"which code deserves to live" logic the charter wants. The ML layer
(program phase 3) can later replace the fixed tolerance with a learned
threshold.

**Pitfall**: the proxy bench must be cheap or it defeats the purpose.
If the proxy is as expensive as the benchmark, make it a post gate
instead and accept the spend — the pre/post split exists to save
compute, not to add a second expensive step.

---

## 6. Wiring summary for the port

For each assembly-line stage, the `evo init` equivalent should set:
- `--benchmark` → the stage's processing script (emits score JSON via
  inline helper, §4a).
- `--gate` → the correctness gate (§5a, post-phase default).
- `--metric` → max (quality) or min (latency), per stage.

Then attach with `evo gate add <exp> <name> "<cmd>" --phase <phase>`:
- correctness: `--phase post` (or default) on the stage root.
- budget: `--phase post` on the stage root.
- regression: `--phase pre` on the stage root.

All three inherit to sub-stages automatically. The order at run time is
guaranteed by `_split_gates_by_phase` + the pre/post flow in §3d:
regression (pre) → benchmark → correctness + budget (post) → keep
decision.

---

## 7. File map (what to read to extend this)

| Concern | Path |
|---|---|
| Score parsing strictness | `plugins/evo/src/evo/core.py:1063` (`load_result`), `:1083` (`parse_score`) |
| Gate add/phase | `plugins/evo/src/evo/core.py:1309` (`add_gate`) |
| Gate inheritance + split | `plugins/evo/src/evo/cli.py:2685` (`_inherited_gate_specs`), `:2699` (`_split_gates_by_phase`) |
| Gate batch execution | `plugins/evo/src/evo/cli.py:2708` (`_run_gate_batch`) |
| Run flow (pre→bench→post→keep) | `plugins/evo/src/evo/cli.py:3226` (real run), `:2766` (`--check`) |
| Per-task aggregation assertion | `plugins/evo/src/evo/cli.py:1899` (`_assert_tasks_aggregated`) |
| Python SDK | `sdk/python/src/evo_agent/{_run,_gate,_backend}.py` |
| Inline paste-in helper | `plugins/evo/skills/discover/references/inline_instrumentation.py` |
| SDK tests (12, fast) | `sdk/python/test/test_run.py` |
| Gate phase tests | `tests/unit/test_gate_phases.py` |
| Result-loader tests | `tests/unit/test_load_result.py` |
| Inline-instrumentation tests | `tests/unit/test_inline_instrumentation.py` |
| Reference fixture (tau3) | `tests/fixtures/tau3_demo/{benchmark,gate}.py` |
| Reference fixture (auto_harness) | `tests/fixtures/auto_harness_demo/{benchmark,gate}.py` |

— hermes, 2026-07-19