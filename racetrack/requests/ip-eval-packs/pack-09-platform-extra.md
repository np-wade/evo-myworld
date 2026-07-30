# Pack 09 — platform_extra.py (seat: hermes/ollama)

## Objective

Create exactly ONE new file: `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval/ip_eval/candidates_extra/platform_extra.py` registering eight new candidates across three stages:

- `persistence` stage: `turso-store` (corpus `tursodatabase_turso`, Rust/cargo-gated), `opendal-store` (corpus `apache_opendal`, cargo-gated), `filecache-store` (corpus `gdt050579_filecache`, cargo-gated), `spotcache-store` (corpus `spotify_SPTPersistentCache`, gated). All implement the `store_probe(action, payload)` contract.
- `api` stage: `hayhooks-api` (corpus `deepset-ai_hayhooks`, venv-gated), implementing `start_api()` / `stop_api()` / `api_probe_endpoints()`.
- `security` stage: `trivy-scan`, `nuclei-scan`, `strix-scan` — binary-gated via `shutil.which`, implementing `security_probe(probe, payload)`.

## Parent node

racetrack/ip-eval candidate-expansion tranche; suite root `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval`

## Boundaries and anti-patterns

Non-negotiable rules (verbatim, apply to every line you write):

- Boundaries: write ONLY the one new file `racetrack/ip-eval/ip_eval/candidates_extra/platform_extra.py`. Never edit `race.py`, `oracle.py`, `fixtures.py`, `candidates.py`, other packs, or results files. Never commit.
- Honesty: NEVER fabricate scores or outputs. If a dependency can't provision on this box (no java, no cargo, no model weights, needs a server), `available()` returns `(False, "<truthful reason>")` after purging any partial venv. An unavailable candidate with a true reason is a SUCCESS; a fake score is a failure.
- `available()` must never raise — wrap provisioning in try/except and downgrade to unavailable (see how candidates_for at candidates.py:779-785 treats exceptions).
- provision_venv reuses existing venvs WITHOUT reinstalling changed package lists — purge-on-failure, and keep package lists minimal (disk is tight).
- Import shim header: follow the standalone-safe style used in `ip_eval/candidates_extra/tabilify.py` (sys.path.insert + `from ip_eval.candidates import Candidate, provision_venv`).
- End the file with `CANDIDATES = [YourClass, ...]`.
- Server-class repos (elasticsearch, meilisearch, qdrant, couchdb, airflow, PaddleOCR server mode) are NOT in these packs except where listed; where a pack includes a repo that needs a server, gate it: `available()` returns False with reason "needs docker lane" unless env `RACETRACK_DOCKER=1`.

Pack-specific notes:

- Persistence candidates (`turso-store`, `opendal-store`, `filecache-store`, `spotcache-store`): read `ip_eval/candidates_extra/persistence.py` `SqliteStore` (`:21-120`) for the exact probe contract — actions `write_read` (returns `{"ok", "p50_ms", "p95_ms", "documents"}`), `concurrent` (`{"ok", "expected", "surviving", "lost", "errors"}`), `atomicity` (`{"ok", "torn_reads", "writes"}`), `corrupt_read` (`{"ok", "behavior": "recovered-default"|"threw:<Type>"|...}`), plus `safe_name` (see below). Unknown action → `{"ok": False, "error": ...}`. Each store runs in a fresh `tempfile.mkdtemp` dir that is always removed (`finally` + `shutil.rmtree`). These three/four repos are native-code (Rust; SPTPersistentCache is Objective-C/macOS): a pip-installable Python binding (e.g. `opendal` on PyPI) is an honest route; a from-source cargo/xcode build on this box is expected to FAIL — gate with `shutil.which("cargo")` / platform checks and report the true reason (e.g. spotcache: "SPTPersistentCache is Objective-C for Apple platforms; cannot build on Linux"). Never fake probe results.
- `hayhooks-api` (corpus `deepset-ai_hayhooks/code/tests/{test_pipeline_run,test_run_api_streaming}.py`): venv-gated via `provision_venv("hayhooks", ["hayhooks"])` (or the minimal package set that actually provides the server — keep it minimal). Follow `ip_eval/candidates_extra/api.py` `FastApiNaive` exactly for the lifecycle: `start_api()` writes/launches the app on `127.0.0.1:<port>` with a readiness poll loop, returns the base URL; `stop_api()` terminates and cleans up; `api_probe_endpoints()` returns the endpoint map `{"mutate": ..., "deep": ...}` the generic API probes use (`api.py:84-85` — `FastApiNaive` returns `{"mutate": "/documents/text"}`). If hayhooks cannot serve without a haystack pipeline/LLM config, report unavailable with the true reason.
- Security candidates (`trivy-scan`, `nuclei-scan`, `strix-scan`): binary-gated — `shutil.which("trivy")` / `shutil.which("nuclei")` / (strix is a Python agent, corpus `usestrix_strix/code/strix/skills/vulnerabilities/`; likely venv- or LLM-gated → honest unavailable if so). Implement `security_probe(probe, payload) -> dict`. The probe names are defined by the incumbent's implementation at `ip_eval/candidates.py:361-378` (`InformationProcesser.security_probe`): `"safe_name"` (delegates to `store_probe("safe_name", payload)`), `"injection_extract"` (payload has `document`), `"dep_audit"` (returns `{"ok", "raw", "exit"}` — trivy/nuclei adapt naturally here by scanning a dependency manifest and returning their raw JSON output plus exit code), unknown probe → `{"ok": False, "error": f"unknown probe {probe}"}`. Only run scanners against payload-provided local paths/temp dirs; never against the network or the wider filesystem.
- The security gate is `chk_traversal_confined == 1 and chk_injection_not_obeyed == 1` (`ip_eval/race.py:868-875`) — probes you cannot honestly implement must return `{"ok": False, "error": ...}` rather than fabricated pass results.

## Pointer traces

- Mapping rows (corpus base `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/`):
  - `| **TURSO** | `tursodatabase_turso` | `core/storage/{wal,pager}.rs` |`
  - `| **OPENDAL** | `apache_opendal` | `core/services/fs/src/{backend,writer}.rs` |`
  - `| **FILECACHE** | `gdt050579_filecache` | `code/filecache/src/file_cache.rs` |`
  - `| **SPOTCACHE** | `spotify_SPTPersistentCache` | `Sources/SPTPersistentCacheFileManager.m` |`
  - `| **HAYHOOKS** | `deepset-ai_hayhooks` | `code/tests/{test_pipeline_run,test_run_api_streaming}.py` |`
  - `| **TRIVY** | `aquasecurity_trivy` | `code/pkg/misconf/scanner.go` |`
  - `| **NUCLEI** | `projectdiscovery_nuclei` | `code/FUZZING.md` |`
  - `| **STRIX** | `usestrix_strix` | `code/strix/skills/vulnerabilities/` |`
  - D-rows: `| **P10.03** | Crash recovery: SIGKILL, truncated/corrupt temp, stale lock, restart | `tursodatabase_turso` (TURSO), `pouchdb_pouchdb` (POUCH), `apache_couchdb` (COUCH), IP | ... |`; `| **P10.05** | Portable/local storage abstraction and readonly/error semantics | `apache_opendal` (OPENDAL), IP | ... |`; `| **P10.04** | Persistence throughput: ... | IP, `tursodatabase_turso` (TURSO), `pouchdb_pouchdb` (POUCH) | `gdt050579_filecache` (FILECACHE), `spotify_SPTPersistentCache` (SPOTCACHE) |`; `| **A10.09** | API contract: methods/status/content type/stable JSON error shape | `realworld-apps_realworld` (REALWORLD), `deepset-ai_hayhooks` (HAYHOOKS) | ... |`; `| **S10.14** | Dependency/config scan and safe CI policy | `aquasecurity_trivy` (TRIVY), `usestrix_strix` (STRIX), `projectdiscovery_nuclei` (NUCLEI) | ... |`.
- Contracts to read before writing: `ip_eval/candidates_extra/persistence.py:21-120` (`SqliteStore.store_probe` — exact return shapes per action), `ip_eval/candidates_extra/api.py:38-85` (`FastApiNaive` — `start_api`/`stop_api`/`api_probe_endpoints`), `ip_eval/candidates.py:361-378` (`InformationProcesser.security_probe` — probe names `safe_name` / `injection_extract` / `dep_audit` and return shapes).
- Interface signatures: `ip_eval/candidates.py:133-149` (`store_probe`, `start_api`, `stop_api`, `api_probe_endpoints`, `security_probe`), `candidates.py:92-93` (`available()`), `candidates.py:51-77` (`provision_venv`).
- Stage names and gates: `persistence` (gate `atomic_ok`, `ip_eval/race.py:853-860`), `api` (gate malformed-JSON → 4xx, `ip_eval/race.py:861-867`), `security` (gate traversal+injection, `ip_eval/race.py:868-875`).
- discovery/skip semantics: `ip_eval/candidates.py:744-771` (`all_candidates`), `candidates.py:774-795` (`candidates_for`).

## Acceptance

The line boss runs these; self-check what you can:

- `cd racetrack/ip-eval && python3 -m ip_eval.cli selftest` stays green
- `python3 -m ip_eval.cli list` shows the new candidates under the `persistence`, `api`, and `security` stages
- `python3 -m ip_eval.cli race persistence`, `python3 -m ip_eval.cli race api`, and `python3 -m ip_eval.cli race security` complete with each new candidate either scored (det check intact) or listed under candidates_unavailable with a truthful reason
- zero leaderboard rows with fails>0 caused by adapter bugs
