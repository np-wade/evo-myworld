# race: safe-self-improvement
seat: backend-lab
question: which self-improvement loop produces the largest real held-out gain while resisting reward hacking, regressions, and premature promotion?
metric: max — held-out improvement delta across deterministic deceptive, specialist, and transfer landscapes; ties broken by evaluations required
gate: held-out data is never used for proposal/training; visible-score regressions are rejected; every promotion has independent verification and rollback evidence; a candidate that improves only the training score fails

## candidate: evo-pareto-loop
source: projects/evo-myworld/plugins/evo/src/evo/frontier_strategies.py and plugins/evo/src/evo/missions.py
approach: preserve per-task specialists with Pareto selection, generate bounded research/build/verify/integrate missions, and promote only independently verified experiments.

## candidate: flywheel-policy
source: filing-cabinet/library-base/repos/Wassimyounes01_flywheel/code/docs/architecture.md
approach: update action policy from observed reward with win-rate/average-reward weighting, bounded exploration, count decay, and group-relative advantages.

## candidate: rd-agent
source: filing-cabinet/library-base/repos/microsoft_RD-Agent/code
approach: autonomous research-and-development experiment generation evaluated on the same locked tasks and promotion gate.

## candidate: opik-optimizer
source: filing-cabinet/library-base/repos/comet-ml_opik/code
approach: judge- and optimizer-driven candidate generation with structured traces, multi-metric evaluation, and an external held-out promotion gate.
