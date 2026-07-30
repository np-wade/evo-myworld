# race: witt-background-service
seat: backend-lab
question: which service boundary finishes Witt as a controllable local ZeroClaw-based agent without requiring a user-facing CLI?
metric: max — passed end-to-end service scenarios for health, request, streaming, cancellation, tool call, scoped memory, restart, and bounded failure; ties broken by p95 request overhead
gate: desktop/phone completes the fixture without invoking a CLI; one trace id spans every hop; cancellation terminates active work; dead service returns within 5s; unauthorized tools and cross-room memory are blocked

## candidate: witt-link-to-witt-brain-jsonrpc
source: projects/witt-link-server/src and projects/witt-brain/src/interface/server.rs
approach: keep Witt Link as the HTTP/WebSocket front door and run Witt Brain as a loopback/Unix-socket JSON-RPC background service owning the local provider, memory API, and ZeroClaw tools.

## candidate: zeroclaw-a2a-sidecar
source: filing-cabinet/library-base/repos/zeroclaw-labs_zeroclaw/code and filing-cabinet/library-base/repos/zeroclaw-labs_claw-standards/spec/cip-1.0-draft.md
approach: expose ZeroClaw behind a bundled A2A/ACP-compatible sidecar and let Witt Link act as the authenticated client and UI gateway.

## candidate: witt-link-embedded-runtime
source: projects/witt-link-server/src and filing-cabinet/library-base/repos/zeroclaw-labs_zeroclaw/code
approach: embed the runtime directly in the gateway process, removing an IPC hop but coupling crashes, upgrades, memory, and permissions to the front door.
