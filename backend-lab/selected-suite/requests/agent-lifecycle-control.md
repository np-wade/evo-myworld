# race: agent-lifecycle-control
seat: backend-lab
question: which control-plane lifecycle best provides durable dependency-aware agent execution, steering, cancellation, recovery, and exactly-once claims?
metric: max — passed lifecycle scenarios across dependency, contention, cancellation, restart, failure propagation, pause/resume, and bounded-child fixtures; ties broken by operations/sec
gate: idempotent same-owner claim; exclusive different-owner claim; dependencies never run early; restart restores running ownership; every transition is auditable

## candidate: evo-mission-dag
source: projects/evo-myworld/plugins/evo/src/evo/missions.py
approach: persistent research/build/verify/integrate DAG overlay with dependency unlock, idempotent claims, depth/child caps, and cancellation cascade.

## candidate: witt-spine-lanes
source: projects/witt-spine/crates/spine-engine/src/lib.rs
approach: Rust task state machine with CAS claim/reconcile, lane pool slots, dependency gating, and failure propagation.

## candidate: pueue-durable-queue
source: filing-cabinet/library-base/repos/Nukesor_pueue/code
approach: durable queue state with pause/resume, task controls, process ownership, and retry-oriented local execution.

## candidate: cowork-task-sessions
source: filing-cabinet/library-base/repos/CoWork-OS_CoWork-OS/code
approach: persistent task/event/session records with recursive child-task creation and parent cancellation propagation.
