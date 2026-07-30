# Selected backend race results

## Cross App Contract

| Candidate | Kind | Score | Gate | Status |
|---|---:|---:|---:|---|
| versioned-jsonl | reference | 1.0000 | PASS | scored |
| claw-cip-profile | technique-port | 1.0000 | PASS | scored |
| witt-brain-jsonrpc-service | pending | — | — | pending |
| baml | pending | — | — | pending |
| apache-thrift | pending | — | — | pending |
| apache-fory | pending | — | — | pending |

## Agent Lifecycle

| Candidate | Kind | Score | Gate | Status |
|---|---:|---:|---:|---|
| evo-mission-dag | technique-port | 0.7143 | PASS | scored |
| witt-spine-lanes | technique-port | 0.7143 | PASS | scored |
| pueue-queue | technique-port | 0.7143 | PASS | scored |
| cowork-os | pending | — | — | pending |
| agent-control | pending | — | — | pending |
| crabfleet | pending | — | — | pending |

## Identity Trace

| Candidate | Kind | Score | Gate | Status |
|---|---:|---:|---:|---|
| normalized-name-trace-id | reference | 1.0000 | PASS | scored |
| agent-trace-envelope | technique-port | 1.0000 | PASS | scored |
| cosine-resolution | technique-port | 1.0000 | PASS | scored |
| ontocast-aligner | pending | — | — | pending |
| flyline | pending | — | — | pending |

## Gateway Routing

| Candidate | Kind | Score | Gate | Status |
|---|---:|---:|---:|---|
| hardcoded-ports | reference | 0.4286 | FAIL | scored |
| prefix-front-door | technique-port | 1.0000 | FAIL | scored |
| health-registry-router | technique-port | 1.0000 | PASS | scored |
| mitmproxy | pending | — | — | pending |
| pingora | pending | — | — | pending |

## Hybrid Recall

| Candidate | Kind | Score | Gate | Status |
|---|---:|---:|---:|---|
| fts-only | reference | 0.6000 | FAIL | scored |
| vector-only | reference | 0.8000 | FAIL | scored |
| rrf-hybrid | technique-port | 1.0000 | PASS | scored |
| qdrant-native | pending | — | — | pending |
| turso-native | pending | — | — | pending |
| tantivy | pending | — | — | pending |
| meilisearch | pending | — | — | pending |

## Graph Lineage

| Candidate | Kind | Score | Gate | Status |
|---|---:|---:|---:|---|
| memory-adjacency | reference | 1.0000 | PASS | scored |
| sqlite-edges | reference | 1.0000 | PASS | scored |
| falkordb | pending | — | — | pending |
| supermemory-graph | pending | — | — | pending |
| hypermem | pending | — | — | pending |

## Self Improvement

| Candidate | Kind | Score | Gate | Status |
|---|---:|---:|---:|---|
| argmax | reference | 0.5800 | FAIL | scored |
| evo-pareto | technique-port | 0.7200 | PASS | scored |
| flywheel-ucb | technique-port | 0.7200 | PASS | scored |
| evoagentbench | pending | — | — | pending |
| rd-agent | pending | — | — | pending |
| opik-optimizer | pending | — | — | pending |
| prompt-engineer | pending | — | — | pending |

Technique-port scores validate the arena; they do not establish that the full upstream repository wins.
Pending native adapters must run before architectural promotion.
