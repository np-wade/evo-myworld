"""``evo graph ...`` command handlers.

Kept out of the giant ``cli.py`` so the graph surface reads as one thing.  The
main CLI registers the ``graph`` parser (see ``cli.build_parser``) and delegates
to ``dispatch(args)`` here.  Handlers print JSON by default (``--json``) or a
compact human line, and follow the store's graceful-degradation policy: a
missing library index prints a message and returns exit 2, never a traceback.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from .store import GraphStore, GraphUnavailable
from .candidates import build_candidates, CandidateSet
from .inject import inject_prior_art
from .writeback import EvidenceGraph


def _err(msg: str) -> int:
    print(f"evo graph: {msg}", file=sys.stderr)
    return 2


def _emit(obj: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, default=str))


def _find(args: Any) -> int:
    store = GraphStore(getattr(args, "data_root", None))
    try:
        hits = store.find(
            args.query, repo=args.repo, limit=args.limit,
            kinds=(args.kind or None),
        )
    except GraphUnavailable as e:
        return _err(str(e))
    finally:
        store.close()
    if args.json:
        _emit([h.to_dict() for h in hits], as_json=True)
    else:
        if not hits:
            print("no hits (FTS covers top ~50k nodes/repo; a miss is not absence)")
        for h in hits:
            print(f"{h.repo_id}  {h.label}  [{h.kind}]  {h.source_location}  deg={h.degree}")
    return 0


def _neighbors(args: Any) -> int:
    store = GraphStore(getattr(args, "data_root", None))
    try:
        edges = store.neighbors(
            args.repo_id, args.node_id, direction=args.direction,
            relations=(args.relation or None), limit=args.limit,
        )
    except GraphUnavailable as e:
        return _err(str(e))
    finally:
        store.close()
    if args.json:
        _emit([
            {"relation": e.relation, "direction": e.direction, "neighbor": e.neighbor.to_dict()}
            for e in edges
        ], as_json=True)
    else:
        for e in edges:
            arrow = "->" if e.direction == "out" else "<-"
            n = e.neighbor
            print(f"{arrow} [{e.relation}] {n.label} [{n.kind}] {n.source_location}")
    return 0


def _subgraph(args: Any) -> int:
    store = GraphStore(getattr(args, "data_root", None))
    try:
        sg = store.subgraph(
            args.repo_id, args.node_id, hops=args.hops,
            direction=args.direction, relations=(args.relation or None),
            limit=args.limit,
        )
    except GraphUnavailable as e:
        return _err(str(e))
    finally:
        store.close()
    if args.json:
        _emit(sg, as_json=True)
    else:
        print(f"{len(sg['nodes'])} nodes, {len(sg['edges'])} edges")
        for e in sg["edges"]:
            print(f"  {e['src']} -[{e['relation']}]-> {e['dst']}")
    return 0


def _slice(args: Any) -> int:
    store = GraphStore(getattr(args, "data_root", None))
    try:
        slices = store.slices(args.repo, topic=args.topic)
    except GraphUnavailable as e:
        return _err(str(e))
    finally:
        store.close()
    if args.json:
        _emit(slices, as_json=True)
    else:
        print(f"{len(slices)} slice(s):")
        for s in slices:
            if "error" in s:
                print(f"  {s['path']}  (unreadable: {s['error']})")
            else:
                print(f"  {s['path']}\n    topic_terms={s['topic_terms']} "
                      f"nodes={s['node_count']} edges={s['edge_count']}\n"
                      f"    files={s['files']}  hubs={s['hubs']}")
    return 0


def _candidates(args: Any) -> int:
    store = GraphStore(getattr(args, "data_root", None))
    try:
        cset = build_candidates(
            store, args.need,
            queries=(args.query or None), repo=args.repo,
            kinds=(args.kind or None), per_query=args.limit, total=args.total,
        )
    finally:
        store.close()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(cset.to_json())
    if args.json:
        _emit(cset.to_dict(), as_json=True)
    else:
        print(cset.to_markdown())
        if cset.note:
            print(f"\n_note: {cset.note}_")
    return 0


def _inject(args: Any) -> int:
    if args.brief_file:
        brief = open(args.brief_file, encoding="utf-8").read()
    elif args.brief:
        brief = args.brief
    else:
        brief = sys.stdin.read()
    store = GraphStore(getattr(args, "data_root", None))
    try:
        out = inject_prior_art(
            brief, need=args.need, store=store, repo=args.repo,
            limit=args.limit, enabled=True,  # explicit invocation always injects
        )
    finally:
        store.close()
    print(out)
    return 0


def _record(args: Any) -> int:
    """Record an Evo experiment node (JSON on stdin or --node-file) into evidence.db."""
    if args.node_file:
        node = json.load(open(args.node_file, encoding="utf-8"))
    else:
        node = json.load(sys.stdin)
    eg = EvidenceGraph.open_for_workspace(args.root)
    try:
        uid = eg.record_experiment(
            node, agent=args.agent, model=args.model,
            environment=args.environment, harness=args.harness,
        )
    finally:
        eg.close()
    _emit({"recorded": uid}, as_json=args.json if hasattr(args, "json") else True)
    if not getattr(args, "json", False):
        print(f"recorded {uid}")
    return 0


def _lineage(args: Any) -> int:
    eg = EvidenceGraph.open_for_workspace(args.root)
    try:
        chain = eg.lineage(args.exp_id)
        beat = eg.beat_chain(args.exp_id)
    finally:
        eg.close()
    if getattr(args, "json", False):
        _emit({"lineage": chain, "beat": beat}, as_json=True)
    else:
        print("lineage (newest->oldest): " + " -> ".join(chain))
        if beat:
            print("beat: " + ", ".join(beat))
    return 0


def _stats(args: Any) -> int:
    eg = EvidenceGraph.open_for_workspace(args.root)
    try:
        st = eg.stats()
    finally:
        eg.close()
    _emit(st, as_json=True)
    return 0


def _export(args: Any) -> int:
    eg = EvidenceGraph.open_for_workspace(args.root)
    try:
        g = eg.export_graph()
    finally:
        eg.close()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(g, f, indent=2, default=str)
        print(f"wrote {args.out} ({len(g['nodes'])} nodes, {len(g['edges'])} edges)")
    else:
        _emit(g, as_json=True)
    return 0


_HANDLERS = {
    "find": _find,
    "neighbors": _neighbors,
    "subgraph": _subgraph,
    "slice": _slice,
    "candidates": _candidates,
    "inject": _inject,
    "record": _record,
    "lineage": _lineage,
    "stats": _stats,
    "export": _export,
}


def dispatch(args: Any) -> int:
    action = getattr(args, "graph_action", None)
    handler = _HANDLERS.get(action)
    if handler is None:
        return _err(f"unknown graph action {action!r}")
    return handler(args)
