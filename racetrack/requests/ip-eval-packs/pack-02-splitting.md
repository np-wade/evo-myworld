# Pack 02 — splitting.py (seat: poe)

## Objective

Create exactly ONE new file: `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval/ip_eval/candidates_extra/splitting.py` registering four new candidates for the `split` stage: `ontocast-chunker`, `opennlp-split`, `paperspine-split`, and `undoc-headings`. Each implements `split(content: str) -> list[dict]` producing sections in the incumbent's shape (`[{"id", "order", "title", "content"}]` — match the shape produced by `NaiveBaseline.split` / `MdTableParser._sections_from`). `opennlp-split` is Java-gated honest refusal; `undoc-headings` reuses the built-undoc-binary approach from extraction.py if feasible, else reports honestly unavailable.

## Parent node

racetrack/ip-eval candidate-expansion tranche; suite root `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval`

## Boundaries and anti-patterns

Non-negotiable rules (verbatim, apply to every line you write):

- Boundaries: write ONLY the one new file `racetrack/ip-eval/ip_eval/candidates_extra/splitting.py`. Never edit `race.py`, `oracle.py`, `fixtures.py`, `candidates.py`, other packs, or results files. Never commit.
- Honesty: NEVER fabricate scores or outputs. If a dependency can't provision on this box (no java, no cargo, no model weights, needs a server), `available()` returns `(False, "<truthful reason>")` after purging any partial venv. An unavailable candidate with a true reason is a SUCCESS; a fake score is a failure.
- `available()` must never raise — wrap provisioning in try/except and downgrade to unavailable (see how candidates_for at candidates.py:779-785 treats exceptions).
- provision_venv reuses existing venvs WITHOUT reinstalling changed package lists — purge-on-failure, and keep package lists minimal (disk is tight).
- Import shim header: follow the standalone-safe style used in `ip_eval/candidates_extra/tabilify.py` (sys.path.insert + `from ip_eval.candidates import Candidate, provision_venv`).
- End the file with `CANDIDATES = [YourClass, ...]`.
- Server-class repos (elasticsearch, meilisearch, qdrant, couchdb, airflow, PaddleOCR server mode) are NOT in these packs except where listed; where a pack includes a repo that needs a server, gate it: `available()` returns False with reason "needs docker lane" unless env `RACETRACK_DOCKER=1`.

Pack-specific notes:

- `ontocast-chunker`: corpus `growgraph_ontocast/code/ontocast/tool/chunk/chunker.py`. Read that file first. If the chunker is usable as a pure-python module with small pip deps (semantic-text-splitter etc.), import it by file path or drive it in a venv subprocess (retrieval.py `_venv_call` pattern). If it requires an LLM/SPARQL endpoint to run, say so in `available()` and return False.
- `opennlp-split` (corpus `apache_opennlp`, Java/Maven): gate on `shutil.which("java")` and honest refusal — do NOT attempt a maven build on this box. Reason e.g. "opennlp is a Java/Maven project; no java on this box".
- `paperspine-split`: corpus `WUBING2023_PaperSpine/code/src/scripts/structured_review.py`. Read it; if its section-structuring logic is extractable as a deterministic function, adapt it; if it is LLM- or API-key-bound, honest unavailable.
- `undoc-headings`: the undoc shim build lives in `ip_eval/candidates_extra/extraction.py:144-259` (`_build_undoc`, `UNDOC_BIN`). REUSE the built binary at `.venv-candidates/undoc/bin/undoc-extract` if present (do NOT rebuild, do NOT copy the build code into your file — import or reference it read-only). Note the binary renders docx→markdown; as a splitter it only makes sense if the heading analyzer output is honestly derivable. If you cannot honestly turn it into a text splitter, report unavailable with the true reason — that is a success.
- Determinism: the split workload repeats calls (det check) — your `split` must be a pure function of `content`.

## Pointer traces

- Mapping rows (corpus base `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/`):
  - `| **ONTO** | `growgraph_ontocast` | `code/ontocast/tool/chunk/chunker.py`, `tool/agg/entity_aligner.py` |`
  - `| **OPEN** | `apache_opennlp` | `opennlp-runtime/src/main/java/opennlp/tools/{sentdetect,namefind}/` |`
  - `| **PSP** | `WUBING2023_PaperSpine` | `code/src/scripts/{structured_review,citation_quality_audit}.py` |`
  - `| **UND** | `iyulab_undoc` | `code/src/docx/parser.rs`, `render/heading_analyzer.rs` |`
  - D-rows: `| **S2.01** | Explicit headings: ATX/setext, numbered, DOCX style, TeX section, visually styled heading | `deepset-ai_haystack` (HAY), `growgraph_ontocast` (ONTO), `iyulab_undoc` (UND), `WUBING2023_PaperSpine` (PSP), `jgm_pandoc` (PAND) | ... |` and `| **S2.02** | Academic boundaries/labels: abstract through appendix; ... | `growgraph_ontocast` (ONTO), `WUBING2023_PaperSpine` (PSP), `deepset-ai_haystack` (HAY) | ... |`.
- Exemplar to follow: `ip_eval/candidates_extra/extraction.py:197-259` (`_build_undoc` cargo-shim approach and honest gating), plus `ip_eval/candidates_extra/retrieval.py:16-35` (`_venv_call`, `_VenvCandidate`) if a venv subprocess is needed.
- Section row shape: `ip_eval/candidates_extra/tabilify.py:114-138` (`MdTableParser._sections_from`: `[{"id": f"s{order}", "order": order, "title": ..., "content": ...}]`, 1-based). Also `ip_eval/candidates.py:397-401` (`NaiveBaseline.split`).
- Interface signature: `ip_eval/candidates.py:99-100` (`split(content: str) -> list[dict]`), `candidates.py:92-93` (`available()`).
- Stage name: `split`; gate `mean_f1 >= 0.3` vs gold headings (`ip_eval/race.py:791-795`).
- discovery/skip semantics: `ip_eval/candidates.py:744-771` (`all_candidates`), `candidates.py:774-795` (`candidates_for`).

## Acceptance

The line boss runs these; self-check what you can:

- `cd racetrack/ip-eval && python3 -m ip_eval.cli selftest` stays green
- `python3 -m ip_eval.cli list` shows the new candidates under the `split` stage
- `python3 -m ip_eval.cli race split` completes with each new candidate either scored (det check intact) or listed under candidates_unavailable with a truthful reason
- zero leaderboard rows with fails>0 caused by adapter bugs
