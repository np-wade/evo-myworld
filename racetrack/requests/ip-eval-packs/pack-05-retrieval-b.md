# Pack 05 — retrieval_b.py (seat: feather)

## Objective

Create exactly ONE new file: `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval/ip_eval/candidates_extra/retrieval_b.py` registering five new candidates for the `retrieval` stage: `annoy`, `aann`, `leann`, `ruvector`, and `pixelrag`. Each implements `retrieve(query: str, corpus: list[str]) -> list[str]` — rank the corpus sentences best-first. Deliver per-candidate items: each class is self-contained and independently correct. Follow the venv + JSON-over-stdio pattern of `ip_eval/candidates_extra/retrieval.py` (`_VenvCandidate`, `_venv_call`). The hashing-embedding trick is allowed (see `FaissHashDense` in retrieval.py) so NO model downloads are needed: embed query and sentences with the stdlib blake2b signed-hashing embedding (512-dim), then let each library's ANN index do the ranking.

## Parent node

racetrack/ip-eval candidate-expansion tranche; suite root `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval`

## Boundaries and anti-patterns

Non-negotiable rules (verbatim, apply to every line you write):

- Boundaries: write ONLY the one new file `racetrack/ip-eval/ip_eval/candidates_extra/retrieval_b.py`. Never edit `race.py`, `oracle.py`, `fixtures.py`, `candidates.py`, other packs, or results files. Never commit.
- Honesty: NEVER fabricate scores or outputs. If a dependency can't provision on this box (no java, no cargo, no model weights, needs a server), `available()` returns `(False, "<truthful reason>")` after purging any partial venv. An unavailable candidate with a true reason is a SUCCESS; a fake score is a failure.
- `available()` must never raise — wrap provisioning in try/except and downgrade to unavailable (see how candidates_for at candidates.py:779-785 treats exceptions).
- provision_venv reuses existing venvs WITHOUT reinstalling changed package lists — purge-on-failure, and keep package lists minimal (disk is tight).
- Import shim header: follow the standalone-safe style used in `ip_eval/candidates_extra/tabilify.py` (sys.path.insert + `from ip_eval.candidates import Candidate, provision_venv`).
- End the file with `CANDIDATES = [YourClass, ...]`.
- Server-class repos (elasticsearch, meilisearch, qdrant, couchdb, airflow, PaddleOCR server mode) are NOT in these packs except where listed; where a pack includes a repo that needs a server, gate it: `available()` returns False with reason "needs docker lane" unless env `RACETRACK_DOCKER=1`.

Pack-specific notes:

- `annoy` (corpus `spotify_annoy/src/annoylib.h`, `annoymodule.cc`): provision venv `annoy` with pip package `annoy`. Build an `AnnoyIndex(512, "angular")` per call over hash embeddings, query for all N, map indices back to corpus strings, stable tie-break (score desc, corpus index asc — see `TantivyPy` SCRIPT, retrieval.py:88-95).
- `aann` (corpus `schlegelp_aann/code/aann/core.py`, rust `src/lib.rs`): pip package `aann` if it installs on py3.12 with wheels; if the rust-backed wheel fails to build/install, purge and report unavailable with the tail of the log.
- `leann` (corpus `StarTrail-org_LEANN/code/packages/leann-core/src/leann/interface.py`): LEANN pulls heavy deps (faiss, embeddings); keep the venv minimal (e.g. `leann-core` only if it exists on PyPI) and gate: if the install or its embedding-backend requirement can't be satisfied without model downloads, honest unavailable with the true reason. Do NOT download model weights.
- `ruvector` (corpus `ruvnet_ruvector/code/crates/ruvector-acorn/...`, Rust): check for a Python wheel (`ruvector` on PyPI); if none / build requires cargo toolchain work beyond a plain pip install, honest unavailable with the true reason.
- `pixelrag` (corpus `StarTrail-org_PixelRAG/code/eval/lib/retrievers.py`, `index/src/pixelrag_index/`): pixel-level multimodal retrieval requiring a vision model — expected honest-unavailable unless a deterministic text path genuinely exists in the source; verify by reading the files first.
- All embeddings must be deterministic (fixed dim, stdlib hashing, no RNG seed variance). Empty corpus → `[]`. Output is corpus strings, best first, stable across REPS.

## Pointer traces

- Mapping rows (corpus base `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/`):
  - `| **ANNOY** | `spotify_annoy` | `src/annoylib.h`, `src/annoymodule.cc` |`
  - `| **AANN** | `schlegelp_aann` | `code/src/lib.rs`, `code/aann/core.py` |`
  - `| **LEANN** | `StarTrail-org_LEANN` | `code/packages/leann-core/src/leann/interface.py` |`
  - `| **RUV** | `ruvnet_ruvector` | `code/crates/ruvector-acorn/src/search.rs`, `ruvector-matryoshka/` |`
  - `| **PIXEL** | `StarTrail-org_PixelRAG` | `code/eval/lib/retrievers.py`, `code/index/src/pixelrag_index/` |`
  - D-row: `| **S4.04** | Dense semantic retrieval on paraphrase, acronym, nested concept, distractor | `facebookresearch_faiss` (FAISS), `qdrant_qdrant` (QDR), `StarTrail-org_LEANN` (LEANN), `ruvnet_ruvector` (RUV), `spotify_annoy` (ANNOY), `schlegelp_aann` (AANN), `deepset-ai_haystack` (HAY), `deepsense-ai_ragbits` (RAG), `StarTrail-org_PixelRAG` (PIXEL), `EverMind-AI_HyperMem` (HMEM) | ... |`.
- Exemplar to follow: `ip_eval/candidates_extra/retrieval.py` — `FaissHashDense` (`:148-186`) is the direct template: copy its `embed()` (blake2b → (index, sign), 512-dim, L2-normalized) into your per-candidate SCRIPT strings and swap faiss for each ANN library; `_VenvCandidate` (`:24-35`), `_venv_call` (`:16-21`), stable-order idiom in `TantivyPy` (`:88-95`).
- Honest-unavailable idiom: `ip_eval/candidates_extra/concepts.py:152-171` (`FastTextConcepts`).
- Interface signature: `ip_eval/candidates.py:108-110` (`retrieve(query, corpus) -> list[str]`), `candidates.py:51-77` (`provision_venv`).
- Stage name: `retrieval`; score `recall_at_5`, gate `recall_at_5 > 0.0` (`ip_eval/race.py:803-807`).
- discovery/skip semantics: `ip_eval/candidates.py:744-771` (`all_candidates`), `candidates.py:774-795` (`candidates_for`).

## Acceptance

The line boss runs these; self-check what you can:

- `cd racetrack/ip-eval && python3 -m ip_eval.cli selftest` stays green
- `python3 -m ip_eval.cli list` shows the new candidates under the `retrieval` stage
- `python3 -m ip_eval.cli race retrieval` completes with each new candidate either scored (det check intact) or listed under candidates_unavailable with a truthful reason
- zero leaderboard rows with fails>0 caused by adapter bugs
