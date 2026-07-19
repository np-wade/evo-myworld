# Prior-art citations — gate library (Track A, deliverable A1)

Author: hermes  Date: 2026-07-19
Method: GRAPH-FIRST — pulled slices from the graphify index.db via
`world/backend/evo_graph.py find <query>` (Track B phase-1 tool), then
read the cited source files in the corpus at `/library/repos/`. Each
gate design below has ≥2 candidates with REAL citations I read end-to-end.

The lab's RACE RULE (CHARTER.md §"THE RACE RULE") requires racing ≥2
candidates in the evo-hq harness. The race requests for these gates
live at `racetrack/requests/gate-<type>.md`; this file records the
citations the race steward will instantiate as experiment branches.

---

## 1. Correctness gate — post-phase, golden-case assertion

**What it does**: small fixed golden set; runs the stage's product
against each case; `exit 1` on first failure.

### candidate A: evo's own auto_harness_demo/gate.py
- source: `tests/fixtures/auto_harness_demo/gate.py` (this repo,
  `evo-hq/evo` upstream)
- approach: a Python module loaded with `importlib`; iterate a hard-
  coded `GATE_TASKS` list of `{request, expected}`; on the first
  `module.solve(task) != task["expected"]`, `sys.exit(1)`. Exits 0
  only if every case passes. This is the canonical evo pattern —
  zero deps, plain `sys.exit`, no SDK import.
- cited at: `tests/fixtures/auto_harness_demo/gate.py:35-44`

### candidate B: nocodb assert_golden
- source: `nocodb/nocodb` slice — file
  `docker-compose/1_Auto_Upstall/tests/lib/helpers.bash:56-60`
- approach: bash helper. Normalizes the generated artifact and diffs
  it (`diff -u`) against a committed golden file. Mismatch prints a
  unified diff and fails the test (non-zero exit from `diff`). This is
  the file-snapshot variant of the same idea — golden = a fixed
  committed artifact, not a hardcoded case list.
- cited at:
  `/library/repos/nocodb_nocodb/code/docker-compose/1_Auto_Upstall/tests/lib/helpers.bash:58`
- slice query: `graph find "golden jsonl assert expected output evaluation cases"`

**Race dimension**: case-list (A) vs file-snapshot (B). For the
assembly line, A is the natural fit (per-product golden cases), but B
matters if a stage's output is a generated file. The race steward
builds a fair arena where both run the same golden set and we measure
false-negative rate + runtime.

---

## 2. Budget gate — post-phase, per-stage spend cap

**What it does**: benchmark writes a side-channel budget.json (since
gates do NOT see EVO_* env, sdk-notes.md §3e); gate compares each
field to a per-stage ceiling and exits 1 if any field exceeds.

### candidate A: OmniRoute checkTokensPerTaskGate
- source: `diegosouzapw/OmniRoute` slice — file
  `code/open-sse/services/compression/harness/budgetGate.ts:46-62`
- approach: per-task ratchet gate. Computes mean compressed tokens per
  task group from an `EvalReport`, compares each task's current mean
  to a frozen baseline, fails when `deltaPercent > tolerancePercent`
  (default 2%). Falling cost always passes — baseline is a ratchet,
  not a hard cap. Returns `{passed, regressions[], tolerancePercent}`.
- cited at: `/library/repos/diegosouzapw_OmniRoute/code/open-sse/services/compression/harness/budgetGate.ts:46`
- slice query: `graph find "gate budget regression correctness"`

### candidate B: raven BeforeIterationHook (token-budget/pruning gate)
- source: `EverMind-AI/raven` slice — file
  `code/raven/eval_engine/hooks/before_iteration_hook.py:25-73`
- approach: crude byte/4 token estimate of the messages list; if
  estimate exceeds `config.max_iteration_tokens`, short-circuit the
  iteration with a synthetic halt. Intentionally a rough estimator
  ("prevent runaway, not millisecond-accurate"). This is the absolute
  cap variant — no baseline, just "above this number = fail."
- cited at: `/library/repos/EverMind-AI_raven/code/raven/eval_engine/hooks/before_iteration_hook.py:41`
- slice query: `graph find "token usage budget gate ratchet"`

**Race dimension**: ratchet vs absolute-cap. For the WSL box with
12GB RAM + 24GB swap (CHARTER gotcha), the ratchet (A) catches spend
regressions across the experiment tree even when absolute numbers stay
under a generous cap. But absolute-cap (B) is what protects against a
single runaway stage starving every other branch. The race steward
builds an arena where both run over a synthetic budget.json with one
field spiked; we measure false-positive rate under swap pressure and
catch-rate on a real spike.

---

## 3. Regression gate — pre-phase, parent-score comparison

**What it does**: compares a cheap proxy metric on the stage's
worktree against the parent's committed proxy score; if worse beyond
a tolerance, exits 1 BEFORE the benchmark runs (pre-phase saves
benchmark spend — sdk-notes.md §3d).

### candidate A: adk-rust BaselineStore::check_regressions
- source: `zavora-ai/adk-rust` slice — file
  `code/adk-eval/src/baseline.rs:116-154`
- approach: per-metric, per-case signed delta. Loads a baseline JSON
  (`HashMap<metric, HashMap<case_id, f64>>`), compares each
  `(metric, case)` pair to current; a regression is `baseline_value -
  current_value > tolerance`. No baseline file → no regressions
  (graceful skip, not fail). Returns `Vec<Regression>` with the
  offending metric/case/baseline/current/delta.
- cited at: `/library/repos/zavora-ai_adk-rust/code/adk-eval/src/baseline.rs:116`
- slice query: `graph find "regression test parent baseline proxy benchmark"`

### candidate B: repowise density_regression smell
- source: `repowise-dev/repowise` slice — file
  `code/scripts/kg_validate/kg_checks.py:347-367`
- approach: per-language drop ratio. For each language in the current
  stats, if a baseline exists and `1.0 - (cur/prev) > DENSITY_REGRESSION_TOLERANCE`,
  emits a `Smell("FAIL", "density_regression", "<lang>: X -> Y
  imports/file (Z% drop)")`. Single scalar per dimension, percentage-
  based, not absolute-delta. Graceful: skips languages with no
  baseline or zero baseline.
- cited at: `/library/repos/repowise-dev_repowise/code/scripts/kg_validate/kg_checks.py:347`
- slice query: same as A; second hit.

**Race dimension**: absolute-delta vs percentage-drop. For our
experiment tree (evo records `score` per node, sdk-notes.md §5c), the
parent's committed score is a single scalar — candidate A's
`HashMap<metric, HashMap<case_id, f64>>` is richer than we need but
trivially degenerates to one metric/one case. Candidate B's
percentage-drop is the natural shape for a single-scalar proxy. The
race steward builds an arena where both run over a parent/child pair
with a planted 5%/10%/20% regression; we measure detection accuracy
at each tolerance and false-positive rate on a no-change child.

---

## 4. Held-out gate — post-phase, generalization check

**What it does**: runs the stage's product on a held-out set the
benchmark never trained on; if held-out score < tolerance, exit 1.
This is the overfitting check — the thing that deletes code that
memorized the benchmark instead of generalizing.

### candidate A: Lightning-AI overfit_batches
- source: `Lightning-AI/pytorch-lightning` slice — file
  `tests/tests_pytorch/trainer/flags/test_overfit_batches.py:31-46`
  and `:175-200`
- approach: trainer runs on a small fraction of training data with
  validation disabled; the test asserts that the model can overfit
  that one batch (training accuracy → 1.0) AND that, when eval is
  enabled on a separate split, the eval score is bounded. This is the
  "can you even learn anything" sanity check, paired with a held-out
  eval on a disjoint split.
- cited at: `/library/repos/Lightning-AI_pytorch-lightning/code/tests/tests_pytorch/trainer/flags/test_overfit_batches.py:175`
- slice query: `graph find "overfit train eval gap penalty detect generalization"`

### candidate B: ruvector learned_weights_beat_chance_on_held_out
- source: `ruvnet/ruvector` slice — file
  `code/crates/emergent-time/src/weight_learning.rs:460-487`
- approach: split traces into train (60%) and held-out val (40%) with
  disjoint seeds; fit weights on train; compute AUC on the held-out
  set; `assert!(learned_auc > 0.7, "held-out AUC should beat
  chance")`. Single scalar threshold on a disjoint slice — exactly
  the held-out gate semantics.
- cited at: `/library/repos/ruvnet_ruvector/code/crates/emergent-time/src/weight_learning.rs:460`
- slice query: `graph find "held out split sample never seen evaluation canary"`

**Race dimension**: paired-overfit-and-eval (A) vs single-threshold-
  on-held-out (B). For the assembly line, B is the natural fit — the
  benchmark already runs on the training set; the held-out gate runs
  on a disjoint slice and asserts a single score threshold. A is
  heavier (needs a paired overfit run) and only worth it when we
  suspect the stage is memorizing. The race steward builds an arena
  where a stage overfits a tiny training set and we measure which
  gate catches the overfit first under a fixed budget.

— hermes, 2026-07-19