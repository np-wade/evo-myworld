# Pack 03 — concepts_extra.py (seat: poe)

## Objective

Create exactly ONE new file: `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval/ip_eval/candidates_extra/concepts_extra.py` registering four new candidates for the `concepts` stage: `ontocast-concepts`, `opennlp-ner`, `nemo-gliner`, and `wittgenstein-rules`. Each implements `concepts(sections: list[dict]) -> list[dict]` returning concept rows in the incumbent's shape (`[{"name", "type", ...}]` — match the shape emitted by the existing concepts candidates, e.g. `{"name": ..., "type": "Concept", "mentions": n}`). LLM- or Java-gated candidates must honestly report unavailable with the true reason.

## Parent node

racetrack/ip-eval candidate-expansion tranche; suite root `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval`

## Boundaries and anti-patterns

Non-negotiable rules (verbatim, apply to every line you write):

- Boundaries: write ONLY the one new file `racetrack/ip-eval/ip_eval/candidates_extra/concepts_extra.py`. Never edit `race.py`, `oracle.py`, `fixtures.py`, `candidates.py`, other packs, or results files. Never commit.
- Honesty: NEVER fabricate scores or outputs. If a dependency can't provision on this box (no java, no cargo, no model weights, needs a server), `available()` returns `(False, "<truthful reason>")` after purging any partial venv. An unavailable candidate with a true reason is a SUCCESS; a fake score is a failure.
- `available()` must never raise — wrap provisioning in try/except and downgrade to unavailable (see how candidates_for at candidates.py:779-785 treats exceptions).
- provision_venv reuses existing venvs WITHOUT reinstalling changed package lists — purge-on-failure, and keep package lists minimal (disk is tight).
- Import shim header: follow the standalone-safe style used in `ip_eval/candidates_extra/tabilify.py` (sys.path.insert + `from ip_eval.candidates import Candidate, provision_venv`).
- End the file with `CANDIDATES = [YourClass, ...]`.
- Server-class repos (elasticsearch, meilisearch, qdrant, couchdb, airflow, PaddleOCR server mode) are NOT in these packs except where listed; where a pack includes a repo that needs a server, gate it: `available()` returns False with reason "needs docker lane" unless env `RACETRACK_DOCKER=1`.

Pack-specific notes:

- `ontocast-concepts`: corpus `growgraph_ontocast/code/ontocast/tool/agg/entity_aligner.py` (+ `tool/chunk/chunker.py` for context). OntoCast is LLM/SPARQL-driven — if its extraction path cannot run without an LLM endpoint, follow the `FastTextConcepts` idiom: attempt the honest check, then return `(False, "<true reason>")`. Do NOT substitute a regex and call it ontocast.
- `opennlp-ner` (corpus `apache_opennlp`, Java/Maven): Java-gated honest refusal; check `shutil.which("java")`, do NOT attempt maven builds.
- `nemo-gliner`: corpus `NVIDIA-NeMo_Guardrails/code/nemoguardrails/library/gliner/{actions,request}.py`. venv-gated: provision a minimal venv (e.g. `gliner` package only — NOT the full `nemoguardrails` stack, disk is tight). GLiNER weights are downloaded from HF at first use; if weights cannot download on this box, `available()` returns False with the true reason after purging. If the gliner pip path cannot work without NeMo's action runtime, say so truthfully.
- `wittgenstein-rules`: corpus `imoscovitz_wittgenstein/code/wittgenstein/ripper.py`, `abstract_ruleset_classifier.py`. RIPPER is a supervised rule classifier — like `FastTextConcepts`, if there is no honest adaptation from rule-classification to concept extraction, report unavailable with exactly that reason. Only implement `concepts()` if the adaptation is honest (e.g. deterministic rules over section text with no invented labels).
- Follow the honest-unavailable idiom in `ip_eval/candidates_extra/concepts.py:152-171` (`FastTextConcepts`) wherever the repo cannot genuinely do concept extraction on this box.

## Pointer traces

- Mapping rows (corpus base `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/`):
  - `| **ONTO** | `growgraph_ontocast` | `code/ontocast/tool/chunk/chunker.py`, `tool/agg/entity_aligner.py` |`
  - `| **OPEN** | `apache_opennlp` | `opennlp-runtime/src/main/java/opennlp/tools/{sentdetect,namefind}/` |`
  - `| **NEMO** | `NVIDIA-NeMo_Guardrails` | `code/nemoguardrails/library/gliner/{actions,request}.py` |`
  - `| **WITT** | `imoscovitz_wittgenstein` | `code/wittgenstein/ripper.py`, `abstract_ruleset_classifier.py` |`
  - D-rows: `| **S3.01** | Entity/concept recall: people, orgs, methods, datasets, models, materials, variables, processes | `growgraph_ontocast` (ONTO), `apache_opennlp` (OPEN), `data-privacy-stack_presidio` (PRES), `NVIDIA-NeMo_Guardrails` (NEMO) | ... |`; `| **S3.07** | Ontology classification: method/dataset/metric/tool/theory/person/org/material/location | `growgraph_ontocast` (ONTO), `apache_opennlp` (OPEN), `facebookresearch_fastText` (FAST), `imoscovitz_wittgenstein` (WITT) | ... |`; `| **S3.09** | Rules vs statistical classifier: sparse/imbalanced labels, explanation, determinism | `imoscovitz_wittgenstein` (WITT), `facebookresearch_fastText` (FAST), `apache_opennlp` (OPEN) | ... |`.
- Exemplars: `ip_eval/candidates_extra/concepts.py` — `FastTextConcepts` (`:152-171`, honest unavailable), `SpacyNounChunks` (venv subprocess returning `[{'name','type','mentions'}]`, around `:120-149`). Follow whichever fits each candidate.
- Interface signature: `ip_eval/candidates.py:102-103` (`concepts(sections) -> list[dict]`), `candidates.py:92-93` (`available()`), `candidates.py:51-77` (`provision_venv`).
- Stage name: `concepts`; score `0.6*mean_f1 + 0.25*type_accuracy + 0.15*nested_score`, gate `mean_f1 > 0.0` (`ip_eval/race.py:797-801`). Sections input is incumbent-split sections (`[{"id","order","title","content"}]`).
- discovery/skip semantics: `ip_eval/candidates.py:744-771` (`all_candidates`), `candidates.py:774-795` (`candidates_for`).

## Acceptance

The line boss runs these; self-check what you can:

- `cd racetrack/ip-eval && python3 -m ip_eval.cli selftest` stays green
- `python3 -m ip_eval.cli list` shows the new candidates under the `concepts` stage
- `python3 -m ip_eval.cli race concepts` completes with each new candidate either scored (det check intact) or listed under candidates_unavailable with a truthful reason
- zero leaderboard rows with fails>0 caused by adapter bugs
