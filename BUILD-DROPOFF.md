# Evo build dropoff

Date: 2026-07-19

## What was built

The first environment-first compatibility slice is implemented across Evo and
Graphify. A second foundation slice now makes Graphify evidence readable in
bounded source ranges and gives Evo a durable, safe path toward recursive agent
operation.

### Disposable environment support

- Versioned environment manifests and evidence envelopes:
  `plugins/evo/src/evo/backends/environment.py`
- Sandbox manifest plumbing, fixture upload, setup/customization commands,
  identity capture, digest persistence, and Rust-runner evidence parsing:
  `plugins/evo/src/evo/backends/protocol.py`
  `plugins/evo/src/evo/backends/remote.py`
- Pinned Python/Rust Nix environment profile:
  `plugins/evo/env/nixos/flake.nix`

The existing remote provider path remains backward-compatible when no
environment manifest is configured.

### Python and Rust compatibility

- Rust environment runner:
  `plugins/evo/bin/evo-env-runner/`
- Python JSONL control bridge:
  `plugins/evo/src/evo/runner_bridge.py`
- Shared language adapters and normalized test evidence:
  `plugins/evo/src/evo/language_adapters.py`

The compatibility boundary is versioned JSONL over stdio. Python remains the
orchestration layer; Rust provides the fast isolated execution layer. Either
runtime can be selected as the test command inside the same environment.

### Code and fixture mobility

- Content-addressed artifact store:
  `plugins/evo/src/evo/artifacts.py`
- Executable shuttle:
  `plugins/evo/bin/evo-artifact`
- Installed CLI entry point:
  `evo-artifact`

Supported operations include deterministic SHA-256 storage, export/import,
restore, swap with backup, bounded unified diffs, and staged script transforms.
Symlinks and path traversal are rejected.

### Graphify evidence surface

In `coding/docker-envs/projects/graphify-app`:

- `src/evidence-store.js`
- `src/evidence-server.js`
- `test/evidence.test.js`

Read-only endpoints:

- `/api/evidence`
- `/api/evidence/environment`
- `/api/evidence/artifacts`

The adapter discovers `EVO_ROOT`, reads attempt metadata, exposes language and
runtime fields, and redacts artifact paths outside the Evo root.

### Graphify source-range retrieval

In `coding/docker-envs/projects/graphify-app`:

- Read-only range implementation and model/tool schema:
  `src/source-slices.js`
- Express route adapter:
  `src/source-slice-server.js`
- Inspector range reader, source display, and copy action:
  `public/app.js`, `public/style.css`, `public/index.html`
- Terminal parity command:
  `scripts/gfy.mjs` (`gfy source <repo> <file> <start> <end>`)

The API is:

- `GET /api/repos/:id/source?file=&startLine=&endLine=`
- `GET /api/tools/read-source-line-range`

It accepts 1-indexed inclusive ranges and returns numbered text, effective
range, total lines, truncation state, and a SHA-256 content hash. Reads are
limited to 500 lines and 5 MiB source files. Absolute paths, traversal,
non-regular files, binary content, and symlinks escaping the selected indexed
repository are rejected. This is the intended retrieval primitive for agents
and lower-cost coding models: retrieve a cited slice, not a whole checkout.

### Recursive mission and agent control foundation

In Evo:

- Durable mission DAG overlay in the existing `.evo/graph.json`:
  `plugins/evo/src/evo/missions.py`
- Graph schema initialization:
  `plugins/evo/src/evo/core.py`
- CLI control surfaces:
  `plugins/evo/src/evo/cli.py`
- Usage documentation:
  `plugins/evo/README.md`
- Unit coverage:
  `tests/unit/test_missions.py`

`evo mission` now creates and controls persistent `research`, `build`,
`verify`, and `integrate` missions. A mission has a bounded brief, explicit
acceptance conditions, dependency IDs, evidence references, an optional owning
experiment, and per-mission depth/child caps. Ready work is unlocked only by
successful dependencies; claims are locked and idempotent for the same owner;
cancellation cascades through child missions.

`evo agent` is intentionally a thin CLI control plane over the existing
dispatch and directive systems rather than a new scheduler. It exposes
`start`, `list`, `status`, `wait`, `stop`, `steer`, `receipt`,
`message-status`, and `watch`. Job state remains owned by Evo dispatch and
message delivery/acknowledgement remains owned by the existing inject queues.
`agent start` has exactly the host support of `evo dispatch`; it does not claim
to launch an unsupported host.

## Point reached

The system now has the minimum closed-loop primitives to grow safely:

```text
Graphify search/context
  -> bounded, hash-addressed source slice
  -> durable research/build/verify/integrate mission
  -> existing Evo dispatch / isolated environment / gates
  -> evidence and outcome retained in Evo state
  -> dependent mission unlocked or blocked
```

This is not yet an autonomous scheduler or a dashboard control plane. The
current implementation deliberately stops short of automatic self-spawning,
automatic promotion, or generic-host job launching until those operations have
budget, capability, and independent-verification controls.

## Research basis for the autonomy design

Three read-only research passes followed `graphify-app/GRAPH-FIRST.md`,
including topic entries, overview images, self-contained slices, and real code:

- **CoWork-OS:** durable task/event/session records, permission assertions,
  recursive child-task creation, and parent cancellation propagation.
- **xai/grok-build:** explicit pending/active/completed maps, parent-session
  scoping, persisted fallback state, and cancellation/wait race handling.
- **Evo and Graphify themselves:** Evo dispatch/directive/acknowledgement is
  already the correct lifecycle owner; Graphify now supplies bounded source
  evidence through its CLI/API rather than owning mutations or scheduling.

The adopted rule is therefore: mission dependencies describe intent; the Evo
experiment tree describes Git lineage; Graphify provides immutable/read-only
context; an independent verify mission is required before promotion.

## Objectives established

The agreed program objectives are:

1. A capability-scoped autonomous agent control plane with durable lifecycle,
   budgets, path/command permissions, audit events, pause/resume/cancel, and
   safe steering.
2. Full CLI parity for that control plane (`evo agent ...`), suitable for both
   humans and agents; the initial adapter is now implemented.
3. A bounded recursive mission graph that turns a goal into research, build,
   verify, and integration work; the initial persistent DAG is now implemented.
4. Graphify-backed candidate cards and experiment-brief injection, using exact
   source slices, repository IDs, licenses, expected benefit, and test plans.
5. Candidate races under identical seeds, fixtures, environments, gates, and
   activation proof; only empirical winners may be promoted.
6. Structured evidence write-back: outcomes, failures, environment identity,
   artifacts, and decisions become queryable lineage for the next cycle.
7. Generated UI interaction/state-machine simulation and API/database replay
   tiers before expensive browser/full-environment confirmation.
8. An evidence-aware harness factory that can race tests, benchmarks, mutation
   suites, and fixtures by detection rate, false positives, runtime, and
   reproducibility.
9. Continuous repository observation that turns changed code, failures, and
   stale graph indexes into bounded evidence-backed missions.
10. Promotion/rollback and portfolio selection: independent verification,
    clean-checkout reproduction, retained losing evidence, and cost/risk-aware
    allocation of available agents and model tiers.

## Verification

- Rust `cargo fmt -- --check`: passed.
- Rust `cargo test`: 5 passed.
- Rust JSONL prepare/run/collect/destroy smoke test: passed.
- Python-to-Rust bridge smoke test: passed.
- Artifact store/export/import/restore/diff smoke tests: passed.
- Graphify focused Node tests: 2 passed.
- Graphify source-range tests: 3 passed, including traversal and escaping
  symlink rejection; focused evidence tests also passed.
- Mission DAG tests: 3 passed (dependency unlock/claim, caps/cancellation/
  evidence, and agent CLI delegation) using a temporary lock shim because the
  host lacks `portalocker`.
- Mission CLI create/list end-to-end smoke test: passed.
- Mission/agent parser smoke test and Python syntax compilation: passed.
- `git diff --check`: passed for changed implementation files.

## Known local limitations

- Native Python pytest could not run on this host because `pytest` and
  `portalocker` are unavailable.
- The mission DAG has not yet been surfaced through dashboard HTTP endpoints,
  attached automatically to dispatch-created experiments, or connected to
  Graphify brief injection/write-back. Those are the next integration steps,
  not evidence that autonomous scheduling already exists.
- Full Graphify `npm test` was stopped because existing graph/index tests did
  not produce output for over a minute. The focused evidence tests passed.
- Nix/NixOS is not installed on this host, so the flake was added but not
  locally built. The Rust runner currently supports host and Docker modes.
- The Rust runner is intentionally separate from the existing fast
  `evo-hook-drain` binary; provisioning does not belong in that hot path.

## Useful commands

```bash
cargo test --manifest-path plugins/evo/bin/evo-env-runner/Cargo.toml
cargo build --manifest-path plugins/evo/bin/evo-env-runner/Cargo.toml
PYTHONPATH=plugins/evo/src python3 -m evo.artifacts --help
node --test test/evidence.test.js test/scanner.test.js

# Graphify: retrieve only the source required for a task
node scripts/gfy.mjs source <repo-id> <source-file> <start-line> <end-line>

# Evo: create bounded work and control an agent through the existing lifecycle
evo mission create --title 'Research candidates' --kind research --brief 'Read cited Graphify slices.'
evo mission list --status ready
evo agent list --running
evo agent steer --exp-id exp_0001 'Read the cited source range before editing.'
```

## Existing worktree note

The repositories already contained unrelated user changes before this build.
Those changes were preserved. No commit, reset, or destructive cleanup was
performed.
