"""Experiment evidence graph — the write-back half of the bridge.

Retrieval (``store.py``) reads the immutable 9.2M-node library index.  This
module writes the *other* graph: the empirical record of what Evo tried, in what
environment, against what gates, what it beat, and why it was promoted or
discarded.  Both handoffs list this as the central missing piece
(GRAPHIFY-FIRST "Write experiment nodes ... back to an experiment graph with
artifact hashes"; roadmap Milestone 3 "result write-back with provenance").

Hard boundary: this database is **separate** from ``index.db`` and lives under
the workspace at ``.evo/graph/evidence.db``.  The source index is immutable
during an experiment; nothing here can touch it.

Prior art (graph-first pull, FTS over the library index — see session notes):

* **openwhisk ``ArtifactStore``** (CosmosDB/MongoDB/Memory implementations) —
  the pluggable-store shape: a small trait (``upsert``/``get``/``put`` an
  attachment) with swappable backends.  We keep one concrete SQLite backend but
  mirror the interface so a FalkorDB/remote backend could slot in later.
* **HKUDS/Vibe-Trading ``SqliteStrategyStore``** — a SQLite-backed domain store
  with a JSON ``attrs`` column and content-addressed rows; the table shape here
  (id + kind + attrs_json + timestamps) follows it.
* **apache/airflow ``OpenLineageAdapter`` / ``OperatorLineage``** — the run/job
  lineage model: an experiment is a run, ``DERIVED_FROM`` is the lineage edge,
  and inputs/outputs (artifacts, environments) attach as explicit edges rather
  than being inferred.
* **FalkorDB MERGE** upsert semantics (GRAPH-FIRST Depth-3) — re-recording the
  same experiment is idempotent: nodes/edges MERGE-upsert, never duplicate.
* **content addressing** reuses ``evo.artifacts`` SHA-256 conventions so an
  artifact hash written here matches what the artifact shuttle produced.

Everything is stdlib (sqlite3 + json + hashlib).  WAL mode + a busy timeout make
concurrent recursive agents safe; writes are single-statement upserts.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from . import schema
from .candidates import CandidateSet, GraphCandidate

SCHEMA_VERSION = schema.SCHEMA_VERSION
DEFAULT_BUSY_TIMEOUT_MS = 5000


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_default(o: Any) -> Any:
    return str(o)


def _dumps(d: Any) -> str:
    return json.dumps(d, sort_keys=True, default=_json_default)


@dataclass(frozen=True)
class EvNode:
    uid: str
    kind: str
    label: str
    attrs: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid, "kind": self.kind, "label": self.label,
            "attrs": self.attrs, "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class EvEdge:
    src: str
    dst: str
    relation: str
    attrs: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "src": self.src, "dst": self.dst, "relation": self.relation,
            "attrs": self.attrs, "created_at": self.created_at,
        }


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ev_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS ev_nodes (
    uid        TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    label      TEXT NOT NULL,
    attrs_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ev_nodes_kind ON ev_nodes(kind);
CREATE TABLE IF NOT EXISTS ev_edges (
    src        TEXT NOT NULL,
    dst        TEXT NOT NULL,
    relation   TEXT NOT NULL,
    attrs_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY (src, relation, dst)
);
CREATE INDEX IF NOT EXISTS ev_edges_src ON ev_edges(src, relation);
CREATE INDEX IF NOT EXISTS ev_edges_dst ON ev_edges(dst, relation);
CREATE TABLE IF NOT EXISTS ev_artifacts (
    sha256     TEXT PRIMARY KEY,
    size       INTEGER NOT NULL DEFAULT 0,
    kind       TEXT NOT NULL DEFAULT 'blob',
    ref        TEXT,
    created_at TEXT NOT NULL
);
"""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> tuple[str, int]:
    """Content hash + byte size of a file (matches evo.artifacts hashing)."""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


class EvidenceGraph:
    """SQLite-backed experiment evidence graph.

    Open on a path, ``ensure_schema()`` once, then upsert nodes/edges.  All
    writes are idempotent MERGE-upserts keyed on the natural id, so a recursive
    agent that records the same experiment twice converges instead of
    duplicating.  Use as a context manager or ``close()`` explicitly.
    """

    def __init__(self, db_path: str | os.PathLike[str], *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> None:
        self.db_path = str(db_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._con: sqlite3.Connection | None = None

    # -- lifecycle -------------------------------------------------------------

    @classmethod
    def open_for_workspace(cls, root: str | os.PathLike[str]) -> "EvidenceGraph":
        """Open (creating dirs) at ``<root>/.evo/graph/evidence.db``."""
        gdir = Path(root) / ".evo" / "graph"
        gdir.mkdir(parents=True, exist_ok=True)
        eg = cls(gdir / "evidence.db")
        eg.ensure_schema()
        return eg

    def __enter__(self) -> "EvidenceGraph":
        self.ensure_schema()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _connect(self) -> sqlite3.Connection:
        if self._con is not None:
            return self._con
        parent = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(parent, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=self._busy_timeout_ms / 1000)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        con.execute("PRAGMA foreign_keys=ON")
        self._con = con
        return con

    def ensure_schema(self) -> None:
        con = self._connect()
        con.executescript(_SCHEMA_SQL)
        con.execute(
            "INSERT INTO ev_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SCHEMA_VERSION,),
        )
        con.execute(
            "INSERT INTO ev_meta(key, value) VALUES('created_at', ?) "
            "ON CONFLICT(key) DO NOTHING",
            (_utc_now(),),
        )
        con.commit()

    def close(self) -> None:
        if self._con is not None:
            self._con.commit()
            self._con.close()
            self._con = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise

    # -- primitive upserts (MERGE semantics) ----------------------------------

    def upsert_node(self, uid: str, kind: str, label: str, **attrs: Any) -> EvNode:
        """MERGE a node: insert or shallow-merge attrs, bump updated_at.

        Idempotent — recording the same uid twice merges attrs rather than
        duplicating (FalkorDB MERGE semantics).
        """
        schema.require_node_kind(kind)
        con = self._connect()
        now = _utc_now()
        existing = con.execute(
            "SELECT attrs_json, created_at FROM ev_nodes WHERE uid=?", (uid,)
        ).fetchone()
        if existing is not None:
            merged = json.loads(existing["attrs_json"] or "{}")
            merged.update({k: v for k, v in attrs.items() if v is not None})
            con.execute(
                "UPDATE ev_nodes SET kind=?, label=?, attrs_json=?, updated_at=? "
                "WHERE uid=?",
                (kind, label, _dumps(merged), now, uid),
            )
            created = existing["created_at"]
        else:
            merged = {k: v for k, v in attrs.items() if v is not None}
            con.execute(
                "INSERT INTO ev_nodes(uid, kind, label, attrs_json, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (uid, kind, label, _dumps(merged), now, now),
            )
            created = now
        con.commit()
        return EvNode(uid, kind, label, merged, created, now)

    def add_edge(self, src: str, dst: str, relation: str, **attrs: Any) -> EvEdge:
        """MERGE an edge (src, relation, dst).  Relation is validated/normalized."""
        rel = schema.normalize_relation(relation)
        con = self._connect()
        now = _utc_now()
        clean = {k: v for k, v in attrs.items() if v is not None}
        con.execute(
            "INSERT INTO ev_edges(src, dst, relation, attrs_json, created_at) "
            "VALUES(?,?,?,?,?) "
            "ON CONFLICT(src, relation, dst) DO UPDATE SET attrs_json=excluded.attrs_json",
            (src, dst, rel, _dumps(clean), now),
        )
        con.commit()
        return EvEdge(src, dst, rel, clean, now)

    def register_artifact(self, sha256: str, *, size: int = 0, kind: str = "blob", ref: str | None = None) -> str:
        """Record a content-addressed artifact; returns its ``artifact:<sha>`` uid.

        Also creates an ``artifact`` node so lineage queries can reach it.  The
        sha256 is the identity — re-registering the same content is a no-op.
        """
        con = self._connect()
        now = _utc_now()
        con.execute(
            "INSERT INTO ev_artifacts(sha256, size, kind, ref, created_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(sha256) DO UPDATE SET "
            "size=excluded.size, ref=COALESCE(excluded.ref, ev_artifacts.ref)",
            (sha256, size, kind, ref, now),
        )
        con.commit()
        uid = f"artifact:{sha256}"
        self.upsert_node(uid, schema.ARTIFACT, sha256[:12], sha256=sha256, size=size, artifact_kind=kind, ref=ref)
        return uid

    def register_artifact_file(self, path: str | os.PathLike[str], *, kind: str = "blob", ref: str | None = None) -> str:
        sha, size = sha256_file(path)
        return self.register_artifact(sha, size=size, kind=kind, ref=ref or str(path))

    # -- high-level: record an experiment and its evidence --------------------

    @staticmethod
    def experiment_uid(exp_id: str) -> str:
        return f"exp:{exp_id}"

    def record_experiment(
        self,
        node: dict[str, Any],
        *,
        run_id: str | None = None,
        agent: str | None = None,
        model: str | None = None,
        environment: str | None = None,
        harness: str | None = None,
        extra_attrs: dict[str, Any] | None = None,
    ) -> str:
        """Write an Evo experiment tree node as an experiment node + its edges.

        ``node`` is an Evo graph node dict (``id``, ``parent``, ``hypothesis``,
        ``status``, ``score``, ``commit``, ``gates``, optional ``judge``).  This
        creates:

          (experiment)-[DERIVED_FROM]->(parent experiment)
          (agent)-[PROPOSED]->(experiment)         if agent given
          (experiment)-[RAN_IN]->(environment)     if environment given
          (experiment)-[MEASURED]->(score)         if score present
          (experiment)-[GATED_BY]->(gate)          per gate
          (experiment)-[JUDGED_BY]->(score)        if node.judge present

        Idempotent: re-recording updates attrs and re-MERGEs edges.
        Returns the experiment uid.
        """
        exp_id = str(node.get("id") or node.get("exp_id") or "")
        if not exp_id:
            raise ValueError("node has no id/exp_id")
        uid = self.experiment_uid(exp_id)
        attrs = {
            "exp_id": exp_id,
            "run_id": run_id,
            "status": node.get("status"),
            "hypothesis": node.get("hypothesis"),
            "score": node.get("score"),
            "commit": node.get("commit"),
            "branch": node.get("branch"),
            "eval_epoch": node.get("eval_epoch"),
            "pruned_reason": node.get("pruned_reason"),
            "created_at": node.get("created_at"),
            "updated_at": node.get("updated_at"),
        }
        if extra_attrs:
            attrs.update(extra_attrs)
        self.upsert_node(uid, schema.EXPERIMENT, node.get("hypothesis") or exp_id, **attrs)

        parent = node.get("parent")
        if parent and parent != "root":
            self.upsert_node(self.experiment_uid(str(parent)), schema.EXPERIMENT, str(parent))
            self.add_edge(uid, self.experiment_uid(str(parent)), schema.DERIVED_FROM)

        if agent:
            auid = f"agent:{agent}"
            self.upsert_node(auid, schema.AGENT, agent, model=model)
            self.add_edge(auid, uid, schema.PROPOSED)
        if model:
            muid = f"model:{model}"
            self.upsert_node(muid, schema.MODEL, model)
            self.add_edge(uid, muid, schema.RAN_IN, role="model")
        if environment:
            euid = f"env:{environment}"
            self.upsert_node(euid, schema.ENVIRONMENT, environment)
            self.add_edge(uid, euid, schema.RAN_IN)
        if harness:
            huid = f"harness:{harness}"
            self.upsert_node(huid, schema.HARNESS, harness)
            self.add_edge(uid, huid, schema.EXERCISED_BY)

        score = node.get("score")
        if score is not None:
            suid = f"score:{exp_id}"
            self.upsert_node(suid, schema.SCORE, str(score), value=score, metric="scalar")
            self.add_edge(uid, suid, schema.MEASURED)

        for i, gate in enumerate(node.get("gates") or []):
            self._record_gate(uid, exp_id, i, gate)

        judge = node.get("judge")
        if isinstance(judge, dict) and judge.get("value") is not None:
            juid = f"judge:{exp_id}"
            self.upsert_node(
                juid, schema.SCORE, str(judge.get("value")),
                value=judge.get("value"), metric="judge",
                preset=judge.get("preset"), reason=judge.get("reason"),
            )
            self.add_edge(uid, juid, schema.JUDGED_BY)

        return uid

    def _record_gate(self, exp_uid: str, exp_id: str, i: int, gate: Any) -> None:
        if isinstance(gate, dict):
            name = str(gate.get("name") or gate.get("id") or f"gate_{i}")
            passed = gate.get("passed", gate.get("ok"))
        else:
            name = str(gate)
            passed = None
        guid = f"gate:{exp_id}:{name}"
        self.upsert_node(guid, schema.GATE, name, passed=passed, index=i)
        self.add_edge(exp_uid, guid, schema.GATED_BY, passed=passed)

    def record_failure(
        self,
        exp_id: str,
        *,
        failure_class: str,
        summary: str,
        task: str | None = None,
        detail: str | None = None,
        artifact_sha: str | None = None,
    ) -> str:
        """Record a classified failure for an experiment (optionally per-task).

        The class is validated against the failure taxonomy so a typo can't
        create an un-queryable failure bucket.  Returns the failure uid.
        """
        schema.require_failure_class(failure_class)
        exp_uid = self.experiment_uid(exp_id)
        key = f"{exp_id}:{task}" if task else exp_id
        fuid = f"failure:{key}:{failure_class}"
        self.upsert_node(
            fuid, schema.FAILURE, failure_class,
            failure_class=failure_class, summary=summary, task=task,
            detail=detail,
            non_merit=failure_class in schema.NON_MERIT_FAILURES,
        )
        self.add_edge(exp_uid, fuid, schema.FAILED_AT)
        if task:
            tuid = f"task:{task}"
            self.upsert_node(tuid, schema.TASK, task)
            self.add_edge(tuid, fuid, schema.FAILED_AT)
        if artifact_sha:
            auid = self.register_artifact(artifact_sha, kind="failure_trace")
            self.add_edge(fuid, auid, schema.PRODUCED_BY)
        return fuid

    def record_artifact_for(self, exp_id: str, sha256: str, *, size: int = 0, kind: str = "blob", ref: str | None = None) -> str:
        """Attach a content-addressed artifact to an experiment (PRODUCED_BY)."""
        auid = self.register_artifact(sha256, size=size, kind=kind, ref=ref)
        self.add_edge(self.experiment_uid(exp_id), auid, schema.PRODUCED_BY)
        return auid

    def record_comparison(
        self,
        winner_exp: str,
        loser_exp: str,
        *,
        gated: bool,
        margin: float | None = None,
        metric: str | None = None,
        basis: str | None = None,
    ) -> None:
        """Record that ``winner`` beat ``loser`` — only a *gated* win is a BEAT.

        The roadmap's rule "correctness gates first, then performance": a raw
        score delta is recorded as COMPARED_WITH; only a comparison that passed
        its gates earns the directed BEAT edge the selector trusts.
        """
        w = self.experiment_uid(winner_exp)
        l = self.experiment_uid(loser_exp)
        self.upsert_node(w, schema.EXPERIMENT, winner_exp)
        self.upsert_node(l, schema.EXPERIMENT, loser_exp)
        self.add_edge(w, l, schema.COMPARED_WITH, margin=margin, metric=metric, basis=basis)
        if gated:
            self.add_edge(w, l, schema.BEAT, margin=margin, metric=metric, basis=basis)

    def record_regression(self, exp_id: str, baseline_exp: str, *, metric: str | None = None, delta: float | None = None) -> None:
        self.add_edge(
            self.experiment_uid(exp_id), self.experiment_uid(baseline_exp),
            schema.REGRESSED, metric=metric, delta=delta,
        )

    def record_decision(
        self,
        exp_id: str,
        *,
        kind: str,
        rationale: str = "",
        by: str | None = None,
    ) -> str:
        """Record a win/lose/promote/discard decision node pointing at the experiment."""
        duid = f"decision:{exp_id}:{kind}"
        self.upsert_node(duid, schema.DECISION, kind, decision=kind, rationale=rationale, by=by)
        rel = schema.PROMOTED if kind in ("promote", "promoted", "win") else schema.DECIDED
        self.add_edge(duid, self.experiment_uid(exp_id), rel, kind=kind)
        return duid

    # -- link retrieval evidence to an experiment -----------------------------

    def record_candidates(self, exp_id: str, cset: CandidateSet) -> list[str]:
        """Persist a CandidateSet as source_symbol nodes cited by the experiment.

        Creates a ``source_symbol`` node per candidate (pointing at immutable
        library source) and a ``(experiment)-[CITES]->(source_symbol)`` +
        ``[RETRIEVED_FROM]`` edge carrying the query that surfaced it.  This is
        the retrieval->write-back link that closes the loop.
        """
        exp_uid = self.experiment_uid(exp_id)
        self.upsert_node(exp_uid, schema.EXPERIMENT, exp_id)
        uids: list[str] = []
        for c in cset.candidates:
            uid = f"src:{c.repo_id}:{c.node_id or c.label}"
            self.upsert_node(
                uid, schema.SOURCE_SYMBOL, c.label,
                repo_id=c.repo_id, node_id=c.node_id, symbol_kind=c.kind,
                source_file=c.source_file, source_location=c.source_location,
                degree=c.degree, license=c.license,
                index_built_at=c.index_built_at,
            )
            self.add_edge(exp_uid, uid, schema.CITES, need=cset.need)
            self.add_edge(exp_uid, uid, schema.RETRIEVED_FROM, query=c.query)
            uids.append(uid)
        return uids

    # -- queries: read the evidence back --------------------------------------

    def get_node(self, uid: str) -> EvNode | None:
        con = self._connect()
        r = con.execute(
            "SELECT uid, kind, label, attrs_json, created_at, updated_at "
            "FROM ev_nodes WHERE uid=?", (uid,)
        ).fetchone()
        if r is None:
            return None
        return EvNode(r["uid"], r["kind"], r["label"], json.loads(r["attrs_json"] or "{}"), r["created_at"], r["updated_at"])

    def nodes_by_kind(self, kind: str) -> list[EvNode]:
        con = self._connect()
        rows = con.execute(
            "SELECT uid, kind, label, attrs_json, created_at, updated_at "
            "FROM ev_nodes WHERE kind=? ORDER BY created_at", (kind,)
        ).fetchall()
        return [EvNode(r["uid"], r["kind"], r["label"], json.loads(r["attrs_json"] or "{}"), r["created_at"], r["updated_at"]) for r in rows]

    def edges_from(self, uid: str, *, relation: str | None = None) -> list[EvEdge]:
        con = self._connect()
        if relation:
            rows = con.execute(
                "SELECT src, dst, relation, attrs_json, created_at FROM ev_edges "
                "WHERE src=? AND relation=?", (uid, schema.normalize_relation(relation))
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT src, dst, relation, attrs_json, created_at FROM ev_edges WHERE src=?", (uid,)
            ).fetchall()
        return [EvEdge(r["src"], r["dst"], r["relation"], json.loads(r["attrs_json"] or "{}"), r["created_at"]) for r in rows]

    def edges_into(self, uid: str, *, relation: str | None = None) -> list[EvEdge]:
        con = self._connect()
        if relation:
            rows = con.execute(
                "SELECT src, dst, relation, attrs_json, created_at FROM ev_edges "
                "WHERE dst=? AND relation=?", (uid, schema.normalize_relation(relation))
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT src, dst, relation, attrs_json, created_at FROM ev_edges WHERE dst=?", (uid,)
            ).fetchall()
        return [EvEdge(r["src"], r["dst"], r["relation"], json.loads(r["attrs_json"] or "{}"), r["created_at"]) for r in rows]

    def lineage(self, exp_id: str, *, max_depth: int = 64) -> list[str]:
        """Walk DERIVED_FROM from an experiment back to its root ancestor.

        Returns exp_ids oldest-last (the node itself first).  Cycle-guarded and
        depth-capped — the experiment tree is a DAG but a corrupt write could
        loop, and this query must never hang a report.
        """
        chain: list[str] = []
        seen: set[str] = set()
        cur = self.experiment_uid(exp_id)
        for _ in range(max_depth):
            if cur in seen:
                break
            seen.add(cur)
            node = self.get_node(cur)
            if node is None:
                break
            chain.append(node.attrs.get("exp_id", node.label))
            parents = self.edges_from(cur, relation=schema.DERIVED_FROM)
            if not parents:
                break
            cur = parents[0].dst
        return chain

    def beat_chain(self, exp_id: str) -> list[str]:
        """Experiments this one directly beat (BEAT edges out)."""
        uid = self.experiment_uid(exp_id)
        return [e.dst.split(":", 1)[1] for e in self.edges_from(uid, relation=schema.BEAT)]

    def failures_for(self, exp_id: str) -> list[EvNode]:
        uid = self.experiment_uid(exp_id)
        out = []
        for e in self.edges_from(uid, relation=schema.FAILED_AT):
            n = self.get_node(e.dst)
            if n is not None:
                out.append(n)
        return out

    def citations_for(self, exp_id: str) -> list[EvNode]:
        uid = self.experiment_uid(exp_id)
        out = []
        for e in self.edges_from(uid, relation=schema.CITES):
            n = self.get_node(e.dst)
            if n is not None:
                out.append(n)
        return out

    def stats(self) -> dict[str, Any]:
        con = self._connect()
        by_kind = {
            r["kind"]: r["c"]
            for r in con.execute("SELECT kind, count(*) c FROM ev_nodes GROUP BY kind")
        }
        by_rel = {
            r["relation"]: r["c"]
            for r in con.execute("SELECT relation, count(*) c FROM ev_edges GROUP BY relation")
        }
        n_art = con.execute("SELECT count(*) c FROM ev_artifacts").fetchone()["c"]
        return {
            "schema_version": SCHEMA_VERSION,
            "nodes": sum(by_kind.values()),
            "edges": sum(by_rel.values()),
            "artifacts": n_art,
            "nodes_by_kind": by_kind,
            "edges_by_relation": by_rel,
            "db_path": self.db_path,
        }

    def export_graph(self) -> dict[str, Any]:
        """Full node/edge dump — for the dashboard feed or a FalkorDB push."""
        con = self._connect()
        nodes = [
            {
                "uid": r["uid"], "kind": r["kind"], "label": r["label"],
                "attrs": json.loads(r["attrs_json"] or "{}"),
            }
            for r in con.execute("SELECT uid, kind, label, attrs_json FROM ev_nodes")
        ]
        edges = [
            {
                "src": r["src"], "dst": r["dst"], "relation": r["relation"],
                "attrs": json.loads(r["attrs_json"] or "{}"),
            }
            for r in con.execute("SELECT src, dst, relation, attrs_json FROM ev_edges")
        ]
        return {"schema_version": SCHEMA_VERSION, "nodes": nodes, "edges": edges}
