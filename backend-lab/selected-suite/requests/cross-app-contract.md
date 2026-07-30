# race: cross-app-contract
seat: backend-lab
question: which versioned cross-app contract gives the strongest interoperability and forward compatibility across the local agent/app ecosystem?
metric: max — conformance accuracy over valid, malformed, version-skewed, and foreign-metadata fixtures; ties broken by round-trip latency
gate: 100% required-field/version/error conformance; valid records round-trip without loss; unknown vendor metadata remains namespaced and does not break readers

## candidate: evo-versioned-jsonl
source: projects/evo-myworld/plugins/evo/src/evo/runner_bridge.py and plugins/evo/src/evo/backends/environment.py
approach: versioned JSONL request/response and evidence envelopes over stdio; extend the existing Python↔Rust execution boundary into a shared app envelope.

## candidate: claw-cip-profile
source: filing-cabinet/library-base/repos/zeroclaw-labs_claw-standards/spec/cip-1.0-draft.md
approach: conform to the CIP-pinned JSON-RPC/A2A task lifecycle, method errors, capability honesty, and vendor metadata namespace rules.

## candidate: thrift-idl
source: filing-cabinet/library-base/repos/apache_thrift/code
approach: define the shared task/event/artifact contract in Thrift IDL and generate clients for each supported app language.

## candidate: baml-typed-json
source: filing-cabinet/library-base/repos/BoundaryML_baml/code
approach: use BAML typed structured outputs for agent-facing payloads while retaining JSON transport and explicit version negotiation.
