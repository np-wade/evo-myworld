"""Brief injection — put source-backed prior art in front of the agent.

This is the retrieval->generation half of the loop the handoffs describe: before
an experiment brief goes to an agent, retrieve candidate implementations from the
library and append them so the agent proposes from proven code with citations
rather than from scratch (GRAPHIFY-FIRST "Add a Graphify retrieval hook to
Assembly/Evo brief generation ... keep it read-only and opt-out per run").

Three properties the handoffs insist on, enforced here:

1. **Read-only.**  Injection only *reads* the library index; it never writes.
2. **Opt-out per run.**  Controlled by ``EVO_GRAPH_INJECT`` (or an explicit
   ``enabled=`` arg).  Default is OFF so the standing lab loop's latency and
   token cost don't change unless a run asks for prior art — turn it on per run.
3. **Retrieval != selection.**  The injected block is explicitly headed as
   *retrieval evidence to consider*, not approved dependencies, and reminds the
   agent that gates and measurements — not graph centrality — decide winners
   (roadmap: "Graph proximity proposes candidates; gates and measured evidence
   decide winners", and the retrieval/held-out separation rule).

The retrieval call is injected through a ``retrieve`` seam so tests exercise the
formatting and gating without a database or any tokens.
"""
from __future__ import annotations

import os
from typing import Callable, Iterable, Sequence

from .candidates import CandidateSet, build_candidates
from .store import GraphStore, GraphUnavailable, query_terms

INJECT_ENV = "EVO_GRAPH_INJECT"
DEFAULT_LIMIT = 6

# A retrieve seam: (need, queries) -> CandidateSet.  Real one hits the store;
# tests pass a stub.
Retriever = Callable[[str, Sequence[str] | None], CandidateSet]

_MARKER_BEGIN = "<!-- evo-graph:prior-art -->"
_MARKER_END = "<!-- /evo-graph:prior-art -->"

_HEADER = (
    "## Graph prior art (retrieval evidence — NOT approved dependencies)\n\n"
    "These are source-backed candidates the Graphify library index surfaced for "
    "this work. They are *proposals to consider*, not selections: verify license "
    "and boundary before vendoring, and let gates + measured results — never "
    "graph centrality or proximity — decide what actually wins. Cite any code you "
    "adapt at its `source_location`.\n"
)


def injection_enabled(enabled: bool | None = None) -> bool:
    """Resolve whether to inject: explicit arg wins, else EVO_GRAPH_INJECT.

    Truthy values: ``1``, ``true``, ``yes``, ``on`` (case-insensitive).
    Default (unset) is False — opt-in per run.
    """
    if enabled is not None:
        return enabled
    raw = os.environ.get(INJECT_ENV, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def derive_queries(brief: str, *, max_terms: int = 8) -> list[str]:
    """Derive a retrieval query from a brief using the store's own tokenizer.

    Returns a single-element list (one AND-query of the brief's content terms),
    capped so a long brief doesn't produce an over-narrow AND that matches
    nothing.  Empty if the brief has no content terms.
    """
    terms = query_terms(brief)[:max_terms]
    return [" ".join(terms)] if terms else []


def _default_retriever(
    store: GraphStore,
    *,
    repo: str | None,
    kinds: Iterable[str] | None,
    limit: int,
) -> Retriever:
    def retrieve(need: str, queries: Sequence[str] | None) -> CandidateSet:
        return build_candidates(
            store, need, queries=queries, repo=repo, kinds=kinds,
            per_query=limit, total=limit * 2,
        )
    return retrieve


def build_prior_art_block(cset: CandidateSet) -> str:
    """Render a CandidateSet as the injectable, marker-wrapped brief block."""
    if not cset.candidates:
        return ""
    body = cset.to_markdown()
    provenance = (
        f"\n\n_Retrieved {len(cset)} candidate(s) across {len(cset.repos)} repo(s)"
        + (f"; index built {cset.index_built_at}" if cset.index_built_at else "")
        + f". Queries: {cset.queries}._"
    )
    return f"{_MARKER_BEGIN}\n{_HEADER}\n{body}{provenance}\n{_MARKER_END}"


def strip_prior_art(brief: str) -> str:
    """Remove a previously-injected block so re-injection doesn't stack.

    Idempotency: injecting twice must not append two blocks.  Any text between
    the markers (inclusive) is removed.
    """
    begin = brief.find(_MARKER_BEGIN)
    if begin == -1:
        return brief
    end = brief.find(_MARKER_END, begin)
    if end == -1:
        return brief[:begin].rstrip() + "\n"
    end += len(_MARKER_END)
    return (brief[:begin].rstrip() + "\n" + brief[end:].lstrip()).rstrip() + "\n"


def inject_prior_art(
    brief: str,
    *,
    need: str | None = None,
    queries: Sequence[str] | None = None,
    store: GraphStore | None = None,
    retrieve: Retriever | None = None,
    repo: str | None = None,
    kinds: Iterable[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    enabled: bool | None = None,
) -> str:
    """Return ``brief`` with a graph prior-art block appended (or unchanged).

    Best-effort and non-fatal: if injection is disabled, the store is
    unavailable, or retrieval finds nothing, the original brief is returned
    unchanged.  ``need`` defaults to the brief itself; ``queries`` default to
    terms derived from the brief.

    Pass ``retrieve`` to bypass the store entirely (tests / custom retrieval).
    """
    if not injection_enabled(enabled):
        return brief
    need = need or (brief.strip().splitlines()[0] if brief.strip() else "")
    if not need:
        return brief
    qs = list(queries) if queries else derive_queries(brief)

    if retrieve is None:
        owns_store = store is None
        store = store or GraphStore()
        try:
            if not store.available():
                return brief
            retrieve = _default_retriever(store, repo=repo, kinds=kinds, limit=limit)
            cset = retrieve(need, qs or None)
        except GraphUnavailable:
            return brief
        finally:
            if owns_store:
                store.close()
    else:
        try:
            cset = retrieve(need, qs or None)
        except GraphUnavailable:
            return brief

    block = build_prior_art_block(cset)
    if not block:
        return brief
    base = strip_prior_art(brief).rstrip()
    return f"{base}\n\n{block}\n"
