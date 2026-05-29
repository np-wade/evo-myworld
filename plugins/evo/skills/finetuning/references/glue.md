# Writing the training activity (glue)

You write this per task in the experiment worktree. evo provides inputs by convention; you produce a checkpoint + traces; the benchmark loads the checkpoint and emits a scalar score.

## Inputs evo provides (by convention)

- `EVO_DATASET` — path to the assembled scored-trajectory JSONL (train split only;
  selection already applied). See `trace-schema.md`.
- `EVO_PARENT_POLICY` — base model id, or a parent checkpoint to warm-start from.
- `EVO_RUN_DIR` / `EVO_ARTIFACTS_DIR` — where to write the checkpoint + traces.
- Held-out data is **not** provided — evo scores on it independently.

## What you produce

1. A **checkpoint artifact** under the artifacts dir, recorded on the result as
   `artifacts: [{kind: "lora_adapter"|"checkpoint", uri, content_key, created_by}]`.
2. `train_summary.json` — the `TrainingTrace` setup/dynamics fields.
3. `metrics.jsonl` — step-indexed `{step, loss, reward, kl, grad_norm, lr}`.

## Benchmark by convention

The benchmark loads the active checkpoint (from the consumed artifact / the policy
env the harness reads) and emits the normal scalar score. A child experiment that
`consumes` the checkpoint is scored exactly like any other node — score stays the spine.

## Rules

- Compute loss on **assistant tokens only** (set `trainable`); keep groups intact.
- Train and serve with the **same chat template / tokenizer** — serving drift silently tanks LoRA quality.
- Never fetch or evaluate on held-out scenarios — evo owns that boundary.
