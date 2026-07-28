"""Index+query stage — the search bracket (Search Jobs B/C, finally raced).

Each candidate indexes a corpus of {path: {title, body_text}} and answers a
query with a ranked list of answer paths. The standalone race feeds the FULL
gold corpus so index quality is isolated from crawl completeness; the pipeline
feeds whatever the winning crawler actually reached (so a static crawl that
missed the /item pages simply can't answer the item queries — search recall then
inherits the crawl gap, which is the lesson).

Candidates:
  stdlib-bm25  : pure-python BM25 baseline (always available)
  tantivy      : Rust full-text engine via the `tantivy` wheel (keyword)
  meilisearch  : HTTP to a local meilisearch container (keyword, typo-tolerant)
  qdrant       : qdrant local-mode + fastembed vectors (semantic)   [gated]
  lance        : lancedb embedded + the SAME fastembed model (semantic) [gated]

The two vector engines (qdrant, lance) embed with the identical fastembed model
(BAAI/bge-small-en, cosine) via the shared `_embed_text()` builder, so their race
is a fair head-to-head of the index, not of the embedding.
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass

_WORD = re.compile(r"[a-z0-9]+")


def _tok(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


# Fastembed model shared by every dense-vector candidate (qdrant's own default,
# so lance vs qdrant is a fair head-to-head of the index rather than the model).
DENSE_MODEL = "BAAI/bge-small-en"


def _embed_text(title: str, body: str) -> str:
    """Build the document text fed to a dense embedder, cleaning crawl noise so a
    slightly-degraded CRAWLED body embeds as well as the clean gold body:
      * drop nav path fragments (tokens starting with '/', e.g. '/blog') — pure
        noise to a semantic model that crowds real content on short pages;
      * collapse a title the HTML extractor echoed into the head of the body
        (crawl4ai repeats the <h1>), so the title isn't double/triple counted.
    On the clean gold corpus (no path tokens, no echoed title) this is a no-op,
    so the standalone index race is unchanged — it only repairs the crawled
    pipeline corpus, where these two artifacts tip a razor-thin ranking."""
    toks = [t for t in (body or "").split() if not t.startswith("/")]
    body2 = " ".join(toks)
    tl = (title or "").strip().lower()
    if tl:
        low = body2.lower()
        while low.startswith(tl):
            body2 = body2[len(tl):].lstrip(" .:-")
            low = body2.lower()
    return f"{title}. {body2}".strip()


class BaseIndex:
    name = "base"
    def available(self) -> bool: return False
    def build(self, docs: dict): ...
    def search(self, q: str, k: int = 5) -> list[str]: return []
    def close(self): pass


class StdlibBM25(BaseIndex):
    name = "stdlib-bm25"
    k1, b = 1.5, 0.75
    def available(self) -> bool: return True
    def build(self, docs: dict):
        self.paths = list(docs)
        self.docs = {p: _tok(d.get("title", "") + " " + d.get("body_text", ""))
                     for p, d in docs.items()}
        self.tf = {p: Counter(toks) for p, toks in self.docs.items()}
        self.len = {p: len(toks) for p, toks in self.docs.items()}
        self.avgdl = (sum(self.len.values()) / len(self.len)) if self.len else 0
        self.df: Counter = Counter()
        for toks in self.docs.values():
            self.df.update(set(toks))
        self.N = len(self.docs)
    def _idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        return math.log(1 + (self.N - n + 0.5) / (n + 0.5))
    def search(self, q: str, k: int = 5) -> list[str]:
        qt = _tok(q)
        scores: dict[str, float] = defaultdict(float)
        for p in self.paths:
            for term in qt:
                f = self.tf[p].get(term, 0)
                if not f:
                    continue
                dl = self.len[p]
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                scores[p] += self._idf(term) * f * (self.k1 + 1) / denom
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return [p for p, s in ranked if s > 0][:k]


class TantivyIndex(BaseIndex):
    name = "tantivy"
    def available(self) -> bool:
        try:
            import tantivy  # noqa: F401
            return True
        except Exception:
            return False
    def build(self, docs: dict):
        import tantivy
        sb = tantivy.SchemaBuilder()
        sb.add_text_field("path", stored=True)
        sb.add_text_field("title", stored=False)
        sb.add_text_field("body", stored=False)
        self.schema = sb.build()
        self.ix = tantivy.Index(self.schema)
        w = self.ix.writer()
        for p, d in docs.items():
            w.add_document(tantivy.Document(
                path=p, title=d.get("title", ""), body=d.get("body_text", "")))
        w.commit()
        self.ix.reload()
    def search(self, q: str, k: int = 5) -> list[str]:
        searcher = self.ix.searcher()
        query = self.ix.parse_query(q, ["title", "body"])
        hits = searcher.search(query, k).hits
        out = []
        for _, addr in hits:
            doc = searcher.doc(addr)
            out.append(doc["path"][0])
        return out


class MeiliIndex(BaseIndex):
    name = "meilisearch"
    URL = "http://127.0.0.1:7700"
    IDX = "crawl_eval"
    def _req(self, method, path, body=None, timeout=5):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.URL + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    def available(self) -> bool:
        try:
            h = self._req("GET", "/health", timeout=2)
            return h.get("status") == "available"
        except Exception:
            return False
    def build(self, docs: dict):
        # doc id must be a safe string; map path <-> id
        self.byid = {}
        payload = []
        for i, (p, d) in enumerate(docs.items()):
            self.byid[str(i)] = p
            payload.append({"id": str(i), "path": p, "title": d.get("title", ""),
                            "body": d.get("body_text", "")})
        try:
            self._req("DELETE", f"/indexes/{self.IDX}")
        except Exception:
            pass
        task = self._req("POST", f"/indexes/{self.IDX}/documents", payload)
        # wait for the async indexing task
        tid = task.get("taskUid", task.get("uid"))
        for _ in range(50):
            st = self._req("GET", f"/tasks/{tid}")
            if st.get("status") in ("succeeded", "failed"):
                break
            time.sleep(0.1)
    def search(self, q: str, k: int = 5) -> list[str]:
        res = self._req("POST", f"/indexes/{self.IDX}/search",
                        {"q": q, "limit": k})
        return [h["path"] for h in res.get("hits", [])]


class QdrantIndex(BaseIndex):
    name = "qdrant"
    COLL = "crawl_eval"
    def available(self) -> bool:
        try:
            import qdrant_client  # noqa: F401
            import fastembed  # noqa: F401
            return True
        except Exception:
            return False
    def build(self, docs: dict):
        from qdrant_client import QdrantClient
        self.client = QdrantClient(location=":memory:")
        self.paths, texts, ids = [], [], []
        for i, (p, d) in enumerate(docs.items()):
            self.paths.append(p)
            texts.append(_embed_text(d.get("title", ""), d.get("body_text", "")))
            ids.append(i)
        # qdrant-client's .add() uses fastembed (DENSE_MODEL) under the hood
        self.client.add(collection_name=self.COLL, documents=texts, ids=ids,
                        metadata=[{"path": p} for p in self.paths])
    def search(self, q: str, k: int = 5) -> list[str]:
        hits = self.client.query(collection_name=self.COLL, query_text=q, limit=k)
        return [h.metadata["path"] for h in hits]
    def close(self):
        try:
            self.client.close()
        except Exception:
            pass


class LanceIndex(BaseIndex):
    """lancedb embedded (no server) + fastembed. Same DENSE_MODEL and cosine
    metric as qdrant, same _embed_text builder → a fair vector head-to-head. The
    table lives in a throwaway temp dir; close() removes it."""
    name = "lance"
    TABLE = "crawl_eval"
    _model = None
    def available(self) -> bool:
        try:
            import lancedb        # noqa: F401
            import pyarrow        # noqa: F401
            import fastembed      # noqa: F401
            return True
        except Exception:
            return False
    def _embed(self, texts: list[str]) -> list[list[float]]:
        from fastembed import TextEmbedding
        if LanceIndex._model is None:
            LanceIndex._model = TextEmbedding(model_name=DENSE_MODEL)
        return [v.tolist() for v in LanceIndex._model.embed(list(texts))]
    def build(self, docs: dict):
        import tempfile
        import lancedb
        self._dir = tempfile.mkdtemp(prefix="lance_ce_")
        self.paths, texts = [], []
        for p, d in docs.items():
            self.paths.append(p)
            texts.append(_embed_text(d.get("title", ""), d.get("body_text", "")))
        vecs = self._embed(texts)
        rows = [{"path": p, "vector": v} for p, v in zip(self.paths, vecs)]
        db = lancedb.connect(self._dir)
        self.tbl = db.create_table(self.TABLE, data=rows, mode="overwrite")
    def search(self, q: str, k: int = 5) -> list[str]:
        qv = self._embed([q])[0]
        res = self.tbl.search(qv).metric("cosine").limit(k).to_list()
        return [r["path"] for r in res]
    def close(self):
        import shutil
        shutil.rmtree(getattr(self, "_dir", "") or ".", ignore_errors=True)


ALL_INDEXES = [StdlibBM25(), TantivyIndex(), MeiliIndex(), QdrantIndex(),
               LanceIndex()]


def available_indexes() -> list[BaseIndex]:
    return [i for i in ALL_INDEXES if i.available()]
