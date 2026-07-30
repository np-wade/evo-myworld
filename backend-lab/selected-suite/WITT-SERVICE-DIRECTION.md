# Witt direction: service, not CLI

Decision recorded 2026-07-28: Witt is no longer being built as a user-facing
CLI.

## Intended shape

```text
Desktop / phone / web
        |
        v
Witt Link Server
  - rooms and messages
  - authentication
  - backend health and routing
  - uploads and event stream
        |
        v
Witt Brain background service
  - local model/provider boundary
  - JSON-RPC request/stream contract
  - memory recall/store interface
  - ZeroClaw tools/runtime behind the service
        |
        +--> Witt Spine libraries
        |    scheduling, rails, storage, recall, metrics
        |
        +--> Evo, only for gated experiments and promotion
```

## Keep

- `witt-link-server` as the single front door.
- `witt-brain` as a background service with a narrow JSON-RPC/API contract.
- `witt-spine` as internal backend libraries, not something the user launches.
- Desktop/phone controls for start, stop, health, rooms, approvals, events, and
  model choice.

## Stop depending on

- A person typing Witt commands in a terminal.
- `/projects/witt` being the product entry point.
- Multiple components each owning rooms, routing, memory, or service lifecycle.
- Automatic self-modification without held-out evaluation and rollback.

No repository is deleted by this decision. The old CLI can remain as reference
code until its useful ZeroClaw integrations are moved behind Witt Brain.

## Required service tests

1. Desktop/phone can complete a request without invoking a CLI executable.
2. Witt Link can discover Witt Brain health and model readiness.
3. A request carries one `trace_id` through gateway, brain, tool calls, memory,
   and response.
4. Cancellation reaches the active local generation/tool run.
5. Restart preserves durable room/task state and reconnects cleanly.
6. A dead brain produces a bounded, actionable gateway error or configured
   fallback—never an unbounded hang.
7. Tool permissions, budgets, and paths are enforced below the UI.
8. Memory is scoped by room/project and cannot cross scopes silently.
9. Evo cannot promote a candidate without independent held-out verification.
10. Everything needed for normal operation is controllable from the graphical
    surfaces.
