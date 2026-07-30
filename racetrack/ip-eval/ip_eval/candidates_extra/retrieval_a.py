"""Retrieval pack 04 — corpus-repo adapters for the `retrieval` stage.

Six candidates, two runnable pure-stdlib and four honest-unavailable:

- ragbits-rrf: reimplementation of the Reciprocal Rank Fusion kernel from
  deepsense-ai_ragbits `.../retrieval/rerankers/rrf.py:54-64` (score +=
  1/(k + rank), k=1, 1-based rank). The ragbits module itself cannot be
  imported by file path (rrf.py:4-6 pulls in ragbits.core.audit and the
  document_search element/reranker base), and installing the
  `ragbits-document-search` package drags in LLM client deps, so the
  deterministic RRF combinator is reproduced here verbatim-semantics and
  fed two deterministic stdlib rankings (BM25-style + positional). No LLM
  pipeline is imported.
- librer: PJDude_librer's fuzzy-search match primitive,
  `difflib.SequenceMatcher(None, expr, x).ratio()` (record.py:259 and
  :297), applied as a per-sentence relevance score. The application
  itself (librer.py / core.py:50-56) needs tkinter plus zstandard,
  pympler, send2trash, psutil and dateparser, so the module is not
  imported; the stdlib matching kernel is adapted in-process.
- hypermem, wikichat, suql, local-deep-researcher: LLM/server-dependent
  pipelines with no deterministic retrieval sub-component that stands
  alone; each reports unavailable with the true reason (see classes).
"""
from __future__ import annotations

import math
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate, provision_venv  # noqa: E402,F401


def _tokens(text: str) -> list[str]:
    return text.lower().split()


def _bm25_order(query: str, corpus: list[str]) -> list[int]:
    """Corpus indices ranked by a stdlib BM25 (Okapi) score, deterministic."""
    docs = [_tokens(s) for s in corpus]
    n_docs = len(docs)
    avgdl = sum(len(d) for d in docs) / n_docs if n_docs else 0.0
    df: dict[str, int] = {}
    for d in docs:
        for tok in set(d):
            df[tok] = df.get(tok, 0) + 1
    k1, b = 1.5, 0.75
    scores = []
    for i, d in enumerate(docs):
        tf: dict[str, int] = {}
        for tok in d:
            tf[tok] = tf.get(tok, 0) + 1
        score = 0.0
        for tok in set(_tokens(query)):
            f = tf.get(tok, 0)
            if not f:
                continue
            idf = math.log(1 + (n_docs - df[tok] + 0.5) / (df[tok] + 0.5))
            score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / (avgdl or 1.0)))
        scores.append(score)
    return sorted(range(n_docs), key=lambda i: (-scores[i], i))


def _positional_order(query: str, corpus: list[str]) -> list[int]:
    """Corpus indices ranked by query-token coverage, then first-hit position."""
    qtoks = set(_tokens(query))
    keyed = []
    for i, s in enumerate(corpus):
        toks = _tokens(s)
        hits = [pos for pos, tok in enumerate(toks) if tok in qtoks]
        coverage = len({toks[pos] for pos in hits})
        first = min(hits) if hits else len(toks) + 1
        keyed.append((-coverage, first, i))
    return [i for _cov, _first, i in sorted(keyed)]


class RagbitsRRF(Candidate):
    """ragbits ReciprocalRankFusionReranker kernel over two stdlib rankings.

    Fuses a BM25-style ranking and a positional-coverage ranking with the
    exact RRF accumulation from rrf.py:57-62: for each ranked list,
    score[key] += 1 / (rank + 1 + 1) with rank 0-based (i.e. k=1, 1-based
    rank), then sorts by fused score descending (rrf.py:64). Final order
    tie-breaks on corpus index for determinism.
    """
    name = "ragbits-rrf"
    stages = {"retrieval"}

    def available(self) -> tuple[bool, str]:
        return True, ""

    def retrieve(self, query: str, corpus: list[str]) -> list[str]:
        if not corpus:
            return []
        rankings = [_bm25_order(query, corpus), _positional_order(query, corpus)]
        scores: dict[int, float] = {}
        for ranking in rankings:
            for rank, idx in enumerate(ranking):
                scores[idx] = scores.get(idx, 0.0) + 1 / (rank + 1 + 1)
        order = sorted(scores, key=lambda i: (-scores[i], i))
        return [corpus[i] for i in order]


class LibrerFuzzy(Candidate):
    """librer fuzzy-search scoring (record.py:259) as sentence ranking.

    librer's 'By fuzzy match' search kind scores a candidate string x
    against the expression with SequenceMatcher(None, expr, x).ratio()
    and accepts it above a threshold. For ranking we drop the threshold
    and sort the whole corpus by that ratio, best first; ties keep corpus
    order. Pure stdlib, deterministic.
    """
    name = "librer"
    stages = {"retrieval"}

    def available(self) -> tuple[bool, str]:
        return True, ""

    def retrieve(self, query: str, corpus: list[str]) -> list[str]:
        if not corpus:
            return []
        scored = sorted(
            range(len(corpus)),
            key=lambda i: (-SequenceMatcher(None, query, corpus[i]).ratio(), i),
        )
        return [corpus[i] for i in scored]


class _HonestUnavailable(Candidate):
    """Base for candidates whose corpus pipeline cannot run on this box.

    available() never raises and never provisions: the blocker is
    structural (LLM / database / search server required), so no venv
    install could fix it and no disk is spent trying.
    """
    stages = {"retrieval"}
    REASON = "unavailable"

    def available(self) -> tuple[bool, str]:
        try:
            return False, self.REASON
        except Exception as exc:  # pragma: no cover - defensive
            return False, f"available() failed: {exc}"


class HyperMem(_HonestUnavailable):
    """EverMind-AI_HyperMem hypergraph retrieval.

    stage2_hypergraph_extraction.py:30-46 builds topics/facts/hyperedges
    via hypermem.llm.llm_provider.LLMProvider; stage4_hypergraph_retrieval.py
    :37-39 needs EmbeddingProvider and RerankerProvider. Both require LLM +
    embedding API endpoints (keys, models) that do not exist on this box;
    no deterministic retrieval sub-component stands alone.
    """
    name = "hypermem"
    REASON = ("hypergraph extraction/retrieval stages call LLM, embedding "
              "and reranker providers (hypermem.llm.*); needs live LLM API "
              "endpoints and model access not available on this box")


class WikiChat(_HonestUnavailable):
    """stanford-oval_WikiChat listwise LLM reranker.

    retrieval/llm_reranker.py:12-17,40-47 builds a chainlite
    llm_generation_chain (RankGPT-style listwise rerank) against a
    configured LLM engine; pipelines/chatbot.py drives it through the same
    LLM stack. No engine/credentials on this box, and no deterministic
    reranking sub-component stands alone.
    """
    name = "wikichat"
    REASON = ("ListwiseLLMReranker is a chainlite LLM generation chain "
              "(RankGPT); needs a configured LLM engine and API credentials "
              "not available on this box")


class Suql(_HonestUnavailable):
    """stanford-oval_suql free-text SQL executor.

    sql_free_text_support/execute_free_text_sql.py:16-32 imports pglast,
    psycopg2 and sympy, executes against a live PostgreSQL database, and
    resolves free-text predicates through suql.prompt_continuation.llm_generate
    (:31, verification model gpt-5.2 at :43). Needs both a database server
    and an LLM; neither exists on this box.
    """
    name = "suql"
    REASON = ("free-text SQL execution needs a live PostgreSQL database plus "
              "an LLM (suql.prompt_continuation.llm_generate) for the answer() "
              "free-text function; neither is available on this box")


class LocalDeepResearcher(_HonestUnavailable):
    """langchain-ai_local-deep-researcher ollama research graph.

    src/ollama_deep_researcher/graph.py:6-38 wires a langgraph StateGraph
    around ChatOllama / ChatLMStudio and web-search tools (tavily,
    perplexity, duckduckgo, searxng). Retrieval is LLM-query-writing plus
    live web search; needs a running ollama/LM Studio server and search
    APIs not available on this box.
    """
    name = "local-deep-researcher"
    REASON = ("langgraph research loop needs a running Ollama/LM Studio "
              "server (ChatOllama/ChatLMStudio) and live web-search APIs; "
              "neither is available on this box")


CANDIDATES = [RagbitsRRF, HyperMem, WikiChat, Suql, LocalDeepResearcher, LibrerFuzzy]
