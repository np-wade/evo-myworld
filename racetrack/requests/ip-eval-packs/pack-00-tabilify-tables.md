# Pack 00 — tabilify_tables.py (seat: feather)

## Objective

Create exactly ONE new file: `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval/ip_eval/candidates_extra/tabilify_tables.py` registering four new candidates for the `tabilify` stage: `tabfm-encoder`, `genie-worksheets`, `openscience-eval`, and `sheetjs-xlsx`. Every candidate in this pack MUST implement BOTH `tabilify(content)` and `tabilify_table(kind, payload)` for all four kinds `documents` / `sections` / `concepts` / `research`. The tabilify workload calls both entry points — a candidate missing `tabilify_table` is a recorded crash, which fails acceptance. Deliver the pack as per-candidate items: each class is self-contained and independently correct.

## Parent node

racetrack/ip-eval candidate-expansion tranche; suite root `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval`

## Boundaries and anti-patterns

Non-negotiable rules (verbatim, apply to every line you write):

- Boundaries: write ONLY the one new file `racetrack/ip-eval/ip_eval/candidates_extra/tabilify_tables.py`. Never edit `race.py`, `oracle.py`, `fixtures.py`, `candidates.py`, other packs, or results files. Never commit.
- Honesty: NEVER fabricate scores or outputs. If a dependency can't provision on this box (no java, no cargo, no model weights, needs a server), `available()` returns `(False, "<truthful reason>")` after purging any partial venv. An unavailable candidate with a true reason is a SUCCESS; a fake score is a failure.
- `available()` must never raise — wrap provisioning in try/except and downgrade to unavailable (see how candidates_for at candidates.py:779-785 treats exceptions).
- provision_venv reuses existing venvs WITHOUT reinstalling changed package lists — purge-on-failure, and keep package lists minimal (disk is tight).
- Import shim header: follow the standalone-safe style used in `ip_eval/candidates_extra/tabilify.py` (sys.path.insert + `from ip_eval.candidates import Candidate, provision_venv`).
- End the file with `CANDIDATES = [YourClass, ...]`.
- Server-class repos (elasticsearch, meilisearch, qdrant, couchdb, airflow, PaddleOCR server mode) are NOT in these packs except where listed; where a pack includes a repo that needs a server, gate it: `available()` returns False with reason "needs docker lane" unless env `RACETRACK_DOCKER=1`.

Pack-specific notes:

- This stage is scored for exactness AND honesty: gate is `metrics_fabrications == 0 and link_integrity >= 0.5`. Do NOT emit metric records you cannot substantiate from the input text — a fabricated value is a gate failure, worse than an empty list.
- `tabfm-encoder`: KNOWN-CORPUS GAP. The corpus repo is `google-research_tabfm/code/` (a TabPFN-style JAX/TPU foundation model) and the referenced `table_encoder.py` with `encode_text_to_table()` does NOT exist at the stated path on this box. Inspect `google-research_tabfm/code/` once; if no honest text→table encoder exists, `available()` must return `(False, "corpus repo google-research_tabfm has no table_encoder.py / encode_text_to_table(); no honest adapter")` — that is the correct deliverable for this seat.
- `genie-worksheets`: the worksheets library is LLM-driven (structured dialogue over worksheets); an LLM-less deterministic adapter is acceptable ONLY if it honestly derives rows from the payload. If the library cannot run without an LLM key, report unavailable with that true reason.
- `sheetjs-xlsx`: follow the npm-provisioned pattern of `PouchDbStore` in `candidates_extra/persistence.py` (node_modules under `.venv-candidates/sheetjs-node`, marker-check reuse, purge on failure). The npm package is `xlsx`. Drive it with a node script over stdio like `PouchDbStore.store_probe` does. Check `shutil.which("node")` first.
- Row shapes are contractual (see Pointer traces). Match them exactly, including the missing-value rule (emit nothing for `—`/`-`/empty cells) and the transposed-orientation rule, or the oracle scores you as fabricated/wrong.

## Pointer traces

- Mapping rows (corpus base `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/`):
  - `| **SYN** | `synthetic-sciences_openscience` | `code/backend/cli/skills/ml-training/.../evaluation_manager.py` |` — on disk: `synthetic-sciences_openscience/code/backend/cli/skills/ml-training/hugging-face-evaluation/scripts/evaluation_manager.py` (exists, verified).
  - `| **S3.11** | Metric from tables: header association, orientation, %, missing value, multiple metrics | `synthetic-sciences_openscience` (SYN vs IP table baseline) | ... |` — the D-row for `openscience-eval`.
  - genie-worksheets appears in the mapping only as a supporting repo on `| **S6.07** | ... | `WUBING2023_PaperSpine` (PSP), `stanford-oval_storm` (STORM) | ..., `stanford-oval_genie-worksheets` |` — no legend row. On disk the requested file exists: `stanford-oval_genie-worksheets/code/src/worksheets/core/worksheet.py` (verified).
  - tabfm has NO row anywhere in the mapping (see pack-specific notes).
  - `sheetjs-xlsx` is an npm dependency, not a corpus repo — no mapping row expected.
- Exemplar to follow: `ip_eval/candidates_extra/tabilify.py` (`MdTableParser`) — read it in full. It implements BOTH `tabilify` and `tabilify_table`; copy its row shapes verbatim:
  - documents rows: `{"name", "extractionQuality", "pages", "engine", "chars"}`
  - sections rows: `{"id", "order", "title", "content"}` (1-based order, `s{order}` ids)
  - concepts rows: `{"name", "type", "sectionIds"}`
  - research rows: `{"concept", "status", "evidence": [{"excerpt": ...}], "sources"}` with status ∈ supported / limited-evidence / unverified
  - metric records from `tabilify(content)`: `{"subject", "metric", "value", "unit"}` (value as string, unit from `%|ms|s|GB|MB|F1|points`)
- Interface signatures: `ip_eval/candidates.py:116-118` (`tabilify`), `candidates.py:88-93` (Candidate base, `available()`), and `tabilify.py:140-182` for `tabilify_table` dispatch by kind.
- Workload contract: `ip_eval/race.py:657-719` (`_workload_tabilify`) — note the call order: `tabilify(content)` → `tabilify_table("documents", {"files": [{"path","name","mime"}]})` → `tabilify_table("sections", {"content": canonical})` → `tabilify_table("concepts", {"sections": sections})` → `tabilify_table("research", {"concepts": concepts, "documents": [...]})`. Your sections output feeds your concepts input; keep ids stable (link integrity is scored from that chain). REPS=2: both calls must be deterministic.
- npm pattern exemplar: `ip_eval/candidates_extra/persistence.py:123-149` (`PouchDbStore.available`) and `:151-231` (node-over-stdio probe driver).
- provisioning: `ip_eval/candidates.py:51-77` (`provision_venv` purge-on-failure), `candidates.py:774-795` (`candidates_for`), `candidates.py:744-771` (plugin auto-discovery of `CANDIDATES`).

## Acceptance

The line boss runs these; self-check what you can:

- `cd racetrack/ip-eval && python3 -m ip_eval.cli selftest` stays green
- `python3 -m ip_eval.cli list` shows the new candidates under the `tabilify` stage
- `python3 -m ip_eval.cli race tabilify` completes with each new candidate either scored (det check intact) or listed under candidates_unavailable with a truthful reason
- zero leaderboard rows with fails>0 caused by adapter bugs
