# ip-eval — HANDOFF (2026-07-28, tranche 3)

## Cleanup status (read first)
- **Nothing of this suite is running.** No containers, no vite/playwright
  leftovers (frontend race teardown verified: port 3000 free, no processes).
- The evo dashboard IS running on request of the user:
  `http://127.0.0.1:8097` (log `/tmp/evo-dashboard.log`; `pkill -f evo.dashboard`).
- Candidate venvs present on disk: only `fastapi` (15MB) + `pouchdb-node`
  (23MB) from the api/persistence races. `python3 -m ip_eval.cli deps-prune`
  removes them; races re-provision on demand.
- NOT ours, do not delete: `~/.cache/ms-playwright` (1.3GB, predates this
  suite — other tooling).

## Tranche 3 changes (P10/A10/S10/F11)
New stages, all discriminating, all with real findings:
- **persistence**: store probes (write p50, concurrent lost-updates, torn-read
  atomicity, corrupt-file recovery). New driver `drivers/ip_store_driver.mjs`.
  Candidates: ip-incumbent (0.85), sqlite-store (0.85), pouchdb-store (0.775 —
  opens corrupt DB but loses data), naive-json (FAIL, 208 torn / 19 lost).
  IP finding: corrupt workspace.json throws; no recovery path.
- **api**: live HTTP probes (404, malformed JSON, wrong types, 60MB oversize,
  CORS, error leakage, deep link). ip 0.625 vs fastapi-naive FAIL (malformed
  JSON → 500 by framework default). IP findings: unknown API route returns
  the SPA (no 404), wrong-typed body → 500, 60MB body not rejected.
- **security**: path-traversal confinement on safeUploadName, planted prompt
  injection, npm audit. IP gate PASS. Advisories: injection line promoted to
  a concept; 1 high npm vuln.
- **frontend**: playwright/chromium probes (routes, console, keyboard,
  responsive overflow, deep-link refresh) — IP 5/5, no defects.
  Browser installed hermetically in the venv (PLAYWRIGHT_BROWSERS_PATH=0),
  venv purged after the race.

## Tranches 1-2 (kept)
7 stage races (extract/split/concepts/retrieval/graph/drafting/dedup/export x2)
+ E2E pipeline on self-authored fixtures v2. See `../results/ip-suite.md`.
Known incumbent bugs on record: dedup 2-char-token false-merge;
graph similarity-edge false positives; no DOCX reader; retrieval coverage
gate misses acronym/paraphrase queries; setext/numbered headings missed.

## Commands
```bash
cd ~/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval
python3 -m ip_eval.cli selftest
python3 -m ip_eval.cli race <stage>  # extract|split|concepts|retrieval|graph|
                                     # drafting|dedup|export_docx|export_bibtex|
                                     # persistence|api|security|frontend
python3 -m ip_eval.cli race-all && python3 -m ip_eval.cli pipeline
python3 -m ip_eval.cli deps-prune
```

## Known limits / next frontier
- OCR lane needs image fixtures; MinerU needs model weights; server retrieval
  (qdrant/ES) needs the docker lane.
- R10 (SLO/fault injection), backup/restore, schema migration races unwired —
  the persistence/api probe pattern is the template.
- `provision_venv` reuses venvs without re-installing changed package lists —
  delete the venv first when changing a candidate's deps.
- `provision-report.json` overwritten per race — cosmetic.


