# Pack 08 — export_extra.py (seat: hermes/ollama)

## Objective

Create exactly ONE new file: `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval/ip_eval/candidates_extra/export_extra.py` registering four new candidates: `jabref-bibtex` (stage `export_bibtex`, Java-gated honest refusal), `doxx-export` (stage `export_docx`, corpus `bgreenwell_doxx`, cargo shim like `Undoc`), `mdxjs-rs` and `mdx-rs` (stage `export_docx`, cargo-gated; markdown-normalization route — if not honestly adaptable to the export_docx contract, report unavailable with the true reason). Contracts: `export_docx(markdown: str, citations: list[dict]) -> bytes` (valid DOCX zip bytes) and `export_bibtex(citations: list[dict]) -> str`.

## Parent node

racetrack/ip-eval candidate-expansion tranche; suite root `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval`

## Boundaries and anti-patterns

Non-negotiable rules (verbatim, apply to every line you write):

- Boundaries: write ONLY the one new file `racetrack/ip-eval/ip_eval/candidates_extra/export_extra.py`. Never edit `race.py`, `oracle.py`, `fixtures.py`, `candidates.py`, other packs, or results files. Never commit.
- Honesty: NEVER fabricate scores or outputs. If a dependency can't provision on this box (no java, no cargo, no model weights, needs a server), `available()` returns `(False, "<truthful reason>")` after purging any partial venv. An unavailable candidate with a true reason is a SUCCESS; a fake score is a failure.
- `available()` must never raise — wrap provisioning in try/except and downgrade to unavailable (see how candidates_for at candidates.py:779-785 treats exceptions).
- provision_venv reuses existing venvs WITHOUT reinstalling changed package lists — purge-on-failure, and keep package lists minimal (disk is tight).
- Import shim header: follow the standalone-safe style used in `ip_eval/candidates_extra/tabilify.py` (sys.path.insert + `from ip_eval.candidates import Candidate, provision_venv`).
- End the file with `CANDIDATES = [YourClass, ...]`.
- Server-class repos (elasticsearch, meilisearch, qdrant, couchdb, airflow, PaddleOCR server mode) are NOT in these packs except where listed; where a pack includes a repo that needs a server, gate it: `available()` returns False with reason "needs docker lane" unless env `RACETRACK_DOCKER=1`.

Pack-specific notes:

- `jabref-bibtex` (corpus `JabRef_jabref`, Java/Gradle): Java-gated honest refusal — check `shutil.which("java")`, return `(False, "jabref is a Java/Gradle project; no java on this box")` style. Do NOT attempt a gradle build.
- `doxx-export` (corpus `bgreenwell_doxx/code/src/document/parsing/{heading,numbering,table}.rs`): follow the `_build_undoc` cargo-shim pattern exactly (`ip_eval/candidates_extra/extraction.py:144-259`): copy corpus `code/` to /tmp (ignore `target`), thin shim crate with path dependency, `cargo build --release` with `CARGO_TARGET_DIR` in the tmp dir, copy the binary to `.venv-candidates/doxx/bin/`, always delete /tmp. IMPORTANT direction check: doxx is primarily a DOCX *reader/renderer*. A markdown→DOCX exporter is honest ONLY if the library actually offers docx writing; read the source first. If it only reads/renders, report unavailable with that true reason instead of shipping a fake writer.
- `mdxjs-rs` (corpus `wooorm_mdxjs-rs/code/src/lib.rs`) and `mdx-rs` (corpus `web-infra-dev_mdx-rs/code/crates/mdx_rs/src/lib.rs`): MDX compilers (markdown→JSX/HTML), not DOCX writers. Gate on cargo like above; the honest adaptation, if any, is markdown normalization — if producing valid DOCX bytes from them is not honest (it likely is not), `available()` returns False with the true reason ("mdxjs-rs compiles MDX to JSX, cannot emit DOCX"). Do not emit DOCX bytes that aren't a real DOCX zip — the export_docx gate checks validity.
- If no cargo on this box, every cargo-gated candidate reports unavailable with reason "cargo not on PATH" — that is the expected outcome; verify with `shutil.which("cargo")` before any build attempt.
- `export_docx` return: raw bytes of a valid zip (starts `PK`). `export_bibtex`: a string. Never raise from these on bad input — wrap and, where the contract allows, degrade gracefully.

## Pointer traces

- Mapping rows (corpus base `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/`):
  - `| **JAB** | `JabRef_jabref` | `code/jablib/src/.../CitationKeyGenerator.java` |`
  - `| **DOXX** | `bgreenwell_doxx` | `code/src/document/parsing/{heading,numbering,table}.rs` |`
  - `| **MDXW** | `wooorm_mdxjs-rs` | `code/src/lib.rs` |`
  - `| **MDXR** | `web-infra-dev_mdx-rs` | `code/crates/mdx_rs/src/lib.rs` |`
  - D/S-rows: `| **S8.03** | BibTeX: required fields, braces/escaping, duplicate keys, DOI, Unicode names | `jgm_pandoc` (PAND), `JabRef_jabref` (JAB) | ... |`; `| **S8.01** | Markdown fidelity: ... | `jgm_pandoc` (PAND) | `bgreenwell_doxx` (DOXX), `wooorm_mdxjs-rs` (MDXW), `web-infra-dev_mdx-rs` (MDXR) |`; `| **S8.09** | DOCX styles/layout: ... | `jgm_pandoc` (PAND) | `bgreenwell_doxx` (DOXX), ... |` — note DOXX/MDXW/MDXR are SUPPORTING repos in the mapping, so honest-unavailable outcomes here are fully consistent with the mapping.
- Exemplar to follow: `ip_eval/candidates_extra/extraction.py:144-259` (`UNDOC_SRC`/`UNDOC_BIN` constants, `_SHIM_CARGO_TOML`, `_SHIM_MAIN_RS`, `_build_undoc`, `Undoc.available`). Also read the existing export family `ip_eval/candidates_extra/export.py` for the live contract shape of `export_docx`/`export_bibtex` in this suite.
- Interface signatures: `ip_eval/candidates.py:125-129` (`export_docx(markdown, citations) -> bytes`, `export_bibtex(citations) -> str`), `candidates.py:92-93` (`available()`), `candidates.py:37-44` (`_run`).
- Stage names: `export_docx` (gate `docx_score >= 0.35`, validity-weighted, `ip_eval/race.py:830-836`) and `export_bibtex` (gate `entry_count > 0`, `ip_eval/race.py:837-843`).
- discovery/skip semantics: `ip_eval/candidates.py:744-771` (`all_candidates`), `candidates.py:774-795` (`candidates_for`).

## Acceptance

The line boss runs these; self-check what you can:

- `cd racetrack/ip-eval && python3 -m ip_eval.cli selftest` stays green
- `python3 -m ip_eval.cli list` shows the new candidates under the `export_docx` and `export_bibtex` stages
- `python3 -m ip_eval.cli race export_docx` and `python3 -m ip_eval.cli race export_bibtex` complete with each new candidate either scored (det check intact) or listed under candidates_unavailable with a truthful reason
- zero leaderboard rows with fails>0 caused by adapter bugs
