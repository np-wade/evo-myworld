"""Durable mission DAG for recursive, evidence-driven agent work.

Missions are deliberately an overlay in Evo's existing ``graph.json`` rather
than a second scheduler or an alternate experiment lineage.  A mission answers
*what should happen and why*; an experiment answers *which Git branch ran it*.
All mutations hold the graph advisory lock, so independent agents can safely
claim ready work without racing each other.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .core import advisory_lock, atomic_write_json, default_graph, graph_path, load_json, utc_now

MISSION_KINDS = frozenset({"research", "build", "verify", "integrate"})
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_CHILDREN = 8


def _empty_store() -> dict[str, Any]:
    return {"next_id": 0, "nodes": {}}


def _store(graph: dict[str, Any]) -> dict[str, Any]:
    store = graph.setdefault("missions", _empty_store())
    store.setdefault("next_id", 0)
    store.setdefault("nodes", {})
    return store


def _mission(store: dict[str, Any], mission_id: str) -> dict[str, Any]:
    try:
        return store["nodes"][mission_id]
    except KeyError as exc:
        raise RuntimeError(f"unknown mission: {mission_id}") from exc


def _depth(store: dict[str, Any], parent_id: str | None) -> int:
    depth = 0
    seen: set[str] = set()
    while parent_id:
        if parent_id in seen:
            raise RuntimeError("mission parent cycle detected")
        seen.add(parent_id)
        parent = _mission(store, parent_id)
        depth += 1
        parent_id = parent.get("parent_id")
    return depth


def _refresh_ready(store: dict[str, Any]) -> None:
    nodes = store["nodes"]
    for mission in nodes.values():
        status = mission.get("status")
        # ``blocked`` is a recoverable, non-terminal state: a mission parks here
        # when a dependency has not (yet) succeeded, so it must be re-derived
        # alongside planned/ready.  Once every dependency succeeds it returns to
        # ``ready`` and becomes claimable again; a permanently failed dependency
        # keeps it blocked forever, which is the correct dead-end.
        if status not in {"planned", "ready", "blocked"}:
            continue
        dependencies = [_mission(store, dep) for dep in mission.get("depends_on", [])]
        if any(dep.get("status") in {"failed", "cancelled"} for dep in dependencies):
            mission["status"] = "blocked"
            mission["blocked_reason"] = "dependency did not succeed"
        elif all(dep.get("status") == "succeeded" for dep in dependencies):
            mission["status"] = "ready"
            mission.pop("blocked_reason", None)
        elif status == "blocked":
            # Still-pending (not failed) dependencies: an explicitly blocked
            # mission stays blocked until they all succeed rather than silently
            # dropping back to ``planned``.
            pass
        else:
            mission["status"] = "planned"


def _write(root: Path, graph: dict[str, Any]) -> None:
    atomic_write_json(graph_path(root), graph)


def create_mission(
    root: Path,
    *,
    title: str,
    kind: str,
    brief: str,
    parent_id: str | None = None,
    depends_on: list[str] | None = None,
    acceptance: list[str] | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_children: int = DEFAULT_MAX_CHILDREN,
) -> dict[str, Any]:
    title = " ".join(str(title).split())
    brief = str(brief).strip()
    if not title:
        raise RuntimeError("mission title is required")
    if not brief:
        raise RuntimeError("mission brief is required")
    if kind not in MISSION_KINDS:
        raise RuntimeError(f"mission kind must be one of: {', '.join(sorted(MISSION_KINDS))}")
    if max_depth < 0 or max_children < 1:
        raise RuntimeError("max_depth must be >= 0 and max_children must be >= 1")
    depends_on = list(dict.fromkeys(depends_on or []))
    acceptance = [str(item).strip() for item in (acceptance or []) if str(item).strip()]

    gpath = graph_path(root)
    with advisory_lock(gpath.with_suffix(gpath.suffix + ".lock")):
        graph = load_json(gpath, default_graph())
        store = _store(graph)
        if parent_id:
            parent = _mission(store, parent_id)
            if _depth(store, parent_id) + 1 > max_depth:
                raise RuntimeError(f"mission depth exceeds max_depth={max_depth}")
            children = [m for m in store["nodes"].values() if m.get("parent_id") == parent_id]
            inherited_child_cap = int((parent.get("budget") or {}).get("max_children", max_children))
            if len(children) >= inherited_child_cap:
                raise RuntimeError(f"parent {parent_id} reached max_children={inherited_child_cap}")
        for dependency in depends_on:
            _mission(store, dependency)

        mission_id = f"mission_{int(store['next_id']):04d}"
        store["next_id"] = int(store["next_id"]) + 1
        now = utc_now()
        mission = {
            "id": mission_id,
            "parent_id": parent_id,
            "depends_on": depends_on,
            "title": title,
            "kind": kind,
            "brief": brief,
            "acceptance": acceptance,
            "status": "planned",
            "budget": {"max_depth": max_depth, "max_children": max_children},
            "evidence": [],
            "owner_exp_id": None,
            "created_at": now,
            "updated_at": now,
        }
        store["nodes"][mission_id] = mission
        _refresh_ready(store)
        _write(root, graph)
        return dict(mission)


def list_missions(root: Path, *, status: str | None = None) -> list[dict[str, Any]]:
    graph = load_json(graph_path(root), default_graph())
    store = _store(graph)
    _refresh_ready(store)
    rows = [dict(m) for m in store["nodes"].values()]
    if status:
        rows = [m for m in rows if m.get("status") == status]
    return sorted(rows, key=lambda mission: (mission.get("created_at", ""), mission["id"]))


def claim_mission(root: Path, mission_id: str, *, owner_exp_id: str | None = None) -> dict[str, Any]:
    gpath = graph_path(root)
    with advisory_lock(gpath.with_suffix(gpath.suffix + ".lock")):
        graph = load_json(gpath, default_graph())
        store = _store(graph)
        _refresh_ready(store)
        mission = _mission(store, mission_id)
        if mission.get("status") == "running" and mission.get("owner_exp_id") == owner_exp_id:
            return dict(mission)  # idempotent retry by the same agent
        if mission.get("status") != "ready":
            raise RuntimeError(f"mission {mission_id} is {mission.get('status')}, not ready")
        mission["status"] = "running"
        mission["owner_exp_id"] = owner_exp_id
        mission["claimed_at"] = utc_now()
        mission["updated_at"] = utc_now()
        _write(root, graph)
        return dict(mission)


def finish_mission(root: Path, mission_id: str, *, status: str, summary: str = "") -> dict[str, Any]:
    if status not in {"succeeded", "failed", "blocked"}:
        raise RuntimeError("mission completion status must be succeeded, failed, or blocked")
    gpath = graph_path(root)
    with advisory_lock(gpath.with_suffix(gpath.suffix + ".lock")):
        graph = load_json(gpath, default_graph())
        store = _store(graph)
        mission = _mission(store, mission_id)
        if mission.get("status") in TERMINAL_STATUSES:
            raise RuntimeError(f"mission {mission_id} is already terminal")
        mission["status"] = status
        mission["summary"] = str(summary).strip()
        mission["updated_at"] = utc_now()
        _refresh_ready(store)
        _write(root, graph)
        return dict(mission)


def cancel_mission(root: Path, mission_id: str, *, cascade: bool = True) -> list[str]:
    gpath = graph_path(root)
    with advisory_lock(gpath.with_suffix(gpath.suffix + ".lock")):
        graph = load_json(gpath, default_graph())
        store = _store(graph)
        _mission(store, mission_id)
        pending = [mission_id]
        cancelled: list[str] = []
        while pending:
            current = pending.pop()
            mission = _mission(store, current)
            if mission.get("status") not in TERMINAL_STATUSES:
                mission["status"] = "cancelled"
                mission["updated_at"] = utc_now()
                cancelled.append(current)
            if cascade:
                pending.extend(m["id"] for m in store["nodes"].values() if m.get("parent_id") == current)
        _refresh_ready(store)
        _write(root, graph)
        return cancelled


def add_evidence(root: Path, mission_id: str, *, uri: str, sha256: str, summary: str) -> dict[str, Any]:
    if not uri or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise RuntimeError("evidence requires uri and a 64-character sha256")
    gpath = graph_path(root)
    with advisory_lock(gpath.with_suffix(gpath.suffix + ".lock")):
        graph = load_json(gpath, default_graph())
        store = _store(graph)
        mission = _mission(store, mission_id)
        evidence = {"uri": str(uri), "sha256": str(sha256).lower(), "summary": str(summary).strip(), "recorded_at": utc_now()}
        if not any(item.get("uri") == evidence["uri"] and item.get("sha256") == evidence["sha256"] for item in mission["evidence"]):
            mission["evidence"].append(evidence)
            mission["updated_at"] = utc_now()
            _write(root, graph)
        return evidence
