"""Retrieval family — BM25 + dense hashing baselines, subprocess-in-venv.

Each candidate ranks the fixture sentence corpus per query inside its venv
python (JSON in on stdin, ranked list out on stdout). Indexing is rebuilt per
call: the corpus is ~50 sentences, so per-call build cost is negligible next
to interpreter startup; the trade is zero cross-call state.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..candidates import VENVS, Candidate, _run, provision_venv


def _venv_call(python: Path, script: str, payload: dict, timeout: int = 90) -> list[str]:
    proc = _run([str(python), "-c", script],
                stdin_data=json.dumps(payload).encode(), timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode()[-300:])
    return json.loads(proc.stdout.decode())


class _VenvCandidate(Candidate):
    stages = {"retrieval"}
    VENV = ""
    PIP: list[str] = []
    TIMEOUT = 90

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        self._python, reason = provision_venv(self.VENV, self.PIP)
        return (self._python is not None), reason


class RankBM25(_VenvCandidate):
    """rank_bm25.BM25Okapi over whitespace-tokenized sentences."""
    name = "rank-bm25"
    VENV = "rank-bm25"
    PIP = ["rank_bm25"]

    SCRIPT = (
        "import sys, json\n"
        "from rank_bm25 import BM25Okapi\n"
        "req = json.load(sys.stdin)\n"
        "corpus = req['corpus']\n"
        "bm25 = BM25Okapi([s.split() for s in corpus])\n"
        "scores = bm25.get_scores(req['query'].split())\n"
        "order = sorted(range(len(corpus)), key=lambda i: -scores[i])\n"
        "print(json.dumps([corpus[i] for i in order]))\n"
    )

    def retrieve(self, query: str, corpus: list[str]) -> list[str]:
        if not corpus:
            return []
        return _venv_call(self._python, self.SCRIPT,
                          {"query": query, "corpus": corpus})


class TantivyPy(_VenvCandidate):
    """tantivy-py: fresh in-memory index per call, BM25 ranking."""
    name = "tantivy-py"
    VENV = "tantivy-py"
    PIP = ["tantivy"]

    SCRIPT = (
        "import sys, json\n"
        "import tantivy\n"
        "req = json.load(sys.stdin)\n"
        "corpus = req['corpus']\n"
        "sb = tantivy.SchemaBuilder()\n"
        "sb.add_text_field('body', stored=True)\n"
        "sb.add_unsigned_field('idx', stored=True)\n"
        "index = tantivy.Index(sb.build())\n"
        "writer = index.writer()\n"
        "for i, s in enumerate(corpus):\n"
        "    writer.add_document(tantivy.Document(body=s, idx=i))\n"
        "writer.commit()\n"
        "index.reload()\n"
        "searcher = index.searcher()\n"
        "try:\n"
        "    q = index.parse_query(req['query'], ['body'])\n"
        "except Exception:\n"
        "    q = index.parse_query(' '.join(req['query'].split()), ['body'])\n"
        "hits = searcher.search(q, limit=len(corpus)).hits\n"
        # tantivy does not guarantee a stable order among equal BM25 scores
        # (multithreaded collector); impose one: score desc, corpus idx asc.
        "scored = [(score, int(searcher.doc(addr)['idx'][0])) for score, addr in hits]\n"
        "scored.sort(key=lambda p: (-p[0], p[1]))\n"
        "ranked_idx = [i for _s, i in scored]\n"
        "seen = set(ranked_idx)\n"
        "ranked_idx += [i for i in range(len(corpus)) if i not in seen]\n"
        "print(json.dumps([corpus[i] for i in ranked_idx]))\n"
    )

    def retrieve(self, query: str, corpus: list[str]) -> list[str]:
        if not corpus:
            return []
        return _venv_call(self._python, self.SCRIPT,
                          {"query": query, "corpus": corpus})


class HaystackBM25(_VenvCandidate):
    """haystack-ai InMemoryDocumentStore + InMemoryBM25Retriever.

    REUSES the shared .venv-candidates/haystack venv (already provisioned by
    the split family). Never reinstalls, never purges it.
    """
    name = "haystack-bm25"
    TIMEOUT = 300  # haystack import is heavy

    SCRIPT = (
        "import sys, json\n"
        "from haystack import Document\n"
        "from haystack.document_stores.in_memory import InMemoryDocumentStore\n"
        "from haystack.components.retrievers.in_memory import InMemoryBM25Retriever\n"
        "req = json.load(sys.stdin)\n"
        "corpus = req['corpus']\n"
        "store = InMemoryDocumentStore()\n"
        # explicit ids: the fixture corpus contains duplicate sentences and
        # haystack's default content-hash ids collide on them.
        "store.write_documents([Document(id=f's{i}', content=s) for i, s in enumerate(corpus)])\n"
        "retriever = InMemoryBM25Retriever(document_store=store, top_k=len(corpus))\n"
        "docs = retriever.run(query=req['query'])['documents']\n"
        "print(json.dumps([d.content for d in docs]))\n"
    )

    def available(self):
        python = VENVS / "haystack" / "bin" / "python"
        if not python.exists():
            return False, "shared haystack venv missing (.venv-candidates/haystack)"
        probe = _run([str(python), "-c", "import haystack"], timeout=120)
        if probe.returncode != 0:
            return False, f"haystack import failed: {probe.stderr.decode()[-200:]}"
        self._python = python
        return True, ""

    def retrieve(self, query: str, corpus: list[str]) -> list[str]:
        if not corpus:
            return []
        return _venv_call(self._python, self.SCRIPT,
                          {"query": query, "corpus": corpus},
                          timeout=self.TIMEOUT)


class FaissHashDense(_VenvCandidate):
    """faiss-cpu IndexFlatIP over stdlib signed-hashing embeddings (512-dim).

    Dense baseline with no model download: blake2b token hash -> (index, sign),
    L2-normalized; inner-product search.
    """
    name = "faiss-hashdense"
    VENV = "faiss-hashdense"
    PIP = ["faiss-cpu", "numpy"]
    TIMEOUT = 180

    SCRIPT = (
        "import sys, json, hashlib\n"
        "import numpy as np\n"
        "import faiss\n"
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
        "mat = np.stack([embed(s) for s in corpus])\n"
        "index = faiss.IndexFlatIP(DIM)\n"
        "index.add(mat)\n"
        "q = embed(req['query']).reshape(1, -1)\n"
        "_d, ids = index.search(q, len(corpus))\n"
        "print(json.dumps([corpus[i] for i in ids[0] if i >= 0]))\n"
    )

    def retrieve(self, query: str, corpus: list[str]) -> list[str]:
        if not corpus:
            return []
        return _venv_call(self._python, self.SCRIPT,
                          {"query": query, "corpus": corpus},
                          timeout=self.TIMEOUT)


CANDIDATES = [RankBM25, TantivyPy, HaystackBM25, FaissHashDense]
