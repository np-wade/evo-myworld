# Pack 04 — retrieval_a.py (seat: poe)

## Objective

Create exactly ONE new file: `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval/ip_eval/candidates_extra/retrieval_a.py` registering six new candidates for the `retrieval` stage: `ragbits-rrf`, `hypermem`, `wikichat`, `suql`, `local-deep-researcher`, and `librer`. Each implements `retrieve(query: str, corpus: list[str]) -> list[str]` — rank the corpus sentences best-first. Follow the venv + JSON-over-stdio subprocess pattern of `ip_eval/candidates_extra/retrieval.py` (`_VenvCandidate`, `_venv_call`). Most of these repos are LLM-dependent and will honestly report unavailable — that is expected and correct.

## Parent node

racetrack/ip-eval candidate-expansion tranche; suite root `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval`

## Boundaries and anti-patterns

Non-negotiable rules (verbatim, apply to every line you write):

- Boundaries: write ONLY the one new file `racetrack/ip-eval/ip_eval/candidates_extra/retrieval_a.py`. Never edit `race.py`, `oracle.py`, `fixtures.py`, `candidates.py`, other packs, or results files. Never commit.
- Honesty: NEVER fabricate scores or outputs. If a dependency can't provision on this box (no java, no cargo, no model weights, needs a server), `available()` returns `(False, "<truthful reason>")` after purging any partial venv. An unavailable candidate with a true reason is a SUCCESS; a fake score is a failure.
- `available()` must never raise — wrap provisioning in try/except and downgrade to unavailable (see how candidates_for at candidates.py:779-785 treats exceptions).
- provision_venv reuses existing venvs WITHOUT reinstalling changed package lists — purge-on-failure, and keep package lists minimal (disk is tight).
- Import shim header: follow the standalone-safe style used in `ip_eval/candidates_extra/tabilify.py` (sys.path.insert + `from ip_eval.candidates import Candidate, provision_venv`).
- End the file with `CANDIDATES = [YourClass, ...]`.
- Server-class repos (elasticsearch, meilisearch, qdrant, couchdb, airflow, PaddleOCR server mode) are NOT in these packs except where listed; where a pack includes a repo that needs a server, gate it: `available()` returns False with reason "needs docker lane" unless env `RACETRACK_DOCKER=1`.

Pack-specific notes:

- `ragbits-rrf`: corpus `deepsense-ai_ragbits/code/packages/ragbits-document-search/.../rrf.py`. Reciprocal-rank fusion is a pure ranking combinator — if the RRF implementation is extractable as a small deterministic function (or the `ragbits-document-search` package installs minimally), implement it honestly (fuse two deterministic rankings, e.g. BM25-style + positional). If the package drags in LLM client deps, keep the venv package list minimal or fall back to importing the single RRF function by file path. Do NOT import an LLM pipeline.
- `hypermem` (corpus `EverMind-AI_HyperMem/code/hypermem/main/stage{2,4}_hypergraph_*.py`): hypergraph retrieval with LLM stages — almost certainly honest-unavailable; verify by reading the files, then report the true reason.
- `wikichat` (corpus `stanford-oval_WikiChat/code/retrieval/llm_reranker.py`, `pipelines/chatbot.py`): LLM reranker — honest unavailable unless a deterministic sub-component genuinely stands alone.
- `suql` (corpus `stanford-oval_suql/code/src/suql/sql_free_text_support/execute_free_text_sql.py`): free-text SQL needs an LLM + database — honest unavailable with true reason.
- `local-deep-researcher` (corpus `langchain-ai_local-deep-researcher/code/src/ollama_deep_researcher/graph.py`): ollama/LLM graph — honest unavailable with true reason.
- `librer` (corpus `PJDude_librer/code/src/librer.py`, `core.py`): local file-content searcher in Python — the most likely candidate in this pack to run for real. Read the source; if its grep-like deterministic search adapts honestly to sentence ranking, implement it (pure-stdlib in-process or minimal venv); else honest unavailable.
- Empty corpus → return `[]` (see `RankBM25.retrieve`, retrieval.py:55-59). Ranked output must contain corpus sentences (strings), best first, deterministic across repeats.

## Pointer traces

- Mapping rows (corpus base `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/`):
  - `| **RAG** | `deepsense-ai_ragbits` | `code/packages/ragbits-document-search/.../rrf.py` |`
  - `| **HMEM** | `EverMind-AI_HyperMem` | `code/hypermem/main/stage{2,4}_hypergraph_*.py` |`
  - `| **WIKI** | `stanford-oval_WikiChat` | `code/pipelines/chatbot.py`, `code/retrieval/llm_reranker.py` |`
  - `| **SUQL** | `stanford-oval_suql` | `code/src/suql/sql_free_text_support/execute_free_text_sql.py` |`
  - `| **LDR** | `langchain-ai_local-deep-researcher` | `code/src/ollama_deep_researcher/graph.py` |`
  - `| **PJD** | `PJDude_librer` | `code/src/librer.py`, `code/src/core.py` |`
  - D-rows: `| **S4.03** | Lexical passage ranking: Recall@1/5/10, MRR, nDCG, ... | `quickwit-oss_tantivy` (TANT), ..., `deepsense-ai_ragbits` (RAG), `EverMind-AI_HyperMem` (HMEM), ... | `PJDude_librer` (PJD), ... |`; `| **S4.06** | Rerank noisy top-50: ... | `deepsense-ai_ragbits` (RAG), `deepset-ai_haystack` (HAY), `stanford-oval_WikiChat` (WIKI), `EverMind-AI_HyperMem` (HMEM), ... |`; `| **S4.01** | Query variants preserve concept/alias/... | `stanford-oval_WikiChat` (WIKI), `deepsense-ai_ragbits` (RAG), ..., `langchain-ai_local-deep-researcher` (LDR), `stanford-oval_suql` (SUQL) | ... |`.
- Exemplar to follow: `ip_eval/candidates_extra/retrieval.py` — `_venv_call` (`:16-21`), `_VenvCandidate` (`:24-35`), `RankBM25` (`:38-59`), `FaissHashDense` (`:148-186`, hashing-embedding trick), `HaystackBM25.available` (`:130-138`, reusing a shared venv read-only).
- Honest-unavailable idiom: `ip_eval/candidates_extra/concepts.py:152-171` (`FastTextConcepts`).
- Interface signature: `ip_eval/candidates.py:108-110` (`retrieve(query, corpus) -> list[str]`, "Rank corpus sentences for the query, best first."), `candidates.py:51-77` (`provision_venv`), `candidates.py:37-44` (`_run`).
- Stage name: `retrieval`; score `recall_at_5`, gate `recall_at_5 > 0.0` (`ip_eval/race.py:803-807`).
- discovery/skip semantics: `ip_eval/candidates.py:744-771` (`all_candidates`), `candidates.py:774-795` (`candidates_for`).

## Acceptance

The line boss runs these; self-check what you can:

- `cd racetrack/ip-eval && python3 -m ip_eval.cli selftest` stays green
- `python3 -m ip_eval.cli list` shows the new candidates under the `retrieval` stage
- `python3 -m ip_eval.cli race retrieval` completes with each new candidate either scored (det check intact) or listed under candidates_unavailable with a truthful reason
- zero leaderboard rows with fails>0 caused by adapter bugs
