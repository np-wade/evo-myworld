# evo-myworld Architecture Review
**Author:** Gemini (Antigravity Seat)  
**Date:** 2026-07-19  
**Status:** Completed (First unchecked task in `queues/gemini.md`)

This document provides a top-down architecture review of the `evo` codebase located in `/workspace/evo-myworld`. It details module boundaries, coupling patterns, specific bottlenecks and failure modes under our 12GB WSL2 memory constraint, and guidelines on what to touch versus what not to touch.

---

## 1. Module Boundaries

The codebase is partitioned into distinct components, each with specific roles:

1. **Python Core CLI Interface ([plugins/evo/src/evo/cli.py](file:///workspace/evo-myworld/plugins/evo/src/evo/cli.py)):**
   - **Role:** Entrypoint and command dispatcher. Manages argument parsing, routing, and high-level workflows (such as `init`, `new`, `run`, `done`, `discard`, and `dispatch`).
   - **Boundary:** Interfaces directly with user input and coordinates other modules. Due to its size (~7,500 lines), it houses many subcmd definitions and output formatting functions.

2. **Core Orchestration ([plugins/evo/src/evo/core.py](file:///workspace/evo-myworld/plugins/evo/src/evo/core.py)):**
   - **Role:** Handles the `.evo` workspace configuration, metadata (`meta.json`), config management (`config.json`), annotations (`annotations.json`), and the execution graph (`graph.json`).
   - **Boundary:** Provides low-level workspace filesystem operations, locks (`advisory_lock`), and Git utility functions.

3. **Workspace Executors ([plugins/evo/src/evo/workspace_executor.py](file:///workspace/evo-myworld/plugins/evo/src/evo/workspace_executor.py)):**
   - **Role:** Defines the abstract `WorkspaceExecutor` interface and its implementations:
     - `LocalExecutor` and `GitDirExecutor`: Execute commands on the local machine via subprocess.
     - `RemoteExecutor`: Communicates with remote sandboxes over HTTP using a remote client.
   - **Boundary:** Isolates the CLI and orchestrator from the direct details of process execution.

4. **Lifecycle Backends ([plugins/evo/src/evo/backends/](file:///workspace/evo-myworld/plugins/evo/src/evo/backends/)):**
   - **Role:** Manages the lifecycle of workspace allocation, garbage collection, and cleanup.
     - [protocol.py](file:///workspace/evo-myworld/plugins/evo/src/evo/backends/protocol.py): Defines the `Backend` interface (allocate, discard, release_lease, gc, sweep_orphans).
     - [worktree.py](file:///workspace/evo-myworld/plugins/evo/src/evo/backends/worktree.py): Implements git worktree allocation per experiment.
     - [pool.py](file:///workspace/evo-myworld/plugins/evo/src/evo/backends/pool.py): Manages a pre-built pool of slots, leasing directories to minimize git operations.
     - `remote.py` / `sandbox_providers/`: Providers for Daytona, E2B, AWS, Azure, Modal, and SSH.
   - **Boundary:** Completely abstracts workspace setup and environment isolation.

5. **Agent Interception ([plugins/evo/src/evo/inject/](file:///workspace/evo-myworld/plugins/evo/src/evo/inject/)):**
   - **Role:** Hooks into host-agent interactions.
     - [registry.py](file:///workspace/evo-myworld/plugins/evo/src/evo/inject/registry.py): Registers host sessions and maps them to experiment IDs.
     - [drain.py](file:///workspace/evo-myworld/plugins/evo/src/evo/inject/drain.py): Drains events (stdin, stdout, tool executions) from host sessions to target workspaces, and acts as a security policy filter.
   - **Boundary:** Bridges host sessions (such as Claude Code or Codex) to the running experiment.

6. **Frontier Selection ([plugins/evo/src/evo/frontier_strategies.py](file:///workspace/evo-myworld/plugins/evo/src/evo/frontier_strategies.py)):**
   - **Role:** Implements algorithms (`argmax`, `top_k`, `epsilon_greedy`, `softmax`, `pareto_per_task`) to pick the next candidate branch.
   - **Boundary:** Separates search-policy heuristics from core tree operations.

7. **Observability ([plugins/evo/src/evo/dashboard.py](file:///workspace/evo-myworld/plugins/evo/src/evo/dashboard.py) & [plugins/evo/src/evo/dashboard_supervisor.py](file:///workspace/evo-myworld/plugins/evo/src/evo/dashboard_supervisor.py)):**
   - **Role:** A local Flask web server visualising the experiment tree and run metrics.
   - **Boundary:** Read-only web panel, decoupled from core search execution.

8. **Thin SDK ([sdk/python/src/evo_agent/](file:///workspace/evo-myworld/sdk/python/src/evo_agent/)):**
   - **Role:** Minimal, dependency-free wrapper for the benchmark targets to report scores (`run.report`) and gate checks (`gate.check`).
   - **Boundary:** Decoupled reporting layer, communicating with the harness via environment variables (`EVO_RESULT_PATH`, `EVO_TRACES_DIR`) or stdout.

---

## 2. Coupling Patterns

- **CLI-Core-Backend Tight Coupling:**
  - `cli.py` has high coupling with `core.py` and the backend protocol implementations. It frequently imports core utilities and directly mutates workspace state files.
- **Loose Integration of SDK:**
  - The Python SDK (`sdk/python/src/evo_agent/`) is highly decoupled. It interacts with the runner purely via standard interfaces: environment variables (`EVO_RESULT_PATH`, `EVO_TRACES_DIR`) or printing JSON to stdout.
- **State Coupling via JSON Files:**
  - The shared state is stored in `.evo/graph.json` and `.evo/config.json`. Since multiple processes read and write these files, advisory locking (`advisory_lock` in [locking.py](file:///workspace/evo-myworld/plugins/evo/src/evo/locking.py)) is used to serialize state transitions.

---

## 3. WSL2 12GB RAM Constraints: What Breaks First?

Running local experiments on a WSL2 container with only 12GB RAM and 24GB swap imposes strict performance limits:

1. **Parallel Local Subagents:**
   - Spawning concurrent workers via local worktrees/pools runs multiple host agent processes. Since each agent process loads a Python runtime, interacts with LLM endpoints, and runs compilation/tests, a concurrency count of 3+ will cause high memory spikes, triggering WSL2 OOM killing or disk thrashing.
2. **Git Worktree Memory & I/O Overhead:**
   - In `worktree.py`, allocating a fresh worktree runs `git worktree add`. In large repositories, this checks out hundreds of megabytes of files, putting massive pressure on the OS page cache and I/O scheduler.
3. **Graph Databases & Indexing:**
   - Loading large SQLite indexes (e.g. the 9.2M-node `index.db` used by `graphify-app`) or running a local FalkorDB container can easily exhaust 12GB of memory. High-hop Cypher queries or large full-text search index lookups must be strictly capped.
4. **Trace Log Accumulation:**
   - In `scratchpad.py` and trace diagnostics, loading a large window of trace logs (`task_*.json`) into memory at once to compute metrics or render trees will spike the Python process's heap.

---

## 4. What to Touch vs. What NOT to Touch

### What NOT to Touch:
- **Upstream Reference:** `/workspace/evo-hq/` must remain untouched as it is the clean upstream reference harness.
- **CLI Core Logic (`cli.py` / `core.py`):** Do not modify core pathing, locking, or command routers directly unless implementing shared features that pass the harness tests.
- **Uncommitted Files Guard:** Do not bypass the uncommitted changes check in `pool.py:_validate_slot_basics`. Refusing to overwrite user edits is a key safeguard.

### What to Touch / Extend:
- **World Folder:** Keep all Gemini experiments, prototypes, and review files inside `world/gemini/`.
- **Custom Backends:** Implement new resource managers by writing classes conforming to `Backend` in `backends/protocol.py`.
- **Frontier Selection:** Customize search logic inside `frontier_strategies.py` by implementing a new `_pick_*` method.
- **Gates:** Add regression, memory budget, or correctness gates to filter branches before they run.
