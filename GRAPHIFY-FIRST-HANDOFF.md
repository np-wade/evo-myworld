# Handoff: Graphify-first EvoHQPlus

Date: 2026-07-19

## Project objective

Build EvoHQPlus by using Graphify as the discovery, evidence, and selection
engine. Do not invent major subsystems before searching the existing code
corpus. For every capability, Graphify should identify multiple proven code
paths; Evo should run them under common gates and harnesses; measured winners
should be integrated; results and failures should feed the next graph-guided
cycle.

The capabilities to develop are:

1. better code implementations;
2. better test and benchmark harnesses;
3. better agent instructions and task briefs;
4. better guidelines and operational guardrails;
5. app/UI interaction testing, including click, press, hold, repeat, release,
   drag, keyboard, touch, cancellation, and concurrent-event primitives;
6. frontend/backend/database contract and failure testing;
7. reproducible native and isolated execution environments;
8. backend evidence processing, provenance, failure classification, and
   knowledge write-back;
9. graph-informed selection that is always confirmed by empirical tests.

## Required working method

Follow `projects/graphify-app/GRAPH-FIRST.md` exactly:

1. Find the topic in `data/graphs/TOPICS.md`.
2. Inspect candidate repositories' `slices/overview.png` and `slices/INDEX.md`.
3. Read the relevant self-contained slice JSON.
4. Follow `source_file` and `source_location` into the real repository code.
5. Record candidates and citations before implementation.
6. Race at least two candidates with the same fixtures, seeds, resources,
   correctness gates, and activation/coverage proof.
7. Integrate the reproducible winner and retain losing evidence.

Use SQLite read-only for symbol lookups and 1–2-hop relationships. Use FalkorDB
only for bounded 3+-hop questions and push one relevant repository at a time.
The 9.2M-node source index remains immutable during experiments.

## Intended closed loop

```text
need or failure
  -> Graphify topic/symbol/relationship retrieval
  -> 2+ source-backed candidate paths
  -> tiered simulation, tests, mutation checks, and real-app confirmation
  -> structured diagnosis and score
  -> winner/loser decision with provenance
  -> promoted code + incremental Graphify re-index
  -> experiment evidence written to the knowledge graph
  -> next retrieval uses what was learned
```

Graph relevance proposes what to try. Correctness gates and measurements decide
what wins. Centrality, popularity, or proximity alone must never promote code.

## Concrete prior art already found

The following were discovered through the Graphify index and then checked in
their overview images, slice indexes, and real source files.

### Generated event/state testing

- Repository: `zavora-ai/adk-rust`
- Graph hit: `arb_event_sequence()` in
  `adk-session/tests/event_ordering_property_tests.rs`.
- Useful pattern: `proptest` strategies generate arbitrary event sequences;
  independent invariants check ordering, stability, idempotence, and preservation.
- Adaptation target: generate UI/control protocol events and assert invariants
  without a browser. This is the appropriate tier for the “millions of
  simulations” goal before replaying a reduced corpus in a real app.
- Relevant graph slices include `_misc-1`, `_misc-7`,
  `serialization-event-verify~c44`, `failure-policy-arb~c139`,
  `guardrail-pass-fail~c177`, and `parameters-schema-execute~c182`.

### Guardrail event conformance

- Repository: `NVIDIA-NeMo/Guardrails`
- Graph hit: `event_sequence_conforms()` in `tests/utils.py`.
- Useful pattern: recursive subset matching makes assertions resilient to
  additive metadata while still verifying required event fields and sequence.
- Adaptation target: shared conformance oracle for agent action streams,
  frontend/backend traces, and allow/deny guardrail cases.
- The overview shows guardrail validators, event-flow status, action-flow events,
  output rails, metrics, and command benchmarks as connected sections rather
  than isolated utilities.

### Dual-path backend verification and experiment UI

- Repository: `PostHog/posthog`
- Source checked:
  `frontend/src/scenes/experiments/ExperimentView/ExperimentExecutionPathComparison.tsx`.
- Useful pattern: run direct and precomputed backend paths concurrently, capture
  duration/error independently, compare counts/sums/means by variant, and show
  frequentist or Bayesian significance without hiding disagreement.
- Adaptation target: compare Evo/Graphify result paths, backend processing
  variants, and old/new harness implementations inside the app.
- Relevant graph sections include `ExperimentExecutionPathComparison`,
  experiment implementation details, holdouts, query runners, traces, and
  health/monitoring components.

### Additional indexed candidates to inspect next

- `xai-org/grok-build`: `state_machine.rs` and event-loop sequences.
- `refinedev/refine`: mutation-result/property testing utilities.
- `NVIDIA-NeMo/Guardrails`: flow state machine and event/action rails.
- `zavora-ai/adk-rust`: guardrail sets, property tests, audit sinks, scopes,
  confirmation state, session backends, and Neo4j/Redis/in-memory state stores.

These are candidates, not approved dependencies. Licensing, boundary size,
runtime cost, and tests must be checked before code is copied or adapted.

## Test tiers

1. Pure state/reducer/protocol simulation: target extreme throughput.
2. Property, fuzz, and mutation tests: shrink failures to minimal sequences.
3. Component and backend unit tests.
4. API/database deterministic replay.
5. Headless-browser and full-app workflows.
6. Small real-environment/provider confirmation set.

Every result records hardware, environment, seed, fixture version, harness
version, duration, resource use, coverage/activation, and failure class.

## Graph/database work still missing

- Inject Graphify hits and source pointers into each Evo experiment brief.
- Write experiment nodes, scores, gates, traces, failures, environments, and
  decisions back to an experiment graph with artifact hashes.
- Connect UI action -> handler -> API -> backend -> database -> tests -> prior
  failures -> candidate fixes through multi-hop queries.
- Incrementally re-index promoted commits and invalidate stale graph nodes.
- Define a stable evidence schema, failure taxonomy, retention/redaction policy,
  and backups.
- Add retrieval/held-out separation to prevent graph-informed leakage.
- Make the selector uncertainty-aware and penalize missing activation evidence,
  flakiness, environment failure, and repeated rejected approaches.

## Current repository reality

- `world/backend/evo_graph.py` is a useful read-only phase-1 bridge. It supports
  ranked FTS lookup and slice discovery and was previously reported at 12 tests
  passing against the real database.
- It is not connected to experiment brief creation or result write-back.
- The lab queue/racetrack loop sits beside upstream Evo rather than forming a
  clean extension of its experiment engine.
- Both headline races (`backend-query-ranking` and `best-regression-gate`)
  failed without winners.
- The installed `evo` remains stock 0.8.0; fork prototypes are not cleanly
  packaged.
- `DEVELOPMENT-ROADMAP.md` contains the broader capability/test-tier plan. This
  handoff supersedes any implementation-first reading of that plan: discovery
  and source-backed comparison come first.

## Immediate next steps

1. Create a structured `graph-candidates.json` contract: need, query, repo,
   slice, symbol, source pointer, license, boundary, expected benefit, and test.
2. Add a Graphify retrieval hook to Assembly/Evo brief generation using that
   contract; keep it read-only and opt-out per run.
3. Build the first real race around UI event-sequence/state-machine testing:
   at least the ADK Rust `proptest` pattern versus a second graph-sourced model.
4. Build the harness race using mutation/planted-bug detection rate, false
   positives, and runtime as separate measures.
5. Implement experiment evidence write-back and query it in the next cycle.
6. Demonstrate three closed cycles where Graphify changed candidate selection,
   tests selected a winner, and the clean-checkout result reproduced.
7. Define and implement the disposable environment contract: provision a fast
   NixOS-compatible profile, inject candidate code and fixtures, customize it
   from a manifest, run the test tiers inside it, and write environment
   attestation with the result.
8. Add a content-addressed code shuttle and scriptable `export`/`import`/
   `swap`/`patch`/`restore` operations for rapidly moving and editing saved
   candidates without rebuilding an entire checkout.
9. Add Python and Rust as first-class experiment targets, including dependency
   profiles, test/property/fuzz adapters, coverage/traceback/panic
   normalization, and shared evidence records.

## Scope boundary at handoff

The prior native Hermes/Witt/BH/desktop installation thread was explicitly
stopped. Official Hermes Agent code and dependencies were installed under
`~/.hermes/hermes-agent`, but its optional setup wizard was interrupted and is
not part of this objective. Do not resume that tangent unless the user asks.

No BH/Witt source changes were made during that interrupted track.
