# Pack 06 — graph_extra.py (seat: hermes/ollama)

## Objective

Create exactly ONE new file: `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval/ip_eval/candidates_extra/graph_extra.py` registering four new candidates for the `graph` stage: `ontocast-graph`, `hypermem-graph`, `graphify-graph`, and `zeroclaw-graph`. Each implements `graph(concepts: list[dict]) -> dict`. Output contract (exact): `graph(concepts) -> {"nodes": [names], "edges": [(name, name)]}` — nodes are concept names (strings), edges are name-pairs (tuples/lists of two strings, undirected, deterministic order). `graphify-graph` reuses the existing `graphify` venv (rapidfuzz + numpy) read-only; `zeroclaw-graph` is Rust/cargo-gated with honest unavailability if cargo can't build.

## Parent node

racetrack/ip-eval candidate-expansion tranche; suite root `/home/npwad/coding/docker-envs/projects/evo-myworld/racetrack/ip-eval`

## Boundaries and anti-patterns

Non-negotiable rules (verbatim, apply to every line you write):

- Boundaries: write ONLY the one new file `racetrack/ip-eval/ip_eval/candidates_extra/graph_extra.py`. Never edit `race.py`, `oracle.py`, `fixtures.py`, `candidates.py`, other packs, or results files. Never commit.
- Honesty: NEVER fabricate scores or outputs. If a dependency can't provision on this box (no java, no cargo, no model weights, needs a server), `available()` returns `(False, "<truthful reason>")` after purging any partial venv. An unavailable candidate with a true reason is a SUCCESS; a fake score is a failure.
- `available()` must never raise — wrap provisioning in try/except and downgrade to unavailable (see how candidates_for at candidates.py:779-785 treats exceptions).
- provision_venv reuses existing venvs WITHOUT reinstalling changed package lists — purge-on-failure, and keep package lists minimal (disk is tight).
- Import shim header: follow the standalone-safe style used in `ip_eval/candidates_extra/tabilify.py` (sys.path.insert + `from ip_eval.candidates import Candidate, provision_venv`).
- End the file with `CANDIDATES = [YourClass, ...]`.
- Server-class repos (elasticsearch, meilisearch, qdrant, couchdb, airflow, PaddleOCR server mode) are NOT in these packs except where listed; where a pack includes a repo that needs a server, gate it: `available()` returns False with reason "needs docker lane" unless env `RACETRACK_DOCKER=1`.

Pack-specific notes:

- `ontocast-graph` (corpus `growgraph_ontocast/code/ontocast/...`): OntoCast's graph construction is LLM/SPARQL-driven (rdf/owl triples via LLM). If no deterministic, LLM-free graph builder exists in the repo, honest unavailable with the true reason — do not relabel a generic co-occurrence builder as "ontocast".
- `hypermem-graph` (corpus `EverMind-AI_HyperMem/code/hypermem/main/stage{2,4}_hypergraph_*.py`): read the hypergraph stage files; LLM-dependent → honest unavailable with true reason.
- `graphify-graph` (corpus `Graphify-Labs_graphify/code/graphify/{build,validate,dedup,global_graph}.py`): REUSE the shared `.venv-candidates/graphify` venv (rapidfuzz + numpy) exactly the way `HaystackBM25.available` reuses the haystack venv (`ip_eval/candidates_extra/retrieval.py:130-138`) — check the python exists and imports work; NEVER reinstall or purge another family's venv. Follow the existing graph-family style in `ip_eval/candidates_extra/graph.py` (`NetworkxCooc`, `JaccardGraph`) for the JSON-over-stdin subprocess shape. Only claim graphify behavior the source actually implements (e.g. its build/dedup/global_graph logic); if the corpus modules need deps beyond rapidfuzz+numpy, adapt honestly or report unavailable.
- `zeroclaw-graph` (corpus `zeroclaw-labs_zeroclaw/code/crates/zeroclaw-memory/src/dedup.rs`): Rust. Follow the `_build_undoc` cargo-shim approach (`ip_eval/candidates_extra/extraction.py:197-231`) — copy to /tmp, thin shim crate, `cargo build --release`, binary under `.venv-candidates/`, /tmp always deleted. If `cargo` is absent (`shutil.which("cargo")`) or the build fails, `available()` returns False with the true reason. NOTE: the mapping places zeroclaw under dedup tests (S7.04/S7.05), not graph — a graph adapter is honest ONLY if the repo genuinely offers a reusable similarity/edge computation; otherwise report unavailable with that explanation.
- Determinism: node order = input concept order; edges sorted; identical inputs → byte-identical outputs across REPS.

## Pointer traces

- Mapping rows (corpus base `/home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/`):
  - `| **ONTO** | `growgraph_ontocast` | `code/ontocast/tool/chunk/chunker.py`, `tool/agg/entity_aligner.py` |`
  - `| **HMEM** | `EverMind-AI_HyperMem` | `code/hypermem/main/stage{2,4}_hypergraph_*.py` |`
  - `| **GRAPHIFY** | `Graphify-Labs_graphify` | `code/graphify/{build,validate,dedup,global_graph}.py` |`
  - `| **ZERO** | `zeroclaw-labs_zeroclaw` | `code/crates/zeroclaw-memory/src/dedup.rs` |`
  - D-rows: `| **S5.01** | Nodes: alias, homonym, nesting, cross-document repetition; ... | `growgraph_ontocast` (ONTO), `EverMind-AI_HyperMem` (HMEM), `Graphify-Labs_graphify` (GRAPHIFY) | ... |`; `| **S5.03** | Co-occurrence windows: ... | `growgraph_ontocast` (ONTO), `EverMind-AI_HyperMem` (HMEM) | `Graphify-Labs_graphify` (GRAPHIFY) |`; `| **S7.04** | Exact paragraph dedup: ... | `mvanhorn_last30days-skill` (LAST30), `zeroclaw-labs_zeroclaw` (ZERO), `Graphify-Labs_graphify` (GRAPHIFY), ... |` (zeroclaw's actual mapping row — see pack notes).
- Exemplars to follow: `ip_eval/candidates_extra/graph.py` (`NetworkxCooc` venv subprocess `:28-61`, `JaccardGraph` pure-stdlib `:64-84`); venv-reuse idiom `ip_eval/candidates_extra/retrieval.py:130-138`; cargo-shim idiom `ip_eval/candidates_extra/extraction.py:144-259`; honest-unavailable idiom `ip_eval/candidates_extra/concepts.py:152-171`.
- Interface signature: `ip_eval/candidates.py:112-114` (`graph(concepts) -> dict`, docstring specifies exactly `{"nodes": [names], "edges": [(name, name)]}`), `candidates.py:92-93` (`available()`).
- Concepts input rows carry `name`, `type`, `sectionIds` (see `MdTableParser` concepts output, `ip_eval/candidates_extra/tabilify.py:153-164`, and `JaccardGraph`'s use of `sectionIds`/`evidence`).
- Stage name: `graph`; score `0.4*node_f1 + 0.3*edge_precision + 0.3*edge_recall`, gate `node_f1 > 0.0` vs gold co-occurrence edges (`ip_eval/race.py:809-814`).
- discovery/skip semantics: `ip_eval/candidates.py:744-771` (`all_candidates`), `candidates.py:774-795` (`candidates_for`).

## Acceptance

The line boss runs these; self-check what you can:

- `cd racetrack/ip-eval && python3 -m ip_eval.cli selftest` stays green
- `python3 -m ip_eval.cli list` shows the new candidates under the `graph` stage
- `python3 -m ip_eval.cli race graph` completes with each new candidate either scored (det check intact) or listed under candidates_unavailable with a truthful reason
- zero leaderboard rows with fails>0 caused by adapter bugs
