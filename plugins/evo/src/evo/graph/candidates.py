"""The graph-candidates contract.

Both handoffs (GRAPHIFY-FIRST-HANDOFF "Immediate next steps" #1 and
DEVELOPMENT-ROADMAP Milestone 3) call for a *structured* candidate record — not
a blob of search output — carrying: need, query, repo, slice, symbol, source
pointer, license, boundary, expected benefit, and test.  That record is the unit
that flows two ways:

  retrieval  ->  GraphCandidate  ->  brief injection (evo.graph.inject)
                                 ->  write-back CITES/RETRIEVED_FROM edges

Keeping it a typed dataclass with JSON round-trip means a candidate found in one
cycle can be persisted, cited in an experiment node, and re-loaded in the next
cycle — the "next retrieval uses what was learned" loop.

License and boundary are recorded as *claims to verify*, not asserted facts: the
library index has no per-repo license column, and vendoring requires a manual
license/boundary check (both handoffs: "Licensing, boundary size, runtime cost,
and tests must be checked before code is copied or adapted").  So the default
license is ``"unverified"`` and the contract makes the unchecked state explicit
rather than silently implying MIT.

Pure-Python and dependency-free; imports only ``evo.graph.store`` for the Hit
type and the retrieval used by the builder.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from .store import GraphStore, Hit, GraphUnavailable, query_terms

LICENSE_UNVERIFIED = "unverified"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class GraphCandidate:
    """One source-backed option for a stated need, with provenance to verify.

    Every field a reviewer needs to decide 'should we race/vendor this?' without
    re-running the search: what we were looking for, where it is, how central it
    is, what still has to be checked (license/boundary), and how to test it.
    """

    need: str                          # the capability/need this answers
    query: str                         # the retrieval query that surfaced it
    repo_id: str                       # library repo_id (copy/paste round-trips)
    label: str                         # symbol label, e.g. "buildFtsQuery()"
    node_id: str = ""                  # library node_id (for later traversal)
    kind: str = "?"                    # function/class/file/...
    source_file: str = ""
    source_location: str = ""          # "file:line" citation pointer
    degree: int = 0
    centrality: float | None = None
    slice_path: str | None = None      # owning topic slice, if known
    slice_terms: list[str] = field(default_factory=list)
    license: str = LICENSE_UNVERIFIED  # claim-to-verify, not asserted fact
    boundary: str = ""                 # coupling/boundary note (to verify)
    expected_benefit: str = ""         # why this might help the need
    suggested_test: str = ""           # how a race would exercise it
    retrieved_at: str = field(default_factory=_utc_now)
    index_built_at: str | None = None  # provenance stamp of the source index
    rank: int = 0                      # position within its CandidateSet

    # -- construction from retrieval ------------------------------------------

    @classmethod
    def from_hit(
        cls,
        hit: Hit,
        *,
        need: str,
        query: str,
        expected_benefit: str = "",
        suggested_test: str = "",
        index_built_at: str | None = None,
    ) -> "GraphCandidate":
        return cls(
            need=need,
            query=query,
            repo_id=hit.repo_id,
            label=hit.label,
            node_id=hit.node_id,
            kind=hit.kind,
            source_file=hit.source_file,
            source_location=hit.source_location,
            degree=hit.degree,
            centrality=hit.centrality,
            expected_benefit=expected_benefit,
            suggested_test=suggested_test,
            index_built_at=index_built_at,
        )

    # -- serialization ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GraphCandidate":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def citation(self) -> str:
        """A one-line, copy-pasteable source citation for SOURCES.md / briefs."""
        loc = self.source_location or self.source_file or "?"
        return f"{self.repo_id} :: {self.label} [{self.kind}] @ {loc}"

    def to_markdown(self) -> str:
        lines = [
            f"- **{self.label}** [{self.kind}] — `{self.repo_id}`",
            f"  - source: `{self.source_location or self.source_file or '?'}`"
            f"  (degree={self.degree})",
        ]
        if self.slice_terms:
            lines.append(f"  - slice: {self.slice_terms} (`{self.slice_path}`)")
        if self.expected_benefit:
            lines.append(f"  - why: {self.expected_benefit}")
        if self.suggested_test:
            lines.append(f"  - test: {self.suggested_test}")
        lines.append(
            f"  - license: **{self.license}** (verify before vendoring)"
            + (f"; boundary: {self.boundary}" if self.boundary else "")
        )
        return "\n".join(lines)


@dataclass
class CandidateSet:
    """A ranked, deduplicated set of candidates for one need.

    This is what a retrieval call returns and what brief injection formats.  Two
    invariants matter for the loop: (1) candidates are *distinct source symbols*
    (dedup by repo_id+node_id/label) so a race isn't run against two names for
    the same code, and (2) the set carries enough repos that selection isn't
    pinned to one library (the handoffs' "Graphify should identify multiple
    proven code paths").
    """

    need: str
    queries: list[str] = field(default_factory=list)
    candidates: list[GraphCandidate] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    index_built_at: str | None = None
    note: str = ""

    def __len__(self) -> int:
        return len(self.candidates)

    def __iter__(self):
        return iter(self.candidates)

    @property
    def repos(self) -> list[str]:
        seen: dict[str, None] = {}
        for c in self.candidates:
            seen[c.repo_id] = None
        return list(seen)

    def add(self, candidate: GraphCandidate) -> bool:
        """Add if it's a distinct source symbol; returns True if added."""
        key = (candidate.repo_id, candidate.node_id or candidate.label)
        for existing in self.candidates:
            if (existing.repo_id, existing.node_id or existing.label) == key:
                return False
        self.candidates.append(candidate)
        return True

    def rerank(self, *, prefer_repo_diversity: bool = True) -> "CandidateSet":
        """Order by degree (proxy for centrality) but interleave repos.

        Pure graph centrality is a *retrieval* signal only — never a selection
        signal (roadmap: "Never select code only because it is graph-central").
        So we sort by degree for a sensible reading order, then, if asked,
        round-robin across repos so the top of the list isn't one repo's hubs
        crowding out a second proven path.
        """
        ordered = sorted(
            self.candidates, key=lambda c: (c.degree or 0), reverse=True
        )
        if prefer_repo_diversity and len({c.repo_id for c in ordered}) > 1:
            buckets: dict[str, list[GraphCandidate]] = {}
            for c in ordered:
                buckets.setdefault(c.repo_id, []).append(c)
            interleaved: list[GraphCandidate] = []
            while any(buckets.values()):
                for repo in list(buckets):
                    if buckets[repo]:
                        interleaved.append(buckets[repo].pop(0))
                    if not buckets[repo]:
                        del buckets[repo]
            ordered = interleaved
        for i, c in enumerate(ordered):
            c.rank = i
        self.candidates = ordered
        return self

    # -- serialization ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "need": self.need,
            "queries": self.queries,
            "created_at": self.created_at,
            "index_built_at": self.index_built_at,
            "note": self.note,
            "candidates": [c.to_dict() for c in self.candidates],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CandidateSet":
        cs = cls(
            need=d.get("need", ""),
            queries=list(d.get("queries", [])),
            created_at=d.get("created_at", _utc_now()),
            index_built_at=d.get("index_built_at"),
            note=d.get("note", ""),
        )
        cs.candidates = [GraphCandidate.from_dict(c) for c in d.get("candidates", [])]
        return cs

    @classmethod
    def from_json(cls, text: str) -> "CandidateSet":
        return cls.from_dict(json.loads(text))

    def to_markdown(self) -> str:
        if not self.candidates:
            return f"_No graph candidates found for: {self.need}_"
        head = f"### Candidates for: {self.need}"
        if len(self.repos) > 1:
            head += f"  ({len(self.candidates)} across {len(self.repos)} repos)"
        body = "\n".join(c.to_markdown() for c in self.candidates)
        return f"{head}\n\n{body}"


# ── Builder: retrieval -> CandidateSet ───────────────────────────────────────

def build_candidates(
    store: GraphStore,
    need: str,
    *,
    queries: Sequence[str] | None = None,
    repo: str | None = None,
    kinds: Iterable[str] | None = None,
    per_query: int = 6,
    total: int = 12,
    prefer_repo_diversity: bool = True,
) -> CandidateSet:
    """Run one or more queries and assemble a ranked, deduped CandidateSet.

    ``queries`` defaults to a single query derived from ``need`` via the same
    tokenizer the store uses.  Retrieval is best-effort: a store that is
    unavailable yields an empty set with an explanatory ``note`` rather than
    raising, so callers (brief injection) can degrade to no-retrieval.
    """
    qs = list(queries) if queries else [" ".join(query_terms(need)) or need]
    cs = CandidateSet(need=need, queries=qs)
    try:
        meta = store.build_meta()
        cs.index_built_at = meta.get("built_at")
    except GraphUnavailable as e:
        cs.note = f"graph unavailable: {e}"
        return cs

    for q in qs:
        try:
            hits = store.find(q, repo=repo, limit=per_query, kinds=kinds)
        except GraphUnavailable as e:
            cs.note = f"retrieval error on {q!r}: {e}"
            continue
        for h in hits:
            cand = GraphCandidate.from_hit(
                h, need=need, query=q, index_built_at=cs.index_built_at,
            )
            cs.add(cand)
            if len(cs) >= total:
                break
        if len(cs) >= total:
            break

    cs.rerank(prefer_repo_diversity=prefer_repo_diversity)
    if not cs.candidates and not cs.note:
        cs.note = "no hits (FTS covers top ~50k nodes/repo; a miss is not absence)"
    return cs
