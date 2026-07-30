# race: live-tail-fanout
seat: backend-lab
question: lowest-latency way to fan a live-appended events.jsonl out to multiple watching clients — SSE tail, socket.io rooms, or a normalized tailer?
metric: min — p95 ms from file append to client receipt at 100 events/s with 3 concurrent clients
gate: zero missed and zero duplicated events per client across one induced reconnect each (Last-Event-ID or equivalent cursor)

## candidate: sse-tail-incumbent
source: projects/assembly-office/server.js:375 (serveLive SSE tail with shared 3s retry hint and Last-Event-ID replay)
approach: incumbent — fs watch/tail of events.jsonl, one SSE stream per client, cursor-based reconnect. Already in production shape; baseline to beat.

## candidate: socketio-rooms
source: socketio_socket.io/code (library repo, verified; already referenced by assembly-office's retry-jitter comment)
approach: publish each appended line into a socket.io room; clients get auto-reconnect with backoff and packet acknowledgment instead of hand-rolled cursors.

## candidate: flyline-tailer
source: HalFrgrd_flyline/code (library repo, verified)
approach: flyline tails and normalizes the JSONL into its real-time telemetry feed; clients subscribe to the normalized stream rather than the raw file.
