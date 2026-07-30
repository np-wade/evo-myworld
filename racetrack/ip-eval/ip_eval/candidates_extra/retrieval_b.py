"""Retrieval family B — ANN-library adapters over stdlib hash embeddings.

Five candidates for the `retrieval` stage, following the venv +
JSON-over-stdio pattern of `candidates_extra/retrieval.py`:

- annoy:    Spotify AnnoyIndex(512, "angular") over the same blake2b
            signed-hashing embeddings as FaissHashDense (corpus
            `spotify_annoy/src/annoylib.h`, `annoymodule.cc`).
- aann:     schlegelp/aann neighbourhood-graph NN search. aann is strictly
            a 3D point-cloud method (`_assert_cloud_3d` in corpus
            `schlegelp_aann/code/aann/core.py:812-816`), so the 512-dim hash
            embedding is deterministically folded to 3D before indexing.
- leann:    honest unavailable — see class docstring.
- ruvector: honest unavailable unless a `ruvector` wheel appears on PyPI.
- pixelrag: honest unavailable — vision-model retrieval, no text-only path.

All embeddings are deterministic (fixed dim, stdlib hashing, no RNG seed
variance); empty corpus -> []; output is corpus strings, best first, stable
across REPS.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate, _run, provision_venv  # noqa: E402


def _venv_call(python: Path, script: str, payload: dict, timeout: int = 180) -> list[str]:
    proc = _run([str(python), "-c", script],
                stdin_data=json.dumps(payload).encode(), timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode()[-300:])
    return json.loads(proc.stdout.decode())


class _VenvCandidate(Candidate):
    stages = {"retrieval"}
    VENV = ""
    PIP: list[str] = []
    TIMEOUT = 180

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        try:
            self._python, reason = provision_venv(self.VENV, self.PIP)
            return (self._python is not None), reason
        except Exception as exc:  # never raise out of available()
            return False, f"provisioning error: {exc}"


# Shared 512-dim blake2b signed-hashing embedding, copied verbatim from
# FaissHashDense (candidates_extra/retrieval.py:159-172). Each SCRIPT below
# prepends this and swaps faiss for its own ANN library.
_EMBED = (
    "import sys, json, hashlib\n"
    "import numpy as np\n"
    "req = json.load(sys.stdin)\n"
    "corpus = req['corpus']\n"
    "DIM = 512\n"
    "def embed(text):\n"
    "    v = np.zeros(DIM, dtype='float32')\n"
    "    for tok in text.lower().split():\n"
    "        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), 'little')\n"
    "        v[h % DIM] += 1.0 if (h >> 32) & 1 else -1.0\n"
    "    n = np.linalg.norm(v)\n"
    "    return v / n if n else v\n"
)


class AnnoyANN(_VenvCandidate):
    """Spotify Annoy over hash embeddings: AnnoyIndex(512, 'angular').

    Index rebuilt per call (corpus ~50 sentences). `set_seed(0)` pins the
    tree-building RNG (corpus `spotify_annoy/src/annoylib.h:1256`,
    `annoymodule.cc:562`), and ties are broken stable: angular distance asc,
    corpus index asc (idiom from TantivyPy, retrieval.py:88-95).
    """
    name = "annoy"
    VENV = "annoy"
    # numpy is required by _EMBED but is NOT a transitive dep of `annoy`
    # (unlike `aann`, which pulls numpy in) — declare it explicitly.
    PIP = ["annoy", "numpy"]

    SCRIPT = _EMBED + (
        "from annoy import AnnoyIndex\n"
        "t = AnnoyIndex(DIM, 'angular')\n"
        "t.set_seed(0)\n"
        "for i, s in enumerate(corpus):\n"
        "    t.add_item(i, embed(s).tolist())\n"
        "t.build(10)\n"
        "ids, dists = t.get_nns_by_vector(\n"
        "    embed(req['query']).tolist(), len(corpus), include_distances=True)\n"
        # annoy does not guarantee a stable order among equal distances;
        # impose one: distance asc, corpus idx asc.
        "order = sorted(zip(dists, ids), key=lambda p: (p[0], p[1]))\n"
        "print(json.dumps([corpus[i] for _d, i in order]))\n"
    )

    def retrieve(self, query: str, corpus: list[str]) -> list[str]:
        if not corpus:
            return []
        return _venv_call(self._python, self.SCRIPT,
                          {"query": query, "corpus": corpus},
                          timeout=self.TIMEOUT)


class AannANN(_VenvCandidate):
    """schlegelp/aann neighbourhood-graph NN search over hash embeddings.

    aann is a 3D point-cloud library: `_assert_cloud_3d` (corpus
    `schlegelp_aann/code/aann/core.py:812-816`) rejects anything but (N, 3)
    arrays. The 512-dim hash embedding is therefore folded to 3D
    deterministically (band-sum over dims j % 3, L2-renormalized) — identical
    tokens still push identical directions, so lexical overlap survives, but
    recall is inherently degraded vs the 512-dim indexes; that is the honest
    cost of adapting a 3D-only index.

    graph="knn" (not the default "delaunay") for both target and query:
    Delaunay triangulation needs >= 4 points in 3D, so it would break on
    small corpora and can never triangulate the single-point query cloud.
    """
    name = "aann"
    VENV = "aann"
    PIP = ["aann"]

    SCRIPT = _EMBED + (
        "import aann\n"
        "def fold3(v):\n"
        "    w = np.array([v[0::3].sum(), v[1::3].sum(), v[2::3].sum()],\n"
        "                 dtype='float32')\n"
        "    n = np.linalg.norm(w)\n"
        "    return w / n if n else w\n"
        "n = len(corpus)\n"
        "mat = np.stack([fold3(embed(s)) for s in corpus])\n"
        "index = aann.AANN(mat, graph='knn', graph_k=8)\n"
        "q = fold3(embed(req['query'])).reshape(1, 3)\n"
        "d, i = index.query(q, k=n, graph='knn')\n"
        # misses are padded as (inf, n) (core.py `_all_miss`); rank by
        # (distance asc, corpus idx asc) and append any unreachable vertices
        # in corpus order so the ranking is complete and stable.
        "pairs = sorted(zip(d[0].tolist(), i[0].tolist()),\n"
        "               key=lambda p: (p[0], p[1]))\n"
        "ranked = [j for _dd, j in pairs if j < n]\n"
        "seen = set(ranked)\n"
        "ranked += [j for j in range(n) if j not in seen]\n"
        "print(json.dumps([corpus[j] for j in ranked]))\n"
    )

    def retrieve(self, query: str, corpus: list[str]) -> list[str]:
        if not corpus:
            return []
        return _venv_call(self._python, self.SCRIPT,
                          {"query": query, "corpus": corpus},
                          timeout=self.TIMEOUT)


class LeannANN(Candidate):
    """LEANN (StarTrail-org) — honest unavailable.

    `leann-core` exists on PyPI (verified 2026-07, 0.3.7) but its declared
    dependencies include torch>=2.0 and sentence-transformers, and its query
    path requires an embedding server / downloaded model weights (corpus
    `StarTrail-org_LEANN/code/packages/leann-core/src/leann/interface.py:75-95`
    `compute_query_embedding` via ZMQ embedding server;
    `embedding_server_manager.py` default `embedding_mode=
    "sentence-transformers"`). Pack rules forbid model-weight downloads and
    multi-GB installs (disk is tight), so no provisioning is attempted.
    """
    name = "leann"
    stages = {"retrieval"}

    def available(self) -> tuple[bool, str]:
        return False, (
            "leann-core on PyPI declares torch>=2.0 + sentence-transformers "
            "and its query path needs an embedding server with downloaded "
            "model weights (embedding_mode='sentence-transformers'); model "
            "downloads and multi-GB installs are forbidden by pack rules, so "
            "no honest minimal venv exists"
        )


class RuvectorANN(Candidate):
    """ruvector (ruvnet) — Rust-only; no Python wheel on PyPI.

    Corpus `ruvnet_ruvector/code/crates/` holds Rust crates only
    (ruvector-acorn, ruvector-matryoshka, ...). We still attempt
    `pip install ruvector` so a future wheel would be detected honestly;
    today PyPI has no such distribution (404, verified 2026-07), the install
    fails fast, and provision_venv purges the partial venv.
    """
    name = "ruvector"
    stages = {"retrieval"}
    VENV = "ruvector"

    def available(self) -> tuple[bool, str]:
        try:
            python, reason = provision_venv(self.VENV, ["ruvector"])
        except Exception as exc:  # never raise out of available()
            return False, f"provisioning error: {exc}"
        if python is None:
            return False, (
                f"no `ruvector` Python wheel on PyPI and the corpus repo is "
                f"Rust-only crates (would need a cargo build beyond a plain "
                f"pip install): {reason}"
            )
        return False, (
            "a `ruvector` distribution installed, but no documented Python "
            "retrieval API has been verified against the corpus crates; "
            "refusing to fake a ranking"
        )


class PixelRagANN(Candidate):
    """PixelRAG (StarTrail-org) — pixel-level multimodal retrieval.

    Verified by reading the corpus: `pixelrag_index/config.py:12` defaults to
    embed model `Qwen/Qwen3-VL-Embedding-2B` on cuda, and
    `eval/lib/retrievers.py` builds ColQwen / Qwen3-VL / contriever
    retrievers — all downloaded vision/embedding models. The `pixelrag`
    package on PyPI (0.4.0) is likewise a visual RAG pipeline (renders pages
    via cef-capi-py Chromium, anthropic API). There is no deterministic
    text-only path, so this is an honest unavailable; model downloads are
    forbidden by pack rules.
    """
    name = "pixelrag"
    stages = {"retrieval"}

    def available(self) -> tuple[bool, str]:
        return False, (
            "PixelRAG is pixel-level multimodal retrieval: the corpus index "
            "defaults to Qwen/Qwen3-VL-Embedding-2B (pixelrag_index/"
            "config.py) and the eval retrievers are ColQwen/Qwen3-VL vision "
            "models; no deterministic text-only path exists and model-weight "
            "downloads are forbidden by pack rules"
        )


CANDIDATES = [AnnoyANN, AannANN, LeannANN, RuvectorANN, PixelRagANN]
