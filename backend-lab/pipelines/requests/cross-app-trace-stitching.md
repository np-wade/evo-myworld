# race: cross-app-trace-stitching
seat: backend-lab
question: which trace envelope lets one operation spanning assembly-office → witt-link-server → sidecar be joined into a single ordered trace by id?
metric: max — % of hops joinable by trace id into the correct causal order across a synthetic 3-app operation
gate: a complete trace has exactly one event per expected hop in causal (ts-monotonic) order with zero orphan events, and every emitted event line still parses as JSON with ts+type

## candidate: agent-trace-schema
source: cursor_agent-trace/code/index.ts + code/schemas.ts (library repo, verified)
approach: adopt the agent-trace typed event envelope (ts, step type, ids) as the canonical schema; small TS shim at each hop stamps trace_id. Lightweightest schema with an existing type definition.

## candidate: flyline-envelope
source: HalFrgrd_flyline/code (library repo, verified)
approach: run each app's events.jsonl through flyline as the normalizing telemetry logger; it emits one ordered feed with a uniform envelope, stitching downstream of the apps instead of inside them.

## candidate: runid-convention-incumbent
source: projects/assembly-office/server.js:375 (run-dir events.jsonl keyed by run id) + projects/witt-brain-desktop/src/paths.js:10 (WITT_LINK_SERVER_DIR shared stream)
approach: no new dependency — standardize on the existing run-id field as trace_id and require every hop to echo it; pure convention, enforced by the B1 schema-conformance test.
