"""Read-only retrieval over the Graphify library index (index.db + slices).

This is the retrieval backbone of the bridge.  It promotes the proven phase-1
CLI ``world/backend/evo_graph.py`` (12 tests green against the real 9.2M-node
index) into an importable, reusable ``GraphStore`` object, and *adds* the piece
that phase-1 deliberately left out: bounded multi-hop traversal over ``edges``.

The original ``world/backend/evo_graph.py`` is left in place and still works —
this module reuses its approach rather than replacing it:

* ``_query_terms`` / ``_fts_query`` are ported verbatim in behaviour from
  graphify ``serve.py`` (``_query_terms`` L128, ``_QUERY_STOPWORDS``) and
  ``tencentdb-agent-memory`` ``sqlite.ts`` ``buildFtsQuery`` (L198, per-token
  double-quoting so user punctuation can't inject FTS5 operators).
* bm25 + exact/prefix ranking bonuses mirror graphify ``serve.py``
  ``_EXACT_MATCH_BONUS`` / ``_PREFIX_MATCH_BONUS``.
* graceful-degradation policy (``GraphUnavailable`` instead of a traceback for a
  missing/unreadable DB) follows ``tencentdb-agent-memory`` ``__init__.py`` L449
  ``_try_recover_gateway`` "never raises, degrade gracefully".

New in this module — multi-hop, following ``GRAPH-FIRST.md`` "Depth 2 — 1–2-hop
joins on ``edges``" and the neighbor-query shape of ``PostHog`` ``schema.py``
``TraceNeighborsQuery`` (neighbors of a node, bounded, direction-aware).  Per the
protocol we never write 3+-hop recursive SQL here; that is FalkorDB's job.

Everything is read-only: SQLite is opened ``mode=ro``; slices are only read.
The source index is immutable during an experiment — this module cannot mutate
it even by accident.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

DEFAULT_DATA_ROOT = os.path.expanduser(
    "~/coding/docker-envs/projects/graphify-app/data"
)

# Ported from graphify serve.py _QUERY_STOPWORDS (L117-126): content words drive
# the search, not question filler.
_QUERY_STOPWORDS = frozenset({
    "how", "what", "why", "when", "where", "which", "who",
    "does", "did", "is", "are", "was", "were", "be",
    "can", "could", "should", "would", "will", "may", "might", "must",
    "has", "have", "had", "the", "and", "but", "not", "for", "from",
    "with", "into", "that", "this", "these", "those", "there",
})

# Same tier idea as graphify serve.py: exact label beats prefix beats bm25 order.
_EXACT_BONUS = 1000.0
_PREFIX_BONUS = 100.0

# Traversal safety rails — a runaway BFS over a 1405-degree hub would return the
# whole repo.  These cap fan-out per hop and total nodes returned.
DEFAULT_NEIGHBOR_LIMIT = 40
DEFAULT_SUBGRAPH_LIMIT = 120
MAX_HOPS = 2  # GRAPH-FIRST: do NOT write 3+-hop recursive SQL — that's FalkorDB.


class GraphUnavailable(RuntimeError):
    """Raised when the library index/slices are missing or unreadable.

    Callers that must degrade gracefully (the CLI, brief injection) catch this
    and fall back to no-retrieval rather than crashing a run.
    """


def default_data_root() -> str:
    return os.environ.get("GRAPHIFY_DATA", DEFAULT_DATA_ROOT)


def query_terms(query: str) -> list[str]:
    """Tokenize free text into content terms (ported from graphify serve.py).

    ``\\w+`` tokens, lowercased, drop stopwords and 1-2 char tokens; fall back to
    the unfiltered terms if everything was a stopword so we never return empty.
    """
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    content = [t for t in terms if t not in _QUERY_STOPWORDS]
    return content or terms


def fts_match(terms: Sequence[str], *, join: str = "AND") -> str:
    """Build a safe FTS5 MATCH string: each token double-quoted then joined.

    Quoting neutralizes FTS5 operators/punctuation in user input
    (tencentdb-agent-memory sqlite.ts buildFtsQuery L198).
    """
    quoted = ['"{}"'.format(t.replace('"', '""')) for t in terms]
    return f" {join} ".join(quoted)


@dataclass(frozen=True)
class Hit:
    """One node in the library index — the atom of retrieval evidence."""

    repo_id: str
    node_id: str
    label: str
    norm_label: str
    kind: str
    source_file: str
    loc: int | None
    degree: int
    centrality: float | None = None
    community_name: str | None = None
    score: float | None = None  # bm25 (lower=better) when from a find()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id, "node_id": self.node_id,
            "label": self.label, "norm_label": self.norm_label,
            "kind": self.kind, "source_file": self.source_file,
            "loc": self.loc, "degree": self.degree,
            "centrality": self.centrality, "community_name": self.community_name,
            "score": self.score,
        }

    @property
    def source_location(self) -> str:
        """``file:line`` pointer for citations (or just ``file``)."""
        if self.source_file and self.loc:
            return f"{self.source_file}:{self.loc}"
        return self.source_file or "?"


@dataclass
class Edge:
    relation: str
    neighbor: Hit
    direction: str  # "out" (src->dst) or "in" (dst->src)


def _row_to_hit(r: sqlite3.Row, *, score: float | None = None) -> Hit:
    keys = r.keys()
    return Hit(
        repo_id=r["repo_id"],
        node_id=r["node_id"] if "node_id" in keys else "",
        label=r["label"],
        norm_label=(r["norm_label"] if "norm_label" in keys else "") or "",
        kind=(r["kind"] if "kind" in keys else None) or "?",
        source_file=(r["source_file"] if "source_file" in keys else None) or "",
        loc=r["loc"] if "loc" in keys else None,
        degree=r["degree"] if "degree" in keys else 0,
        centrality=r["centrality"] if "centrality" in keys else None,
        community_name=r["community_name"] if "community_name" in keys else None,
        score=score if score is not None else (r["score"] if "score" in keys else None),
    )


class GraphStore:
    """Read-only handle on the Graphify data root.

    Construct once and reuse — the connection is opened lazily and cached.  All
    queries are parameterized and read-only; ``close()`` is idempotent and the
    object is a context manager.
    """

    def __init__(self, data_root: str | None = None) -> None:
        self.data_root = data_root or default_data_root()
        self.db_path = os.path.join(self.data_root, "index.db")
        self.graphs_dir = os.path.join(self.data_root, "graphs")
        self._con: sqlite3.Connection | None = None

    # -- lifecycle -------------------------------------------------------------

    def __enter__(self) -> "GraphStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    def available(self) -> bool:
        """True if the index.db exists and opens read-only (no exception)."""
        if not os.path.exists(self.db_path):
            return False
        try:
            self._connect()
            return True
        except GraphUnavailable:
            return False

    def _connect(self) -> sqlite3.Connection:
        if self._con is not None:
            return self._con
        if not os.path.exists(self.db_path):
            raise GraphUnavailable(
                f"index.db not found at {self.db_path} "
                "(set GRAPHIFY_DATA to the graphify data dir)"
            )
        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        except sqlite3.OperationalError as e:  # pragma: no cover - platform dep
            raise GraphUnavailable(f"cannot open index.db read-only: {e}") from e
        con.row_factory = sqlite3.Row
        self._con = con
        return con

    def build_meta(self) -> dict[str, Any]:
        """Provenance stamp for retrieval evidence: when the index was built."""
        con = self._connect()
        try:
            rows = con.execute("SELECT key, value FROM meta").fetchall()
            meta = {r["key"]: r["value"] for r in rows}
        except sqlite3.OperationalError:
            meta = {}
        meta["index_path"] = self.db_path
        return meta

    # -- Depth 0/1: full-text find --------------------------------------------

    def find(
        self,
        query: str,
        *,
        repo: str | None = None,
        limit: int = 10,
        kinds: Iterable[str] | None = None,
    ) -> list[Hit]:
        """Ranked FTS search over the index (ports evo_graph.cmd_find).

        AND-join for precision; OR-fallback for recall when AND empties out.
        Post-ranks bm25 with exact/prefix label bonuses over a 5x overfetch.
        Returns [] on no hits (a miss is not proof of absence — FTS covers the
        top ~50k nodes/repo).
        """
        con = self._connect()
        terms = query_terms(query)
        if not terms:
            return []
        limit = max(1, limit)
        fetch = limit * 5

        sql = (
            "SELECT n.repo_id, n.node_id, n.label, n.norm_label, n.kind, "
            "n.source_file, n.loc, n.degree, n.centrality, n.community_name, "
            "bm25(nodes_fts) AS score "
            "FROM nodes_fts JOIN nodes n ON n.id = nodes_fts.rowid "
            "WHERE nodes_fts MATCH ?"
        )
        params: list[Any] = [fts_match(terms, join="AND")]
        if repo:
            sql += " AND n.repo_id LIKE ?"
            params.append(f"%{repo}%")
        kind_list = [k for k in (kinds or [])]
        if kind_list:
            sql += " AND n.kind IN (%s)" % ",".join("?" * len(kind_list))
            params.extend(kind_list)
        sql += " ORDER BY score LIMIT ?"
        params.append(fetch)

        try:
            rows = con.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            raise GraphUnavailable(f"FTS query failed: {e}") from e
        if not rows and len(terms) > 1:
            params[0] = fts_match(terms, join="OR")
            rows = con.execute(sql, params).fetchall()
        if not rows:
            return []

        joined = " ".join(terms)

        def rank(r: sqlite3.Row) -> float:
            s = float(r["score"])  # bm25: lower (more negative) = better
            norm = (r["norm_label"] or "").lower()
            if norm == joined or norm == terms[0]:
                s -= _EXACT_BONUS
            elif norm.startswith(terms[0]):
                s -= _PREFIX_BONUS
            return s

        rows = sorted(rows, key=rank)[:limit]
        return [_row_to_hit(r) for r in rows]

    def get_node(self, repo_id: str, node_id: str) -> Hit | None:
        """Exact node lookup by (repo_id, node_id) — the unique key."""
        con = self._connect()
        r = con.execute(
            "SELECT repo_id, node_id, label, norm_label, kind, source_file, "
            "loc, degree, centrality, community_name FROM nodes "
            "WHERE repo_id = ? AND node_id = ? LIMIT 1",
            (repo_id, node_id),
        ).fetchone()
        return _row_to_hit(r) if r else None

    def hubs(self, repo_id: str, *, limit: int = 20) -> list[Hit]:
        """Highest-degree nodes in a repo — the 'what is this repo about' read."""
        con = self._connect()
        rows = con.execute(
            "SELECT repo_id, node_id, label, norm_label, kind, source_file, "
            "loc, degree, centrality, community_name FROM nodes "
            "WHERE repo_id = ? ORDER BY degree DESC LIMIT ?",
            (repo_id, max(1, limit)),
        ).fetchall()
        return [_row_to_hit(r) for r in rows]

    # -- Depth 2: bounded 1–2-hop traversal over edges ------------------------

    def neighbors(
        self,
        repo_id: str,
        node_id: str,
        *,
        direction: str = "both",
        relations: Iterable[str] | None = None,
        limit: int = DEFAULT_NEIGHBOR_LIMIT,
    ) -> list[Edge]:
        """Immediate neighbors of a node (1 hop).

        ``direction``: ``out`` (this node's src edges), ``in`` (dst edges), or
        ``both``.  ``relations`` optionally filters by edge relation
        (case-insensitive).  Bounded by ``limit`` to keep hub fan-out sane.

        Shape follows PostHog ``TraceNeighborsQuery`` (neighbors of a node,
        direction-aware, bounded) and GRAPH-FIRST Depth-2 SQL (join edges on the
        indexed ``(repo_id, src|dst)`` then resolve node_id back to nodes).
        """
        if direction not in ("out", "in", "both"):
            raise ValueError(f"direction must be out|in|both, got {direction!r}")
        con = self._connect()
        rel_set = {r.lower() for r in relations} if relations else None
        limit = max(1, limit)

        out_edges: list[tuple[str, str, str]] = []  # (relation, neighbor_id, dir)
        if direction in ("out", "both"):
            rows = con.execute(
                "SELECT relation, dst FROM edges WHERE repo_id = ? AND src = ? "
                "LIMIT ?",
                (repo_id, node_id, limit * 3),
            ).fetchall()
            out_edges += [(r["relation"], r["dst"], "out") for r in rows]
        if direction in ("in", "both"):
            rows = con.execute(
                "SELECT relation, src FROM edges WHERE repo_id = ? AND dst = ? "
                "LIMIT ?",
                (repo_id, node_id, limit * 3),
            ).fetchall()
            out_edges += [(r["relation"], r["src"], "in") for r in rows]

        edges: list[Edge] = []
        seen: set[tuple[str, str, str]] = set()
        for relation, neigh_id, dirn in out_edges:
            if rel_set is not None and (relation or "").lower() not in rel_set:
                continue
            key = (relation, neigh_id, dirn)
            if key in seen:
                continue
            seen.add(key)
            neigh = self.get_node(repo_id, neigh_id)
            if neigh is None:
                # dst can be an external/synthetic id not present as a node row.
                neigh = Hit(
                    repo_id=repo_id, node_id=neigh_id, label=neigh_id,
                    norm_label=neigh_id.lower(), kind="?", source_file="",
                    loc=None, degree=0,
                )
            edges.append(Edge(relation=relation or "?", neighbor=neigh, direction=dirn))
            if len(edges) >= limit:
                break
        return edges

    def callers(self, repo_id: str, node_id: str, *, limit: int = DEFAULT_NEIGHBOR_LIMIT) -> list[Edge]:
        """Who points at this node (inbound edges) — 'who calls X'."""
        return self.neighbors(repo_id, node_id, direction="in", limit=limit)

    def callees(self, repo_id: str, node_id: str, *, limit: int = DEFAULT_NEIGHBOR_LIMIT) -> list[Edge]:
        """What this node points at (outbound edges)."""
        return self.neighbors(repo_id, node_id, direction="out", limit=limit)

    def subgraph(
        self,
        repo_id: str,
        seed_node_ids: Sequence[str],
        *,
        hops: int = 1,
        direction: str = "both",
        relations: Iterable[str] | None = None,
        limit: int = DEFAULT_SUBGRAPH_LIMIT,
    ) -> dict[str, Any]:
        """Bounded BFS from seed nodes up to ``hops`` (<= 2) hops.

        Returns ``{"nodes": [Hit...], "edges": [(src, relation, dst, dir)...]}``.
        This is the 'connect a UI action to handler, API, backend, tests, prior
        failures' multi-hop read from the roadmap, kept within the SQLite-safe
        2-hop ceiling (GRAPH-FIRST).  Beyond 2 hops, push the repo to FalkorDB.
        """
        hops = max(0, min(int(hops), MAX_HOPS))
        con = self._connect()  # noqa: F841 - ensures availability before BFS
        limit = max(1, limit)

        collected: dict[str, Hit] = {}
        edge_tuples: list[tuple[str, str, str, str]] = []
        edge_seen: set[tuple[str, str, str, str]] = set()

        frontier: list[str] = []
        for nid in seed_node_ids:
            hit = self.get_node(repo_id, nid)
            if hit is not None:
                collected[nid] = hit
                frontier.append(nid)

        for _ in range(hops):
            next_frontier: list[str] = []
            for nid in frontier:
                if len(collected) >= limit:
                    break
                for edge in self.neighbors(
                    repo_id, nid, direction=direction, relations=relations,
                    limit=DEFAULT_NEIGHBOR_LIMIT,
                ):
                    neigh_id = edge.neighbor.node_id
                    et = (
                        (nid, edge.relation, neigh_id, "out")
                        if edge.direction == "out"
                        else (neigh_id, edge.relation, nid, "out")
                    )
                    if et not in edge_seen:
                        edge_seen.add(et)
                        edge_tuples.append(et)
                    if neigh_id not in collected and len(collected) < limit:
                        collected[neigh_id] = edge.neighbor
                        next_frontier.append(neigh_id)
            frontier = next_frontier
            if not frontier:
                break

        return {
            "nodes": [h.to_dict() for h in collected.values()],
            "edges": [
                {"src": s, "relation": rel, "dst": d, "direction": dr}
                for (s, rel, d, dr) in edge_tuples
            ],
        }

    # -- Slices ---------------------------------------------------------------

    def resolve_repo_dir(self, repo: str) -> str:
        """Resolve a graph-dir substring to exactly one repo dir (or raise)."""
        if not os.path.isdir(self.graphs_dir):
            raise GraphUnavailable(
                f"graphs dir not found at {self.graphs_dir} "
                "(set GRAPHIFY_DATA to the graphify data dir)"
            )
        needle = repo.lower()
        matches = sorted(
            d for d in os.listdir(self.graphs_dir)
            if needle in d.lower()
            and os.path.isdir(os.path.join(self.graphs_dir, d))
        )
        if not matches:
            raise GraphUnavailable(
                f"no graph dir matching '{repo}' under {self.graphs_dir}"
            )
        if len(matches) > 1:
            raise GraphUnavailable(
                f"{len(matches)} repos match '{repo}': {matches[:8]}"
                "{}; narrow the substring".format(" …" if len(matches) > 8 else "")
            )
        return os.path.join(self.graphs_dir, matches[0])

    def slices(self, repo: str, *, topic: str | None = None) -> list[dict[str, Any]]:
        """Locate and summarize a repo's topic slices (ports evo_graph.cmd_slice).

        Returns a summary dict per slice: ``path``, ``topic_terms``,
        ``node_count``, ``edge_count``, ``files``, ``hubs``.  ``topic`` filters
        by slice-name substring.
        """
        repo_dir = self.resolve_repo_dir(repo)
        slices_dir = None
        for cand in ("graphify-out/slices", "slices"):
            p = os.path.join(repo_dir, cand)
            if os.path.isdir(p):
                slices_dir = p
                break
        if slices_dir is None:
            raise GraphUnavailable(
                f"{os.path.basename(repo_dir)} has no slices/ yet — run "
                "data/build-run/slice_graph.py on it (GRAPH-FIRST.md)"
            )
        slice_files = sorted(glob.glob(os.path.join(slices_dir, "*.json")))
        if topic:
            t = topic.lower()
            slice_files = [p for p in slice_files if t in os.path.basename(p).lower()]

        out: list[dict[str, Any]] = []
        for path in slice_files:
            out.append(self._slice_summary(path))
        return out

    @staticmethod
    def _slice_summary(path: str) -> dict[str, Any]:
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return {"path": path, "error": str(e)}
        return {
            "path": path,
            "topic_terms": d.get("topic_terms"),
            "node_count": d.get("node_count"),
            "edge_count": d.get("edge_count"),
            "files": (d.get("files") or [])[:8],
            "hubs": [n.get("label", "?") for n in (d.get("nodes") or [])[:5]],
        }
