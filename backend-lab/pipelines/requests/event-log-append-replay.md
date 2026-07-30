# race: event-log-append-replay
seat: backend-lab
question: best engine for the append-only event streams every app already writes (events.jsonl) — plain JSONL+SSE tail, a real event store, or a record/replay subsystem?
metric: min — ms to append 5k events then replay a 1k-event gap to a reconnecting client, on a ≤2MB fixture log
gate: replayed sequence == committed sequence (same ids, same order, no gaps, no dups); every line of the emitted log parses as JSON with ts+type; two concurrent writers never produce a torn read

## candidate: jsonl-sse-incumbent
source: projects/assembly-office/server.js:375 (serveLive: events.jsonl append + SSE tail with Last-Event-ID replay)
approach: keep the incumbent — append-only JSONL file, tail it over SSE, reconnect replays from the Last-Event-ID cursor. Zero new deps; the protocol A4/B6 contract tests already define its invariants.

## candidate: eventsourcing-sqlite
source: pyeventsourcing_eventsourcing/code/eventsourcing (library repo, verified)
approach: swap the file for the framework's append-only event store on its SQLite backend; replay becomes a ordered read by position. Adds transactional append semantics the JSONL file lacks.

## candidate: echoed-replay
source: mrasu_echoed/code/reporter (library repo, verified)
approach: use echoed's TS record/replay subsystem to capture the stream and replay recorded windows on demand; targets exactly the B6 gap-replay path with a purpose-built tool.
