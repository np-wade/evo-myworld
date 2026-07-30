# TESTS — pipelines (data routing + observability)

Tests to build later. Group A are cheap contract tests — one per real seam plus the two known port collisions; each is a standalone script asserting one invariant in seconds. Group B are flow/race tests that wire multiple seams together; each carries metric/gate/fixture/budget for the racetrack.

All paths verified 2026-07-27. Project root below = `/home/npwad/coding/docker-envs/projects`, library root = `/home/npwad/coding/docker-envs/filing-cabinet/library-base`.

---

## A. CONTRACT TESTS (cheap, one per seam)

**A1. graphify index.db schema contract** (seam 1)
- Check: open `projects/graphify-app/data/index.db` read-only (`file:...?mode=ro`); assert tables `meta`, `repos`, `nodes`, `edges` and FTS5 virtual table `nodes_fts` exist; assert `nodes_fts` tokenizer is `unicode61` with tokenchars `+#`; assert unique index `nodes_repo_node(repo_id, node_id)` exists.
- Invariant source: writer schema `projects/graphify-app/src/search/db.js:18-52` (`SCHEMA` const); writer `projects/graphify-app/scripts/build-index.mjs`.
- Readers held to this contract: `projects/evo-myworld/world/backend/evo_graph.py` (env `GRAPHIFY_DATA`, default resolution at line 55), `projects/evo-myworld/plugins/evo/src/evo/graph/store.py` (line 74).
- Expected invariant: read-only open succeeds, WAL mode tolerated, zero write attempts; both Python readers resolve the same path given the same `GRAPHIFY_DATA`.

**A2. graphify → graphify-app bridge contract** (seam 2)
- Check: `projects/graphify-app/src/graphify-bridge.js:24` spawns `uv run --directory <GRAPHIFY_PROJECT> graphify ...`; assert GRAPHIFY_PROJECT resolves to an existing sibling `../graphify` checkout; assert a completed run lands output under `data/graphs/<repo-id>/graphify-out/`.
- Expected invariant: non-zero exit or 600s timeout (`timeoutMs = 600_000`) rejects the promise and writes no partial `graphify-out/` dir (or marks it failed); stderr is captured, not lost.

**A3. filing-cabinet corpus contract** (seam 3)
- Check: `filing-cabinet/library-base/CARDS-META.json` parses as JSON with top-level `{generated, repos, uncarded}`; every `repos` key has a corresponding directory `library-base/repos/<key>/`; generator is `library-base/tools/gen-cards-index.js`.
- Reader: `projects/assembly-office/server.js:345` (`readCardsMeta()`, mtime-cached).
- Expected invariant: regenerating the index twice with no repo changes yields byte-identical file (determinism); every listed repo dir contains a CARD.md or appears in `uncarded`.

**A4. assembly-office run-dir protocol** (seam 4)
- Check: for a fixture run dir `projects/assembly-runs/<run>/`: `events.jsonl` — every non-empty line parses as JSON with `ts` and `type` fields, append-only (no line ever shrinks/mutates between two reads); `approvals.json` — valid JSON, and no torn writes (file always parses, even mid-write, because writers use tmp+rename); `audit.jsonl` and `plan.json` parse.
- Reference: SSE tail at `projects/assembly-office/server.js:375` (`serveLive`), Last-Event-ID reconnect replay.
- Expected invariant: `events.jsonl` byte-prefix property — the file at time T2 is a byte-extension of the file at T1; `approvals.json` mtime changes are atomic (no reader ever sees a partial object) even with the two writers.

**A5. witt-link-server static topology** (seam 5)
- Check: parse `projects/witt-link-server/config.toml`; assert declared ports {8787 (self, line 6), 11434 (Ollama, line 29), 8788 (line 33), 8080 (line 50), 8793 (line 58)} plus the :8788–:8793 sidecar band form no duplicate bindings; assert every hardcoded sibling path in the file exists on disk.
- Expected invariant: every URL is `127.0.0.1`; every referenced sibling directory resolves; no port appears in two `[...]` sections with different purposes.

**A6. witt-brain-desktop ↔ witt-link-server event streams** (seam 6)
- Check: `projects/witt-brain-desktop/src/paths.js:10` resolves `WITT_LINK_SERVER_DIR` (default `/workspace/witt-link-server`); assert both sides' `events.jsonl` and `audit.jsonl` share the line schema (every line JSON with `ts`+`type`); assert the desktop's resolved dir matches where witt-link-server actually writes.
- Expected invariant: an event emitted by witt-link-server appears, by id, in the desktop's view within one poll/tail cycle; no schema field is produced by one side that the other requires but never receives.

**A7. Bertrand-Hussle ↔ witt-brain Unix socket** (seam 7)
- Check: socket path resolution matches `projects/witt-brain/src/interface/server.rs:22-25` — `~/.config/bertrand-hussle/witt.sock`, fallback `/tmp/bh-witt.sock`; framing per `projects/witt-brain/INTERFACE.md:18`.
- Expected invariant: JSON-RPC round-trip over the socket — send a `initialize`/ping-shaped request from a fixture client, get a well-formed JSON-RPC response with matching `id`; malformed frame produces an error response, not a hang.

**A8. evo-desktop → evo dashboard** (seam 8)
- Check: `projects/evo-desktop/launch-dashboard.sh:12` uses `EVO_DASHBOARD_PORT` default 8080 and `EVO_WORKSPACE`; assert the launched dashboard binds the requested port and serves HTTP 200 on `/` within N seconds.
- Expected invariant: if 8080 is occupied, launch fails loudly (non-zero exit or explicit error), never silently serves the wrong app.

**A9. graphify-app → pixel-search sidecar** (seam 9)
- Check: `projects/graphify-app/src/pixel-proxy.js:6` default `http://127.0.0.1:30001`; assert proxy returns a defined error (502/503) within the proxy timeout when the sidecar is down, and passes through status+body when up; FalkorDB expected at :16379.
- Expected invariant: no unbounded hang on sidecar absence; proxy never buffers unboundedly (backpressure or size cap).

**A10. Shared Ollama :11434** (seam 10)
- Check: all three consumers point at the same endpoint: `projects/witt/src/backends.rs:79` (default `http://127.0.0.1:11434`), `projects/witt-link-server/config.toml:29`, witt-brain config; assert model tags referenced by each consumer exist in `ollama list` (or its fixture equivalent).
- Expected invariant: one consumer's request cannot wedge the others — a slow/blocked generation from witt does not starve witt-link-server's calls beyond a defined timeout (consumers must set per-request timeouts).

**A11. Port collision: 8787**
- Check: `projects/witt-link-server/config.toml:6` binds 8787; `projects/information-processer/vite.config.js:10` proxies `/api` to `http://127.0.0.1:8787`.
- Expected invariant: a port-registry test asserts no two apps in the system claim the same default port for different services — 8787 must have exactly one owner, and information-processer's proxy target must match whoever actually owns it (currently ambiguous → this test is expected to FAIL today and documents the collision).

**A12. Port collision: 8080**
- Check: `projects/evo-desktop/launch-dashboard.sh:12` defaults 8080; `projects/witt-link-server/config.toml:50` also references `http://127.0.0.1:8080` (localai sidecar).
- Expected invariant: same registry rule as A11 — 8080 has exactly one default owner; evo dashboard must fail loudly or auto-pick a free port rather than collide with the localai sidecar (expected to FAIL today).

---

## B. FLOW / RACE TESTS (metric / gate / fixture / budget)

**B1. Event schema conformance across apps**
- What: define one canonical event envelope (`ts`, `type`, `source`, `id`, optional `trace_id`, `payload`); validate every line of `events.jsonl`/`audit.jsonl` from assembly-office run dirs, witt-brain-desktop, and witt-link-server against it (tolerating a declared per-app extension set).
- Metric: max — % of lines conforming without per-app special-casing.
- Gate: 100% of lines parse as JSON; ≥99% conform after the declared extension set; zero lines missing `ts` or `type`.
- Fixture: captured snippets (≤2MB total) of each app's real `events.jsonl`/`audit.jsonl`, copied into the race workspace.
- Budget: <10s per validation run.

**B2. Append-only integrity under concurrent writers**
- What: hammer `approvals.json` (two writers, tmp+rename) and `events.jsonl` (appender + SSE tailer) with concurrent fixture writers; assert the byte-prefix property for JSONL and parse-at-every-instant for the atomic file.
- Metric: min — worst-case p99 latency of a single append while 2 writers + 1 tailer are active.
- Gate: zero torn reads (every `approvals.json` read parses); zero interleaved/partial lines in `events.jsonl`; tailer sees every committed event exactly once.
- Fixture: synthetic event generator, 5k events, ≤1MB.
- Budget: <30s.

**B3. Cross-app trace stitching**
- What: run one synthetic operation spanning assembly-office → witt-link-server → a sidecar port; propagate a `trace_id` at each hop (via event field, HTTP header, or socket metadata); assert the per-hop events join into one ordered trace by id.
- Metric: max — % of hops joinable by id into the correct single trace (and min — wall-clock ms end-to-end, for the race table).
- Gate: a complete trace has exactly one event per expected hop, in causal order (ts monotonic within clock tolerance); no orphan hop events.
- Fixture: script driving the three apps with stub sidecar on a free port; ≤1MB logs.
- Budget: <60s including app startup.

**B4. Routing correctness — fixture scrape lands in the right store**
- What: feed a fixture scrape batch (tagged records: graph-node data vs card metadata vs telemetry) through the routing layer; assert graph data reaches the graphify index path (`data/graphs/<repo-id>/graphify-out/` → `index.db`), card metadata reaches `CARDS-META.json` shape, telemetry reaches `events.jsonl` — and nothing cross-lands.
- Metric: max — routing precision (records in correct store / total), then min — ms per record.
- Gate: precision = 1.0 on the fixture batch; each target store's own contract test (A1/A3/A4) still passes after the write.
- Fixture: 200-record synthetic scrape batch, ≤1MB, with known ground-truth routing labels.
- Budget: <30s.

**B5. Heartbeat freshness across the sidecar fleet**
- What: poll the witt-link-server sidecar band :8788–:8793, pixel :30001, Ollama :11434, evo dashboard :8080 (or its override); each must expose or imply a liveness signal; staleness = now − last-successful-probe.
- Metric: min — detection latency from sidecar kill to flagged-stale.
- Gate: every configured sidecar is either live or flagged within 2× poll interval; a killed fixture sidecar is flagged ≤5s at 2s polling; no false-stale on a live but busy sidecar.
- Fixture: two stub HTTP sidecars (one killed mid-run), ports from a free range.
- Budget: <20s.

**B6. Backpressure and replay on the event stream**
- What: with the SSE tail disconnected for a window, keep appending events; reconnect with `Last-Event-ID` (see `assembly-office/server.js:375` replay behavior); measure catch-up throughput and assert no loss/dup. Compare candidate replay engines (race `event-log-append-replay`).
- Metric: min — ms to replay a 1k-event gap to a reconnecting client.
- Gate: replayed sequence == committed sequence (same ids, same order, no gaps, no dups); steady-state append latency does not degrade >2× while a slow client is attached.
- Fixture: 5k-event JSONL log, ≤2MB.
- Budget: <30s.

**B7. Live-tail fanout latency** (race `live-tail-fanout`)
- What: compare incumbent SSE tail vs socket.io rooms vs a flyline-style normalized tailer on the same `events.jsonl` fixture being appended live.
- Metric: min — p95 append→client latency at 100 events/s with 3 concurrent clients.
- Gate: zero missed and zero duplicated events per client across one induced reconnect each.
- Fixture: append generator at controlled rate, 2k events.
- Budget: <60s.

**B8. Front-door routing / port-collision resolution** (race `front-door-port-routing`)
- What: put candidate routers (nginx path-prefix proxy vs hardcoded per-app ports vs programmable proxy) in front of stub backends for 8787 and 8080 claimants; measure added latency and misroute rate.
- Metric: min — added ms per hop (p95) at 200 req/s.
- Gate: every request for `/api/*` reaches the information-processer backend, every dashboard request reaches evo — 0 misroutes; each backend can still be reached directly for the contract tests.
- Fixture: two stub HTTP backends with distinguishing response tokens; wrk/curl loop.
- Budget: <30s.
