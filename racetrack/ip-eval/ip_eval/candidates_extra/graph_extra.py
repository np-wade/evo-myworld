"""Graph family — extra corpus candidates (pack 06).

- ontocast-graph: growgraph_ontocast. OntoCast's graph construction is
  LLM/SPARQL-driven (rdf/owl triples extracted via LLM); its only LLM-free
  aggregation path (tool/agg EntityAligner / EmbeddingBasedAggregator) needs
  sentence-transformers embedding weights. No deterministic, LLM-free graph
  builder exists in the repo, so this candidate is honestly unavailable.
- hypermem-graph: EverMind-AI_HyperMem. stage2_hypergraph_extraction.py is
  LLMProvider-driven and stage4_hypergraph_retrieval.py needs
  EmbeddingProvider/RerankerProvider — LLM-dependent, honestly unavailable.
- graphify-graph: Graphify-Labs_graphify. Reuses the shared
  .venv-candidates/graphify venv (rapidfuzz + numpy) READ-ONLY — never
  installs or purges another family's venv. Co-occurrence edges from shared
  sectionIds are passed through graphify's own
  graphify.dedup.deduplicate_entities (MinHash/LSH + Jaro-Winkler entity
  merge with edge rewiring), which is the graphify logic under test.
- zeroclaw-graph: zeroclaw-labs_zeroclaw (Rust). The repo's reusable
  similarity is zeroclaw_memory::conflict::jaccard_similarity (token-overlap
  Jaccard, the same function dedup.rs's dedup_gate uses via
  find_text_conflicts). A thin shim crate is built against a /tmp copy of the
  workspace; edges are pairs scoring above the dedup threshold. Honestly
  unavailable when cargo is absent or the build fails.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import REPOS, VENVS, Candidate, _run  # noqa: E402


class OntocastGraph(Candidate):
    """growgraph_ontocast — honest unavailable.

    Graph construction in OntoCast is LLM/SPARQL-driven (tool/llm.py,
    triple_manager). The deterministic-looking alternative,
    tool/agg/aggregate.py EmbeddingBasedAggregator + entity_aligner.py,
    clusters entities with a sentence-transformers embedding model
    (paraphrase-multilingual-MiniLM-L12-v2) — model weights we must not
    download. There is no LLM-free, weight-free graph builder to adapt, and
    relabeling a generic co-occurrence builder as "ontocast" would be a lie.
    """
    name = "ontocast-graph"
    stages = {"graph"}
    SRC = REPOS / "growgraph_ontocast" / "code" / "ontocast"

    def available(self):
        if not (self.SRC / "tool" / "agg" / "entity_aligner.py").exists():
            return False, f"corpus path missing: {self.SRC}"
        return False, (
            "ontocast graph construction is LLM/SPARQL-driven; the only "
            "LLM-free aggregation path (tool/agg EntityAligner) requires "
            "sentence-transformers embedding weights "
            "(paraphrase-multilingual-MiniLM-L12-v2), and model-weight "
            "downloads are out of scope — no deterministic LLM-free graph "
            "builder exists in the repo"
        )


class HypermemGraph(Candidate):
    """EverMind-AI_HyperMem — honest unavailable.

    stage2_hypergraph_extraction.py builds the hypergraph from
    LLMProvider-driven fact/topic/hypergraph extractors; stage4 retrieval
    additionally needs EmbeddingProvider and RerankerProvider. No
    deterministic LLM-free hypergraph builder exists in the repo.
    """
    name = "hypermem-graph"
    stages = {"graph"}
    SRC = REPOS / "EverMind-AI_HyperMem" / "code" / "hypermem" / "main"

    def available(self):
        if not (self.SRC / "stage2_hypergraph_extraction.py").exists():
            return False, f"corpus path missing: {self.SRC}"
        return False, (
            "hypermem stage2 hypergraph extraction is LLMProvider-driven and "
            "stage4 retrieval requires EmbeddingProvider/RerankerProvider; "
            "no deterministic LLM-free hypergraph builder exists in the repo"
        )


class GraphifyGraph(Candidate):
    """Graphify-Labs_graphify dedup logic over the co-occurrence graph.

    Edges come from shared sectionIds (the stage's standard co-occurrence
    signal, same as networkx-cooc); the graphify behavior under test is
    graphify.dedup.deduplicate_entities — MinHash/LSH + Jaro-Winkler merging
    of near-duplicate entity labels with edges rewired to survivors. Sections
    map to graphify's source_file notion (first sectionId), so its same-file
    vs cross-file merge guards apply as designed.

    Runs in the SHARED .venv-candidates/graphify venv (rapidfuzz + numpy),
    read-only: if the venv is absent or broken this candidate reports
    unavailable — it never reinstalls or purges another family's venv.
    """
    name = "graphify-graph"
    stages = {"graph"}
    PKG = "Graphify-Labs_graphify/code"
    TIMEOUT = 90

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        try:
            if not (REPOS / self.PKG / "graphify" / "dedup.py").exists():
                return False, f"corpus path missing: {self.PKG}/graphify/dedup.py"
            python = VENVS / "graphify" / "bin" / "python"
            if not python.exists():
                return False, (
                    "shared graphify venv missing (.venv-candidates/graphify); "
                    "it is provisioned on demand by the graphify-dedup "
                    "candidate and reused read-only here"
                )
            probe = _run(
                [str(python), "-c",
                 "import rapidfuzz, numpy; "
                 f"import sys; sys.path.insert(0, {str(REPOS / self.PKG)!r}); "
                 "from graphify.dedup import deduplicate_entities"],
                timeout=120)
            if probe.returncode != 0:
                return False, f"graphify venv import failed: {probe.stderr.decode()[-200:]}"
            self._python = python
            return True, ""
        except Exception as exc:  # available() must never raise
            return False, f"graphify availability probe failed: {exc}"

    def graph(self, concepts: list[dict]) -> dict:
        nodes = [
            {"name": c["name"],
             "source_file": str(c.get("sectionIds", [""])[0])
             if c.get("sectionIds") else ""}
            for c in concepts
        ]
        edges = []
        for i, a in enumerate(concepts):
            for b in concepts[i + 1:]:
                if set(a.get("sectionIds", [])) & set(b.get("sectionIds", [])):
                    edges.append((a["name"], b["name"]))
        script = (
            "import sys, json\n"
            f"sys.path.insert(0, {str(REPOS / self.PKG)!r})\n"
            "from graphify.dedup import deduplicate_entities\n"
            "req = json.load(sys.stdin)\n"
            "nodes = [{'id': n['name'], 'label': n['name'],\n"
            "          'source_file': n['source_file']} for n in req['nodes']]\n"
            "edges = [{'source': a, 'target': b} for a, b in req['edges']]\n"
            "kept, rewired = deduplicate_entities(\n"
            "    nodes, edges, communities={n['id']: 0 for n in nodes})\n"
            "out = sorted({tuple(sorted((e['source'], e['target'])))\n"
            "              for e in rewired})\n"
            "print(json.dumps({'nodes': [n['label'] for n in kept],\n"
            "                  'edges': out}))\n"
        )
        proc = _run([str(self._python), "-c", script],
                    stdin_data=json.dumps({"nodes": nodes, "edges": edges}).encode(),
                    timeout=self.TIMEOUT)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-300:])
        # graphify prints a "[graphify] Deduplicated ..." line to stdout when
        # merges happen — the JSON payload is the last non-empty line.
        last_line = [l for l in proc.stdout.decode().splitlines() if l.strip()][-1]
        return json.loads(last_line)


# ---------------------------------------------------------------------------
# zeroclaw (zeroclaw-labs_zeroclaw, Rust, built from a corpus copy under /tmp)
# ---------------------------------------------------------------------------

ZEROCLAW_SRC = REPOS / "zeroclaw-labs_zeroclaw" / "code"
ZEROCLAW_BIN = VENVS / "zeroclaw-graph" / "bin" / "zeroclaw-graph"
ZEROCLAW_BUILD_TIMEOUT_S = 900
# dedup.rs gates near-duplicates with cfg.dedup_jaccard_threshold (0.5 in its
# own tests) via conflict::find_text_conflicts (sim > threshold).
ZEROCLAW_JACCARD_THRESHOLD = 0.5

_SHIM_CARGO_TOML = """\
[package]
name = "zeroclaw-graph"
version = "0.1.0"
edition = "2021"

[dependencies]
zeroclaw-memory = { path = "__ZEROCLAW_SRC__/crates/zeroclaw-memory" }
serde_json = "1.0"

[profile.release]
lto = false
codegen-units = 4
"""

_SHIM_MAIN_RS = """\
// Thin graph front-end over zeroclaw-memory's reusable text similarity:
// conflict::jaccard_similarity is the token-overlap Jaccard that dedup.rs's
// dedup_gate applies through find_text_conflicts. We reuse exactly that
// function to score concept pairs; pairs above the dedup threshold become
// edges. Reads {"texts": [...], "threshold": f64} on stdin, writes
// {"edges": [[i, j], ...]} on stdout.
use std::io::Read;
use zeroclaw_memory::conflict::jaccard_similarity;

fn main() {
    let mut buf = String::new();
    std::io::stdin().read_to_string(&mut buf).expect("read stdin");
    let req: serde_json::Value = serde_json::from_str(&buf).expect("parse json");
    let texts: Vec<String> = req["texts"]
        .as_array()
        .expect("texts array")
        .iter()
        .map(|v| v.as_str().expect("text string").to_string())
        .collect();
    let threshold = req["threshold"].as_f64().unwrap_or(0.5);
    let mut edges: Vec<[usize; 2]> = Vec::new();
    for i in 0..texts.len() {
        for j in (i + 1)..texts.len() {
            if jaccard_similarity(&texts[i], &texts[j]) > threshold {
                edges.push([i, j]);
            }
        }
    }
    println!("{}", serde_json::json!({ "edges": edges }));
}
"""


def _build_zeroclaw() -> tuple[Path | None, str]:
    """Build the zeroclaw shim binary in a /tmp copy; never inside the corpus."""
    if ZEROCLAW_BIN.exists():
        return ZEROCLAW_BIN, ""
    if not shutil.which("cargo"):
        return None, "cargo not on PATH"
    if not (ZEROCLAW_SRC / "crates" / "zeroclaw-memory" / "Cargo.toml").exists():
        return None, f"corpus path missing: {ZEROCLAW_SRC}/crates/zeroclaw-memory"
    tmp = Path(tempfile.mkdtemp(prefix="zeroclaw-build-"))
    try:
        # zeroclaw-memory's manifest uses workspace-inherited deps, so the
        # whole workspace tree must be copied for the path dependency to
        # resolve (member manifests are read during workspace resolution).
        src_copy = tmp / "src"
        shutil.copytree(ZEROCLAW_SRC, src_copy,
                        ignore=shutil.ignore_patterns("target", ".git"))
        shim = tmp / "shim"
        (shim / "src").mkdir(parents=True)
        (shim / "Cargo.toml").write_text(
            _SHIM_CARGO_TOML.replace("__ZEROCLAW_SRC__", src_copy.as_posix()))
        (shim / "src" / "main.rs").write_text(_SHIM_MAIN_RS)
        try:
            proc = _run(
                ["cargo", "build", "--release",
                 "--manifest-path", str(shim / "Cargo.toml")],
                timeout=ZEROCLAW_BUILD_TIMEOUT_S,
                env={"CARGO_TARGET_DIR": str(tmp / "target")},
            )
        except subprocess.TimeoutExpired:
            return None, f"cargo build timed out after {ZEROCLAW_BUILD_TIMEOUT_S}s"
        binary = tmp / "target" / "release" / "zeroclaw-graph"
        if proc.returncode != 0 or not binary.exists():
            return None, f"cargo build failed: {proc.stderr.decode()[-300:]}"
        ZEROCLAW_BIN.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, ZEROCLAW_BIN)
        return ZEROCLAW_BIN, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # /tmp build dir always deleted


class ZeroclawGraph(Candidate):
    """zeroclaw-labs_zeroclaw token-Jaccard similarity edges (Rust shim).

    Honest scope: zeroclaw's mapping row is dedup (S7.04/S7.05), not graph;
    this adapter exists only because the repo genuinely offers a reusable
    similarity computation — conflict::jaccard_similarity, the same function
    dedup.rs's dedup_gate uses. Edges are concept pairs whose
    name+evidence Jaccard exceeds the dedup threshold (0.5). Nodes are all
    input concept names in input order.
    """
    name = "zeroclaw-graph"
    stages = {"graph"}
    TIMEOUT = 60

    def __init__(self):
        self._bin: Path | None = None

    def available(self):
        try:
            self._bin, reason = _build_zeroclaw()
            return (self._bin is not None), reason
        except Exception as exc:  # available() must never raise
            return False, f"zeroclaw build failed: {exc}"

    def graph(self, concepts: list[dict]) -> dict:
        names = [c["name"] for c in concepts]
        texts = [f"{c['name']} {c.get('evidence', '')}" for c in concepts]
        payload = {"texts": texts, "threshold": ZEROCLAW_JACCARD_THRESHOLD}
        try:
            proc = _run([str(self._bin)],
                        stdin_data=json.dumps(payload).encode(),
                        timeout=self.TIMEOUT)
        except subprocess.TimeoutExpired:
            raise RuntimeError("zeroclaw-graph subprocess timed out")
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-300:])
        idx_edges = json.loads(proc.stdout.decode())["edges"]
        edges = sorted({tuple(sorted((names[i], names[j]))) for i, j in idx_edges})
        return {"nodes": names, "edges": edges}


CANDIDATES = [OntocastGraph, HypermemGraph, GraphifyGraph, ZeroclawGraph]
