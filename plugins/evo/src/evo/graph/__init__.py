"""evo.graph — the Graphify<->Evo knowledge-and-selection bridge.

Four cooperating modules turn the read-only phase-1 prototype
(``world/backend/evo_graph.py``, kept in place and still passing) into the
closed loop the roadmap's Milestone 3 asks for:

* ``schema``      — shared node/edge/failure vocabulary (pure data).
* ``store``       — read-only retrieval over the immutable library index
                    (FTS find, slice lookup, bounded 1-2-hop traversal).
* ``candidates``  — the structured graph-candidates contract with provenance.
* ``writeback``   — the separate, mutable experiment evidence graph.
* ``inject``      — read-only, opt-out brief injection of retrieved prior art.

Retrieval proposes; gates and measured evidence decide.  Nothing here can mutate
the source index; write-back lives in its own ``.evo/graph/evidence.db``.
"""
from __future__ import annotations

from . import schema
from .store import (
    GraphStore,
    GraphUnavailable,
    Hit,
    Edge,
    default_data_root,
    query_terms,
)
from .candidates import GraphCandidate, CandidateSet, build_candidates
from .writeback import EvidenceGraph, EvNode, EvEdge, sha256_bytes, sha256_file
from .inject import inject_prior_art, injection_enabled, INJECT_ENV

__all__ = [
    "schema",
    "GraphStore", "GraphUnavailable", "Hit", "Edge",
    "default_data_root", "query_terms",
    "GraphCandidate", "CandidateSet", "build_candidates",
    "EvidenceGraph", "EvNode", "EvEdge", "sha256_bytes", "sha256_file",
    "inject_prior_art", "injection_enabled", "INJECT_ENV",
]
