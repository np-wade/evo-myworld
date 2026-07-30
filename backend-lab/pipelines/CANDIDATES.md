# CANDIDATES — pipelines (data routing + observability)

All repo paths verified with `ls` under `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/` on 2026-07-27.
Catalog: `/home/npwad/coding/docker-envs/projects/evo-myworld/repository-catalog.md` (note: lives one level above `racetrack/`, not inside it).
Box constraints: 12GB RAM, seconds-not-minutes benchmarks, <10MB fixture data.

## Event-bus / log candidates

| candidate | catalog category | verified repo path | technique | what we'd test | weight/deps + runs-on-box? | verdict |
|---|---|---|---|---|---|---|
| pyeventsourcing_eventsourcing | 5 message/event | `repos/pyeventsourcing_eventsourcing/code/eventsourcing` | Python event-sourcing framework; append-only event store with SQLite backend | replace ad-hoc `events.jsonl` with a real event store: append throughput, replay fidelity, ordering | 11M repo; pure Python + sqlite3; pip-install, runs on box | RACE NOW |
| mrasu_echoed | 5 message/event | `repos/mrasu_echoed/code/reporter` | TS event recording + replay subsystem | record/replay correctness on a captured `events.jsonl` fixture; replay == original sequence | 8.9M repo; TS + jest; npm install, runs on box | RACE NOW |
| socketio_socket.io | 5 message/event | `repos/socketio_socket.io/code` | realtime bidirectional event fanout (rooms, reconnect cursors) | live-tail fanout vs incumbent SSE tail (`assembly-office/server.js:375`): p95 append→client latency, no loss on reconnect | 30M repo; JS/TS; already partially used by assembly-office (see retry-jitter comment in `server.js`); runs on box | RACE NOW |
| apache_kafka | 4 data, 5 message/event | `repos/apache_kafka` | distributed event streaming platform | — | JVM + ZooKeeper/KRaft, minutes-scale startup, RAM-hungry on 12GB | SKIP (violates seconds-not-minutes; massive overkill for localhost hops) |
| spotify_docker-kafka | 5 message/event | `repos/spotify_docker-kafka` | dockerized Kafka cluster | broker-based bus if a future race justifies Kafka | needs docker + JVM images | LATER (only if kafka ever wins a race) |
| apache_dubbo | 5 message/event, 30 networking | `repos/apache_dubbo` | JVM RPC + messaging | — | Java build chain | SKIP (JVM, wrong granularity for file/socket seams) |
| apache_openwhisk (+cli) | 5 message/event | `repos/apache_openwhisk`, `repos/apache_openwhisk-cli` | serverless event-driven execution | — | requires docker cluster | SKIP (platform, not a library; heavy) |
| quinn-rs_quinn | 5 message/event, 30 networking | `repos/quinn-rs_quinn` | async QUIC transport | encrypted transport for cross-machine hops | Rust crate, cargo build (minutes) | LATER (no cross-machine seam exists today; Unix socket/TCP suffice) |
| leandrocp_awesome-cqrs-event-sourcing | 5 message/event | `repos/leandrocp_awesome-cqrs-event-sourcing` | reading list | — | docs only, no runnable code | SKIP (reference material, not a candidate) |
| PipeWire_pipewire | 5 message/event | `repos/PipeWire_pipewire` | low-latency A/V event daemon | — | system daemon, A/V domain | SKIP (wrong domain) |

## Tracing / APM candidates

| candidate | catalog category | verified repo path | technique | what we'd test | weight/deps + runs-on-box? | verdict |
|---|---|---|---|---|---|---|
| cursor_agent-trace | 21 observability | `repos/cursor_agent-trace/code/index.ts`, `code/schemas.ts` | AI-agent execution step tracer with a typed event schema | cross-app trace-id envelope: can one schema cover assembly-office → witt → sidecar hops and stay JSONL-appendable | 1.3M repo; single TS file + bun; runs on box | RACE NOW |
| HalFrgrd_flyline | 21 observability | `repos/HalFrgrd_flyline/code` (Cargo) | real-time telemetry pipeline logger | normalize + tail heterogeneous `events.jsonl`/`audit.jsonl` streams into one ordered telemetry feed | 5M repo; Rust, cargo build ~1 min amortized; runs on box | RACE NOW |
| netdata_netdata | 21 observability | `repos/netdata_netdata` | real-time perf/health monitoring agent | host-level health of the sidecar fleet (:8788–:8793, :11434) | C daemon; apt package available, but full build huge | LATER (system-level, not hop-level; revisit for heartbeat freshness dashboards) |
| comet-ml_opik | 21 observability | `repos/comet-ml_opik` | LLM app tracing/eval platform | trace the Ollama-shared LLM hops (seam 10) | Python + server components, heavier deps | LATER (only for LLM-hop tracing race) |
| apache_hertzbeat | 21 observability | `repos/apache_hertzbeat` | real-time monitoring + alerting | heartbeat freshness alerts on the 7 sidecar ports | Java | LATER (JVM weight; netdata covers same ground cheaper) |
| zeroclaw-labs_zeroclaw-metrics | 21 observability | `repos/zeroclaw-labs_zeroclaw-metrics` | telemetry exporter for agents | metric export format for sidecar heartbeats | small Rust crate | LATER |
| apache_skywalking | 21 observability | `repos/apache_skywalking` | APM + observability mesh | — | Java + Elasticsearch backend | SKIP (far too heavy for a 12GB localhost box) |
| PostHog_posthog | 21 observability | `repos/PostHog_posthog` | product analytics platform | — | full web platform, many services | SKIP (product analytics, not pipeline observability) |
| Roy3838_Observer | 21 observability | `repos/Roy3838_Observer` | system resource monitor daemon | — | resource-only, no trace concept | SKIP (no per-hop visibility) |
| CSIRT-MU_Stream4Flow | 21 observability | `repos/CSIRT-MU_Stream4Flow` | IP flow monitoring | — | needs Kafka/Spark stack | SKIP (network-flow domain, heavy deps) |
| NVIDIA_SkillSpector | 21 observability | `repos/NVIDIA_SkillSpector` | skill execution profiler | — | profiling scope, not pipeline hops | SKIP (wrong seam) |
| deepsense-ai_seahorse | 21 observability | `repos/deepsense-ai_seahorse` | Spark workflow lineage UI | — | Spark-only | SKIP (no Spark in the system) |
| koala73_worldmonitor | 21 observability | `repos/koala73_worldmonitor` | global state monitor | — | OSINT dashboard, not infra | SKIP (wrong domain) |
| amir20_dtop | 21 observability | `repos/amir20_dtop` | docker container TUI monitor | — | TUI, no programmable trace output | SKIP (human-facing tool, not a pipeline component) |
| aquasecurity_trivy | 21 observability | `repos/aquasecurity_trivy` | vulnerability scanner | — | security scanning, not flow observability | SKIP (wrong section — belongs to security) |

## Serialization candidates

| candidate | catalog category | verified repo path | technique | what we'd test | weight/deps + runs-on-box? | verdict |
|---|---|---|---|---|---|---|
| Aleph-Alpha_ts-rs | 23 serialization | `repos/Aleph-Alpha_ts-rs` | Rust struct → TypeScript type compiler | generate the witt-brain (Rust) event types consumed by witt-brain-desktop (TS) — kills schema drift at seam 6/7 | 1.3M repo; Rust proc-macro, cargo build; runs on box | LATER (high value, but needs a Rust+TS fixture harness; queue after event-schema race) |
| apache_fory | 23 serialization | `repos/apache_fory` | ultra-fast cross-language binary serialization | binary frame encoding vs JSON lines for high-rate event streams | 47M repo; multi-lang, bazel build (minutes) | LATER (only if JSONL encode/decode ever shows up in a profile) |
| apache_thrift | 23 serialization | `repos/apache_thrift` | IDL + cross-language RPC/serialization | typed IDL for the witt.sock JSON-RPC interface (seam 7) | compiler + runtimes, moderate build | LATER |
| transmute-app_transmute | 23 serialization | `repos/transmute-app_transmute` | data format transmuter / schema converter | fixture conversion between event schemas | small | LATER |
| toml-rs_toml | 23 serialization | `repos/toml-rs_toml` | serde TOML parser | — | config parsing only; `witt-link-server/config.toml` already parses fine | SKIP (no defect to race; config format, not event encoding) |
| apache_incubator-seata | 23 serialization | `repos/apache_incubator-seata` | distributed transaction protocol | — | Java, distributed TX coordinator | SKIP (no distributed transactions in the system) |
| cool-japan_oxiarc | 23 serialization | `repos/cool-japan_oxiarc` | archive/decompression formats | — | compression, not serialization | SKIP (wrong problem) |
| LukasKalbertodt_litrs | 23 serialization | `repos/LukasKalbertodt_litrs` | literal parsing micro-lib | — | tiny utility | SKIP (no pipeline relevance) |
| wooorm_mdxjs-rs / web-infra-dev_mdx-rs | 23 serialization | `repos/wooorm_mdxjs-rs`, `repos/web-infra-dev_mdx-rs` | MDX serialization | — | docs/markup format | SKIP (wrong domain) |

## Routing / orchestration candidates

| candidate | catalog category | verified repo path | technique | what we'd test | weight/deps + runs-on-box? | verdict |
|---|---|---|---|---|---|---|
| nginx_nginx | 30 networking | `repos/nginx_nginx/code` | reverse proxy with path-prefix routing | single front door resolving the 8787 + 8080 collisions: added latency per hop, path-based dispatch to correct backend | system nginx via apt, config-only; runs on box | RACE NOW |
| mitmproxy_mitmproxy | 30 networking | `repos/mitmproxy_mitmproxy` | programmable intercepting proxy | passive observation of every HTTP hop (fixture scrape → store) for trace stitching ground truth | Python, pip-install; runs on box | RACE NOW (as observability harness, not router) |
| floci-io_floci | 4 data, 31 containerization | `repos/floci-io_floci` | local AWS infra emulator (S3/SQS-shaped) | routing-correctness fixture: "right store" targets emulated locally | docker images, moderate | LATER (useful when routing tests need queue/blob targets) |
| apache_datafusion | 4 data | `repos/apache_datafusion` | in-memory OLAP SQL over JSON/CSV | ad-hoc SQL over `events.jsonl`/`audit.jsonl` for audit queries and test assertions | Rust, cargo build (minutes) | LATER (nice assertion engine for flow tests) |
| apache_camel-kamelets | 5 message/event | `repos/apache_camel-kamelets` | reusable source/sink connector catalog | connector definitions as routing-rule templates | YAML catalog; runtime is Camel (Java) | LATER (borrow the connector taxonomy, not the runtime) |
| cloudflare_pingora | 22 caching, 30 networking | `repos/cloudflare_pingora` | programmable Rust proxy framework | custom front door with per-hop trace-id injection | Rust framework, cargo build (minutes) | LATER (upgrade path if nginx race shows need for programmatic routing) |
| diegosouzapw_OmniRoute | 30 networking | `repos/diegosouzapw_OmniRoute` | dynamic multipath packet router | — | packet-level, not HTTP-level | LATER (wrong layer for app hops; keep for network races) |
| ogulcancelik_herdr | 30 networking | `repos/ogulcancelik_herdr` | cluster discovery daemon | sidecar discovery vs hardcoded `witt-link-server/config.toml` | small | LATER |
| apache_seatunnel | 4 data | `repos/apache_seatunnel` | distributed data integration | — | JVM, cluster-oriented | SKIP (heavy ETL for a localhost pipeline) |
| istio_istio / cilium_cilium / apache_shenyu | 30 networking | `repos/istio_istio`, `repos/cilium_cilium`, `repos/apache_shenyu` | service mesh / API gateway | — | require k8s or JVM | SKIP (no k8s; box is bare processes + docker lanes) |
| apache_druid / apache_superset / polynote_polynote / spotify_chartify | 4 data | `repos/apache_druid`, `repos/apache_superset`, `repos/polynote_polynote`, `repos/spotify_chartify` | OLAP / viz platforms | — | heavy platforms, viz not routing | SKIP (belong to analytics/UI sections) |
| lance-format_lance / apache_iceberg / apache_paimon | 4 data | `repos/lance-format_lance`, `repos/apache_iceberg`, `repos/apache_paimon` | lake table formats | — | storage formats | SKIP (storage-engine section's territory) |
| GyulyVGC_sniffnet | 30 networking | `repos/GyulyVGC_sniffnet` | GUI traffic monitor | — | desktop GUI, no programmatic output | SKIP (human-facing) |
| 5c0_metropolis | 30 networking | `repos/5c0_metropolis` | p2p mesh protocol | — | experimental p2p | SKIP (no p2p seam) |
| apache_spark / apache_flink / twitter_scalding / spotify_scio / microsoft_SynapseML / twitter_algebird / apache_datasketches(-rust) / apache_sedona-db / google-research_tabfm / cicirello_Chips-n-Salsa / adilkhash_Data-Engineering-HowTo | 4 data | all under `repos/` | batch/stream compute engines, sketch algs, reference docs | — | JVM clusters or reference docs | SKIP (compute engines, not the routing/observability seams this seat owns) |
| simplex-chat_simplex-chat / juanfont_headscale / clash-verge-rev_clash-verge-rev / quantumsheep_sshs / lwthiker_curl-impersonate / aksheyd_WhatsUp / iptv-org_iptv / relumetech_Domain-Connect-Templates / octelium_octelium / spotify_mobius / spotify_SPTDataLoader | 30 networking | all under `repos/` | messaging/VPN/proxy/misc networking | — | unrelated protocols | SKIP (no matching seam) |
| cat-31 containerization set (google_gvisor, coollabsio_coolify, 1Panel-dev_1Panel, IceWhaleTech_CasaOS, stagex_stagex, NVIDIA_infra-controller, netbox-community_netbox-operator, NVIDIA_nvidia-container-toolkit, budtmo/HQarroum_docker-android, alexei-led_pi-fusion, vyuh-labs_create-devstack, vyuh-labs_dxkit, ventoy_Ventoy) | 31 containerization | all under `repos/` | runtimes/panels/images | — | platform tooling | SKIP (docker lanes already exist; infra-setup concern, not a pipeline race) |

## Verdict summary

- RACE NOW (6): pyeventsourcing_eventsourcing, mrasu_echoed, socketio_socket.io, cursor_agent-trace, HalFrgrd_flyline, nginx_nginx, mitmproxy_mitmproxy → 7 (mitmproxy as harness)
- LATER (14): spotify_docker-kafka, quinn-rs_quinn, netdata_netdata, comet-ml_opik, apache_hertzbeat, zeroclaw-labs_zeroclaw-metrics, Aleph-Alpha_ts-rs, apache_fory, apache_thrift, transmute-app_transmute, floci-io_floci, apache_datafusion, apache_camel-kamelets, cloudflare_pingora, diegosouzapw_OmniRoute, ogulcancelik_herdr → 16
- SKIP: remainder (see reasons inline).
