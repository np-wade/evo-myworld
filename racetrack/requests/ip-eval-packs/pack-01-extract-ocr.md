# Pack 01 — extract_ocr.py (seat: poe)

## Objective

Create exactly ONE new file: `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval/ip_eval/candidates_extra/extract_ocr.py` registering three new candidates for the `extract` stage: `olmocr`, `stirling-pdf`, and `tesseract-cli`. Follow the extraction-family pattern of `ip_eval/candidates_extra/extraction.py`. Candidates must honestly refuse formats they cannot handle by returning `{"ok": False, "error": ...}` from `extract(...)` rather than raising. `stirling-pdf` is Java/server-class and must honestly refuse via `available()`.

## Parent node

racetrack/ip-eval candidate-expansion tranche; suite root `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval`

## Boundaries and anti-patterns

Non-negotiable rules (verbatim, apply to every line you write):

- Boundaries: write ONLY the one new file `racetrack/ip-eval/ip_eval/candidates_extra/extract_ocr.py`. Never edit `race.py`, `oracle.py`, `fixtures.py`, `candidates.py`, other packs, or results files. Never commit.
- Honesty: NEVER fabricate scores or outputs. If a dependency can't provision on this box (no java, no cargo, no model weights, needs a server), `available()` returns `(False, "<truthful reason>")` after purging any partial venv. An unavailable candidate with a true reason is a SUCCESS; a fake score is a failure.
- `available()` must never raise — wrap provisioning in try/except and downgrade to unavailable (see how candidates_for at candidates.py:779-785 treats exceptions).
- provision_venv reuses existing venvs WITHOUT reinstalling changed package lists — purge-on-failure, and keep package lists minimal (disk is tight).
- Import shim header: follow the standalone-safe style used in `ip_eval/candidates_extra/tabilify.py` (sys.path.insert + `from ip_eval.candidates import Candidate, provision_venv`).
- End the file with `CANDIDATES = [YourClass, ...]`.
- Server-class repos (elasticsearch, meilisearch, qdrant, couchdb, airflow, PaddleOCR server mode) are NOT in these packs except where listed; where a pack includes a repo that needs a server, gate it: `available()` returns False with reason "needs docker lane" unless env `RACETRACK_DOCKER=1`.

Pack-specific notes:

- `olmocr` (corpus `allenai_olmocr`): provision venv `olmocr` via `provision_venv`. Gate `available()` on model weights: if weights cannot be downloaded/verified on this box (HF model weights are multi-GB; disk is tight), return `(False, "olmocr model weights not downloadable on this box (<short true detail>)")` after purging any partial venv. Do NOT fake OCR output.
- `stirling-pdf` (corpus `Stirling-Tools_Stirling-PDF`, Java Spring server): `available()` must check `shutil.which("java")`/server reachability and honestly refuse with a true reason (e.g. "java not on PATH" or "needs docker lane" per the server-class rule when `RACETRACK_DOCKER` is not `1`). Never attempt to provision Java.
- `tesseract-cli`: gate on `shutil.which("tesseract")` — if absent, unavailable with reason "tesseract binary not on PATH". If present, drive the binary via subprocess (`_run`), PDF/page-image inputs only as tesseract actually supports (tesseract does NOT read PDF directly — refuse `%PDF` inputs honestly unless you rasterize via an available tool; if no rasterizer exists, refuse with a true error). Use the `_sniff` header-check idiom from extraction.py.
- Extract contract: return `{"ok": True, "content": <text>, "extractionQuality": "ocr-layout" (or "native-text"), "engine": "<name>"}` on success; `{"ok": False, "error": <truthful>}` on refusal/failure. Empty file → `{"ok": False, "error": "empty file"}`.
- Use generous timeouts for OCR subprocesses and convert timeouts into `{"ok": False, ...}`, mirroring `MinerU.extract` in extraction.py.

## Pointer traces

- Mapping rows (corpus base `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/`):
  - `| **OLM** | `allenai_olmocr` | `code/olmocr/pipeline.py`, `prompts/anchor.py`, `repeatdetect.py` |`
  - `| **STIR** | `Stirling-Tools_Stirling-PDF` | `code/app/core/src/main/java/stirling/software/SPDF/controller/api/` |`
  - `| **TESS** | `tesseract-ocr_tesseract` | `code/src/api/baseapi.cpp`, `code/src/ccmain/pagesegmain.cpp` |`
  - D-rows: `| **S1.07** | OCR accuracy: CER/WER/reading-order error on blank, skewed, noisy, low-contrast, multilingual scans | `allenai_olmocr` (OLM), `PaddlePaddle_PaddleOCR` (PAD), `greatv_oar-ocr` (OAR), `tesseract-ocr_tesseract` (TESS), `zibo-chen_rust-paddle-ocr` (RPAD), `opendatalab_MinerU` (MNU), `Stirling-Tools_Stirling-PDF` (STIR) | ... |` and `| **S1.05** | Native PDF text: ... | `opendatalab_MinerU` (MNU), `Stirling-Tools_Stirling-PDF` (STIR), `allenai_olmocr` (OLM) | ... |`.
- Exemplar to follow: `ip_eval/candidates_extra/extraction.py` — the whole file: `PandocPypandoc` (venv + honest format refusal, `:40-82`), `MinerU` (heavy venv, timeout→error, `:89-137`), `Undoc`/`_build_undoc` (external binary from corpus, `:144-259`), `_sniff` (`:23-33`).
- Interface signatures: `ip_eval/candidates.py:96-97` (`extract(file: Path, name: str, mime: str) -> dict`), `candidates.py:92-93` (`available()`), `candidates.py:51-77` (`provision_venv`), `candidates.py:37-44` (`_run`).
- Stage name: `extract`; gate `mean_f1 >= 0.3 and adversarial_pass >= 2` (`ip_eval/race.py:785-789`). The adversarial pack includes corrupt/encrypted/unsupported files — honest `{"ok": False, "error": ...}` responses are how you pass adversarial checks; crashes are failures.
- discovery/skip semantics: `ip_eval/candidates.py:744-771` (`all_candidates` plugin loading), `candidates.py:774-795` (`candidates_for` — exceptions in `available()` are caught at `:784-785`, but you must still not raise).

## Acceptance

The line boss runs these; self-check what you can:

- `cd racetrack/ip-eval && python3 -m ip_eval.cli selftest` stays green
- `python3 -m ip_eval.cli list` shows the new candidates under the `extract` stage
- `python3 -m ip_eval.cli race extract` completes with each new candidate either scored (det check intact) or listed under candidates_unavailable with a truthful reason
- zero leaderboard rows with fails>0 caused by adapter bugs
