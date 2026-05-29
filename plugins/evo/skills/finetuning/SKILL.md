---
name: finetuning
description: When-to-do-what for the weight-update (training) axis -- terse method triggers, what actually matters, and the rules that are NOT laws. Load when planning or diagnosing a train move. Provider recipes and the data/trace/glue contract are in references/.
evo_version: 0.4.4-alpha.3
---

# Finetuning

Training is an activity you write in the experiment worktree; the benchmark loads the produced checkpoint by convention and emits a scalar score. evo ships no per-framework adapter. How to call a given backend, the data/trace shapes, and how to read a run all live in `references/` -- don't inline them here.

Pick the backend that fits the environment, using only what `final_model` can run on there: a **managed service** if one's available and allowed (`sft/tinker.md`, `rl/art.md` — these also serve the checkpoint), or **local single-GPU** training with whatever's installed (e.g. TRL/PEFT) plus `serving/vllm.md` to serve the adapter. A self-contained GPU box with no external services is the local path.

The only **firm** things are evo's guardrails: a held-out eval you never train on, and no eval-data leakage (both are gates), and trust evo's recorded numbers over a run's self-report. Everything below is a prior to apply with judgment and override against the gate.

## When to do what

- **SFT** -- install a capability the base lacks: format, tone, chat, curated data.
- **RFT** (rejection-sampling / STaR) -- SFT on filtered high-reward samples. Highest-return next step once you can score outputs; stable and cheap.
- **DPO / preference** -- quality is taste/pairwise, not verifiable; you have chosen/rejected pairs and don't want an RL loop.
- **RL (GRPO/PPO)** -- you have a reward you trust and offline methods plateaued; gets gains they can't, at more cost and fuss. Bigger models benefit more.

## What actually matters (roughly in order)

1. A reward you trust -- verifiable beats a learned reward (which gets hacked).
2. A held-out eval you never train on.
3. On-policy freshness for RL -- train on the current policy's samples, not stale ones.
4. LoRA LR is ~10x full-fine-tune; rank matters less than people think (32 is a fine default). LoRA ~= full-FT for RL and small-data SFT; it lags on large SFT sets.

Method- and provider-specific numbers (LR, KL, group size) live in the recipe you pick under `references/`.

## Not laws

Don't state these as rules -- they're situational, decide empirically against the gate:

- "Always SFT before RL" -- RL-from-base works for strong base models; SFT is a warm-start, not a prerequisite.
- "Only RL with verifiable rewards" -- preference-RL on a learned reward is valid where correctness isn't checkable.
- "Always keep the KL penalty" -- some reasoning-RL runs drop it; it's a tunable.
- Fixed β / rank / LR as universal -- scale- and task-dependent.

## Reading a run

`references/diagnostics.md` -- evo records `held_out_score`/`delta`, `reward_saturation`, `generalization_gap`; interpret against those (`delta <= 0` means the move didn't help).

## References

- `references/glue.md` -- write the training activity (what evo provides, what to emit).
- `references/trace-schema.md` -- rollout + `TrainingTrace` JSON shapes.
- `references/diagnostics.md` -- what evo computes + how to read it.
- `references/{sft,rl,serving}/` -- provider recipes (`sft/tinker.md`, `rl/art.md`, `serving/vllm.md`).
