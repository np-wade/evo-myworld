# Pack 07 — drafting_extra.py (seat: poe)

## Objective

Create exactly ONE new file: `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval/ip_eval/candidates_extra/drafting_extra.py` registering three new candidates for the `drafting` stage: `storm-draft`, `paperspine-draft`, and `wikichat-draft`. Each implements `draft(sections: list[dict], concepts: list[dict], research: dict) -> list[str]` — ONE draft text per section, in section order. Drafts must be extractive/grounded ONLY: every sentence must come from (or be directly quoteable against) the given sections/evidence; NO invented content. The drafting gate requires `metric_fidelity >= 0.99` — a single fabricated number fails the gate. Omitting content you cannot ground is always correct.

## Parent node

racetrack/ip-eval candidate-expansion tranche; suite root `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval`

## Boundaries and anti-patterns

Non-negotiable rules (verbatim, apply to every line you write):

- Boundaries: write ONLY the one new file `racetrack/ip-eval/ip_eval/candidates_extra/drafting_extra.py`. Never edit `race.py`, `oracle.py`, `fixtures.py`, `candidates.py`, other packs, or results files. Never commit.
- Honesty: NEVER fabricate scores or outputs. If a dependency can't provision on this box (no java, no cargo, no model weights, needs a server), `available()` returns `(False, "<truthful reason>")` after purging any partial venv. An unavailable candidate with a true reason is a SUCCESS; a fake score is a failure.
- `available()` must never raise — wrap provisioning in try/except and downgrade to unavailable (see how candidates_for at candidates.py:779-785 treats exceptions).
- provision_venv reuses existing venvs WITHOUT reinstalling changed package lists — purge-on-failure, and keep package lists minimal (disk is tight).
- Import shim header: follow the standalone-safe style used in `ip_eval/candidates_extra/tabilify.py` (sys.path.insert + `from ip_eval.candidates import Candidate, provision_venv`).
- End the file with `CANDIDATES = [YourClass, ...]`.
- Server-class repos (elasticsearch, meilisearch, qdrant, couchdb, airflow, PaddleOCR server mode) are NOT in these packs except where listed; where a pack includes a repo that needs a server, gate it: `available()` returns False with reason "needs docker lane" unless env `RACETRACK_DOCKER=1`.

Pack-specific notes:

- All three source repos (storm, PaperSpine, WikiChat) are LLM pipelines. An honest adapter in this pack means one of two things: (a) extract a genuinely deterministic, LLM-free sub-component (e.g. PaperSpine's `structured_review.py` template/outline logic applied extractively over the provided sections/evidence), or (b) report unavailable with the true reason ("storm article generation requires an LLM backend; no honest extractive adapter"). Both are successes. Do NOT paste a sumy clone and rename it storm-draft — the adapter must reflect what the repo actually does, or refuse.
- `storm-draft`: corpus `stanford-oval_storm/code/knowledge_storm/storm_wiki/modules/{outline,article}_generation.py` — read before deciding (a) vs (b).
- `paperspine-draft`: corpus `WUBING2023_PaperSpine/code/src/scripts/structured_review.py` — the best candidate for (a); if its review-template logic runs deterministically over provided content, implement it extractively with citations bound to provided evidence only.
- `wikichat-draft`: corpus `stanford-oval_WikiChat/code/pipelines/chatbot.py` — LLM chat pipeline; almost certainly (b).
- Follow the existing drafting family `ip_eval/candidates_extra/drafting.py` (`_SumyDraft`): declared-composition docstring, JSON-over-stdio subprocess, and the citation post-processor idiom (bind `[n]` markers only to sentences containing actual research evidence excerpts, `:39-55`). Numbers/metrics in drafts must be copied verbatim from the input text — never rounded, never invented.
- Determinism: fixed input → byte-identical drafts across REPS.

## Pointer traces

- Mapping rows (corpus base `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/`):
  - `| **STORM** | `stanford-oval_storm` | `code/knowledge_storm/storm_wiki/modules/{outline,article}_generation.py` |`
  - `| **PSP** | `WUBING2023_PaperSpine` | `code/src/scripts/{structured_review,citation_quality_audit}.py` |`
  - `| **WIKI** | `stanford-oval_WikiChat` | `code/pipelines/chatbot.py`, `code/retrieval/llm_reranker.py` |`
  - D-rows: `| **S6.01** | Map concepts/evidence to correct section; ... | `stanford-oval_storm` (STORM), `WUBING2023_PaperSpine` (PSP), `stanford-oval_WikiChat` (WIKI) | ... |`; `| **S6.05** | Missing evidence produces omission or visible warning, never invention | `stanford-oval_WikiChat` (WIKI), `WUBING2023_PaperSpine` (PSP), ... |`; `| **S6.12** | Numeric/unit/quote fidelity including ranges, signs, uncertainty, significant digits | `stanford-oval_WikiChat` (WIKI), `stanford-oval_storm` (STORM), `WUBING2023_PaperSpine` (PSP) | ... |`.
- Exemplar to follow: `ip_eval/candidates_extra/drafting.py` — whole file: `_SCRIPT` (`:18-59`), `_SumyDraft.available` with data-file download check (`:69-81`), `draft()` subprocess (`:83-90`).
- Honest-unavailable idiom: `ip_eval/candidates_extra/concepts.py:152-171` (`FastTextConcepts`).
- Interface signature: `ip_eval/candidates.py:120-123` (`draft(sections, concepts, research) -> list[str]`, "One draft text per section, grounded in the given evidence."). Research is a dict keyed by concept id with `sources`/`evidence` lists (see usage in `drafting.py:43-48`).
- Stage name: `drafting`; score `draft_score`, gate `metric_fidelity >= 0.99` ("zero fabricated metrics", `ip_eval/race.py:816-822`).
- discovery/skip semantics: `ip_eval/candidates.py:744-771` (`all_candidates`), `candidates.py:774-795` (`candidates_for`).

## Acceptance

The line boss runs these; self-check what you can:

- `cd racetrack/ip-eval && python3 -m ip_eval.cli selftest` stays green
- `python3 -m ip_eval.cli list` shows the new candidates under the `drafting` stage
- `python3 -m ip_eval.cli race drafting` completes with each new candidate either scored (det check intact) or listed under candidates_unavailable with a truthful reason
- zero leaderboard rows with fails>0 caused by adapter bugs
