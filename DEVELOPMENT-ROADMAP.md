# evo-myworld development roadmap

This is the source of truth for turning the current prototypes into one
evidence-driven Evo application. A component is not "wired" merely because
code or notes exist: it must run in the target environment, emit structured
evidence, and influence a later selection.

## End-to-end loop

1. Observe the repository, application, prior experiments, and Graphify data.
2. Retrieve relevant implementations, tests, failures, and dependency context.
3. Generate at least two bounded candidate paths: code, harness, instruction,
   guardrail, backend, environment, or app behavior.
4. Exercise candidates through the cheapest valid test tier first.
5. Diagnose failures into structured categories rather than retaining logs only.
6. Promote survivors through progressively more realistic test tiers.
7. Select by correctness gates first, then performance, robustness, cost,
   usability, and maintainability.
8. Record winners, losers, causal evidence, and activation proof in Evo state
   and the Graphify-backed knowledge layer.
9. Feed that evidence into the next retrieval and selection cycle.

## Required development tracks

### Code and harness evolution

- Race implementations under identical inputs, seeds, resources, and gates.
- Require activation beacons or coverage proving the changed path ran.
- Preserve per-task scores and reproduce winners from a clean checkout.
- Treat tests and benchmarks as candidates. Compare them with planted-bug and
  mutation suites, including detection rate, false positives, and runtime cost.
- Detect benchmark gaming, leakage, flaky tests, and unexercised candidate code.
- Version harnesses and record which harness produced every score.

### Agent instructions, guidelines, and guardrails

- Race scoped instruction variants on a frozen diagnostic task cohort.
- Measure correctness, completion, retries, tool use, token/cost budget,
  destructive-action attempts, and unsupported claims across agents and seeds.
- Keep provider adapters separate from shared task doctrine.
- Add pre-action policy checks, path ownership, secret redaction, command risk
  classification, turn budgets, and explicit destructive-action gates.
- Test guardrails with expected allow/deny fixtures and measure false blocks.

### Apps and interaction simulation

- Model each control as explicit state transitions: click, double-click, press,
  hold, repeat, release, drag, focus, blur, keyboard, touch, cancellation,
  timeout, reconnect, and concurrent input.
- Generate event sequences against pure reducers/state machines at very high
  throughput. The million-simulations target belongs here, without a browser,
  network, model, or database.
- Use property/model-based tests for invariants such as “release always ends
  hold,” idempotency, valid navigation, and no impossible states.
- Replay a smaller selected corpus through component/DOM tests, real browsers,
  then full frontend-backend-database runs.
- Capture heavyweight screenshots and traces only for promoted failures or
  representative cases.

### Frontend, backend, environments, and data

- Validate API schemas, fixtures, errors, streams, authentication, retries,
  cancellation, and version compatibility.
- Classify failures as UI state, transport, API validation, backend logic,
  database, environment, or external provider.
- Test slow responses, disconnects, duplicate events, stale data, contention,
  and provider limits.
- Define reproducible native-Ubuntu and container profiles with tool, model,
  dependency, filesystem, environment-variable, and resource manifests.
- Run environment smoke tests first and track environment identity with results.
- Normalize events, outcomes, traces, diffs, coverage, costs, model/tool metadata,
  and diagnoses into queryable records with lineage, migrations, integrity,
  retention, deduplication, and redaction.
- Store large artifacts outside the graph and retain content-addressed references.

### Near-term TODOs: disposable environments and code mobility

- [ ] Define an `EnvironmentSpec`/manifest for each run: pinned base image or
  Nix flake/lock, packages, injected environment, mounts, seed, resource and
  network policy, setup/customization commands, and artifact paths.
- [ ] Build a fast disposable environment runner. Reuse the existing sandbox
  provider lifecycle, git-bundle workspace shipping, and Rust isolation pieces;
  provision once, inject candidate code and fixtures, customize from the
  manifest, run every selected test tier inside the environment, then collect
  an attestation and evidence bundle.
- [ ] Add a content-addressed code shuttle with explicit `export`, `import`,
  `swap`, `patch`, and `restore` operations. It must move saved candidates,
  fixtures, scripts, and results in and out without copying an entire checkout
  on every iteration, while preserving commit/hash/provenance.
- [ ] Add scriptable candidate transforms so an experiment can quickly apply a
  bounded edit, run the same fixture/gates, and restore or compare the result.
- [ ] Make Python first-class: environment profiles, dependency locking,
  pytest/property/fuzz adapters, coverage and traceback normalization, and
  Python-to-runner evidence exchange.
- [ ] Make Rust first-class: Cargo workspace/profile support, deterministic
  fixture generation, `cargo test`/property/fuzz adapters, coverage and panic
  normalization, and Rust-to-runner evidence exchange.
- [ ] Add environment-equivalence checks proving that local fast runs and the
  NixOS/full-environment confirmation run used the same candidate, fixtures,
  seed, harness contract, and declared toolchain inputs.

## Graphify and database integration

Graphify is the knowledge and selection backbone, not a sidecar text search.

### Graph model

- Repository nodes: files, symbols, calls, imports, tests, UI controls, routes,
  schemas, database objects, configurations, and owners.
- Experiment nodes: candidate, parent, diff, agent, model, environment, harness,
  task, score, gate, trace, failure, artifact, and decision.
- Evidence edges: `IMPLEMENTS`, `CALLS`, `COVERS`, `EXERCISED_BY`, `FAILED_AT`,
  `RAN_IN`, `PRODUCED_BY`, `COMPARED_WITH`, `BEAT`, `REGRESSED`, `PROMOTED`, and
  `DERIVED_FROM`.

### Required services

- Read-only retrieval returning source slices with stable symbol/commit IDs.
- A validated experiment writer for results and artifact references; source
  indexes remain immutable during an experiment.
- Selection combining graph relevance and empirical outcomes. Graph proximity
  proposes candidates; gates and measured evidence decide winners.
- Incremental re-indexing after promotion and stale-node invalidation.
- Multi-hop queries connecting a UI action to handler, API, backend function,
  database object, tests, prior failures, and candidate fixes.
- Provenance, access control, backups, health checks, and schema versions for
  SQLite/FTS, FalkorDB, and application databases.

Never select code only because it is graph-central or graph-near. Separate
retrieval evidence from held-out confirmation, penalize missing activation
evidence and flaky results, and retain losing evidence to avoid rediscovery.

## Test pyramid and throughput

| Tier | Subject | Target scale | Promotion condition |
|---|---|---:|---|
| 0 | Pure functions, reducers, state/protocol models | up to millions/sec where feasible | invariants hold |
| 1 | Property, fuzz, and mutation tests | thousands to millions/run | no crash; mutation score improves |
| 2 | Component and backend unit tests | thousands/run | contracts and coverage pass |
| 3 | API/database integration | hundreds/run | deterministic replay passes |
| 4 | Headless browser/app workflow | tens to hundreds/run | journeys and traces pass |
| 5 | Real provider/full environment | small confirmation set | reproducible end-to-end outcome |

Throughput reports must state hardware, environment, fixture size, seed, and
warmup. One million simulations is a benchmark to earn, not a promise for real
browser or network tests.

## Current wiring assessment (2026-07-19)

- **Working:** upstream Evo 0.8.0 CLI, experiment tree, gates, worktree/remote
  backends, dashboard, host support, and a demonstrated sample run.
- **Working prototypes:** Assembly planner, read-only Graphify FTS/slice bridge,
  bench, gates, dashboard river endpoint, and UCB1 strategy.
- **Partially wired:** cycle self-review and seat queues run beside Evo but have
  not demonstrated sustained improvement.
- **Not wired:** Graphify brief injection, experiment write-back, multi-hop
  failure retrieval, incremental re-indexing, UI simulation, harness evolution,
  environment equivalence, structured failure taxonomy, and evidence-driven
  instruction/guardrail promotion.
- **Known failures:** both requested races produced no winner; installed `evo`
  is stock 0.8.0 rather than this fork; core additions import `world/`
  prototypes and are not packaged cleanly for normal installation.

## Milestones

1. Package river/UCB inside the plugin, install the fork editable on Ubuntu, and
   run upstream tests.
2. Define the evidence schema and failure taxonomy.
3. Build Graphify retrieval injection and result write-back with provenance.
4. Implement tier-0 interaction models and click/hold/release generation; record
   honest throughput baselines.
5. Add API/database replay and browser confirmation tiers.
6. Repair and complete the backend-code and regression-harness races.
7. Run instruction and guardrail races on a frozen diagnostic cohort.
8. Demonstrate three complete cycles where graph evidence changes candidate
   choice and the winner reproduces from a clean checkout.
