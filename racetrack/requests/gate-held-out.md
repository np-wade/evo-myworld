# race: gate-held-out
seat: hermes
question: which held-out gate (single-threshold vs paired-overfit-and-eval) catches memorization faster under a fixed small budget?
metric: min seconds to detect a stage that memorized a 20-case training set (detection = gate exits 1)
gate: exit 0 iff the gate fires on a known-memorizing stage and passes on a known-generalizing stage

## candidate: single-threshold
source: /library/repos/ruvnet_ruvector/code/crates/emergent-time/src/weight_learning.rs:460-487
approach: split traces 60/40 train/held-out with disjoint seeds; fit on train, compute AUC on held-out, `assert!(learned_auc > 0.7)`. Single scalar threshold on a disjoint slice.

## candidate: paired-overfit
source: /library/repos/Lightning-AI_pytorch-lightning/code/tests/tests_pytorch/trainer/flags/test_overfit_batches.py:175-200
approach: trainer runs on a small fraction of training data; assert the model CAN overfit one batch (train acc → 1.0) AND, when eval is enabled on a separate split, eval score is bounded. Paired overfit + disjoint eval.