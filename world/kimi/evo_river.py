#!/usr/bin/env python3
"""evo-river — a horizontal time-river view of an evo experiment tree.

Reads `.evo/<active-run>/graph.json` (or a `--graph` fixture) and renders the
tree as a left-to-right river: root is upstream, later generations flow
downstream, the current best spine is the bright main channel, and frontier
nodes are marked with a splash.

This is a Kimi-seat dashboard surface for evo-myworld: it can be invoked as a
standalone CLI, consumed by the dashboard at `/api/river`, or imported as
`render_river(graph, metric)`.

Usage:
    python3 world/kimi/evo_river.py [--run RUN] [--graph PATH] [--width N] [--no-color]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path | None:
    """Best-effort evo workspace discovery (cwd or any parent containing .evo)."""
    cwd = Path.cwd().resolve()
    for p in [cwd, *cwd.parents]:
        if (p / ".evo").is_dir():
            return p
    return None


def _load_evo() -> tuple[Any, Any] | None:
    """Import evo.core helpers when the package is available."""
    try:
        from evo.core import load_config, load_graph, repo_root  # type: ignore

        return load_graph, load_config
    except Exception:
        return None


def _load_graph(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _default_graph_fixture() -> dict[str, Any]:
    """A tiny synthetic tree used when no workspace or --graph is supplied."""
    return {
        "nodes": {
            "root": {
                "id": "root",
                "status": "committed",
                "children": ["exp_0000", "exp_0001"],
                "hypothesis": "baseline",
            },
            "exp_0000": {
                "id": "exp_0000",
                "parent": "root",
                "status": "committed",
                "score": 5.1,
                "eval_epoch": 1,
                "children": ["exp_0002"],
                "hypothesis": "naive dedup",
            },
            "exp_0001": {
                "id": "exp_0001",
                "parent": "root",
                "status": "discarded",
                "score": 5.2,
                "eval_epoch": 1,
                "children": [],
                "hypothesis": "wrong turn",
            },
            "exp_0002": {
                "id": "exp_0002",
                "parent": "exp_0000",
                "status": "committed",
                "score": 0.01,
                "eval_epoch": 2,
                "children": [],
                "hypothesis": "sorted(set)",
            },
        }
    }


def _status_color(status: str, use_color: bool) -> str:
    if not use_color:
        return ""
    codes = {
        "committed": "\033[32m",   # green
        "failed": "\033[31m",      # red
        "discarded": "\033[33m",   # yellow
        "active": "\033[34m",      # blue
        "evaluated": "\033[35m",   # magenta
        "pending": "\033[90m",     # grey
        "pruned": "\033[90m",      # grey
        "root": "\033[37m",        # white
    }
    return codes.get(status, "")


def _reset(use_color: bool) -> str:
    return "\033[0m" if use_color else ""


def _layout(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Assign (level, lane) to every node for the river layout.

    level = BFS depth from root (time/generation).
    lane  = vertical slot within the level, packed by parent order.
    """
    nodes = graph.get("nodes", {})
    if "root" not in nodes:
        return {}

    layout: dict[str, dict[str, Any]] = {}
    levels: dict[int, list[str]] = {0: []}
    queue: list[tuple[str, int]] = [("root", 0)]
    seen = set()

    while queue:
        node_id, level = queue.pop(0)
        if node_id in seen or node_id not in nodes:
            continue
        seen.add(node_id)
        levels.setdefault(level, [])
        lane = len(levels[level])
        levels[level].append(node_id)
        layout[node_id] = {"node": nodes[node_id], "level": level, "lane": lane}
        for child in nodes[node_id].get("children", []):
            if child not in seen:
                queue.append((child, level + 1))

    return layout


def _find_frontier(graph: dict[str, Any]) -> set[str]:
    """Frontier = committed leaves with no committed/active descendants."""
    try:
        from evo.core import frontier_nodes  # type: ignore

        return {n["id"] for n in frontier_nodes(graph)}
    except Exception:
        pass

    nodes = graph.get("nodes", {})
    frontier: set[str] = set()
    for nid, node in nodes.items():
        if nid == "root":
            continue
        if node.get("status") != "committed":
            continue
        children = node.get("children", [])
        active_or_committed_children = [
            c for c in children
            if c in nodes and nodes[c].get("status") in ("committed", "active")
        ]
        if not active_or_committed_children:
            frontier.add(nid)
    return frontier


def _find_best_spine(graph: dict[str, Any], metric: str) -> set[str]:
    """Best spine = path from root to the best committed node, evo-style."""
    try:
        from evo.core import best_spine_ids  # type: ignore

        return set(best_spine_ids(graph, metric))
    except Exception:
        pass

    nodes = graph.get("nodes", {})
    sign = -1 if (metric or "").lower() == "min" else 1
    committed = [
        n for n in nodes.values()
        if n.get("id") != "root" and n.get("status") == "committed"
        and n.get("score") is not None
    ]
    if not committed:
        return set()
    best = max(committed, key=lambda n: sign * float(n.get("score", 0)))
    spine: set[str] = {best["id"]}
    parent_map = {
        child: nid
        for nid, node in nodes.items()
        for child in node.get("children", [])
    }
    cur = best["id"]
    while cur in parent_map:
        cur = parent_map[cur]
        spine.add(cur)
    return spine


def _node_label(node: dict[str, Any], max_len: int = 16) -> str:
    nid = node.get("id", "?")
    score = node.get("score")
    parts = [nid]
    if score is not None:
        parts.append(f"s={score}")
    text = " ".join(parts)
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def _label_len(label: str) -> int:
    """Visible length excluding ANSI escape sequences."""
    import re
    return len(re.sub(r"\033\[[0-9;]*m", "", label))


def render_river(graph: dict[str, Any], metric: str = "max",
                 width: int = 78, use_color: bool = True) -> str:
    """Render a horizontal time-river ASCII view of the experiment tree."""
    layout = _layout(graph)
    if not layout:
        return "(empty graph)"

    nodes = graph.get("nodes", {})
    frontier = _find_frontier(graph)
    spine = _find_best_spine(graph, metric)

    # Group nodes by level and sort by lane.
    by_level: dict[int, list[str]] = {}
    for nid, info in layout.items():
        by_level.setdefault(info["level"], []).append(nid)
    for lvl in by_level:
        by_level[lvl].sort(key=lambda nid: layout[nid]["lane"])

    max_level = max(by_level.keys())
    max_nodes_in_level = max(len(v) for v in by_level.values())
    row_height = 3
    rows = max(8, (max_level + 1) * max_nodes_in_level * row_height)
    cols = max(width, 40)

    # Horizontal slot per level: fixed width, left-padded.
    slot_width = max(16, cols // (max_level + 2))

    # Build a 2D character canvas.
    canvas = [[" " for _ in range(cols)] for _ in range(rows)]

    def put(x: int, y: int, s: str) -> None:
        for i, ch in enumerate(s):
            if 0 <= x + i < cols and 0 <= y < rows:
                canvas[y][x + i] = ch

    def hline(x0: int, x1: int, y: int) -> None:
        for x in range(min(x0, x1), max(x0, x1) + 1):
            if 0 <= x < cols and 0 <= y < rows:
                if canvas[y][x] == " ":
                    canvas[y][x] = "─"

    def vline(x: int, y0: int, y1: int) -> None:
        for y in range(min(y0, y1), max(y0, y1) + 1):
            if 0 <= x < cols and 0 <= y < rows:
                if canvas[y][x] == " ":
                    canvas[y][x] = "│"

    # Compute coordinates for each node.
    coords: dict[str, tuple[int, int, str]] = {}
    for lvl in range(max_level + 1):
        x = 1 + lvl * slot_width
        nids = by_level.get(lvl, [])
        for idx, nid in enumerate(nids):
            y = 1 + idx * row_height
            node = nodes.get(nid, {})
            label = _node_label(node)
            markers = []
            if nid in frontier:
                markers.append("*")
            if nid in spine:
                markers.append("▲")
            prefix = ("".join(markers) + " ") if markers else ""
            color = _status_color(node.get("status", ""), use_color)
            reset = _reset(use_color)
            full = color + prefix + label + reset
            coords[nid] = (x, y, full)

    # Draw connectors first so labels paint over them.
    for nid, (px, py, plabel) in coords.items():
        node = nodes.get(nid, {})
        label_len = _label_len(plabel)
        right_x = px + label_len + 1
        for child in node.get("children", []):
            if child not in coords:
                continue
            cx, cy, _ = coords[child]
            mid_x = right_x + max(1, (cx - right_x) // 2)
            # Horizontal from parent to mid.
            hline(right_x, mid_x, py)
            if py == cy:
                # Same row: straight horizontal line.
                hline(mid_x, cx - 1, cy)
            else:
                # Vertical to child row, then horizontal into child.
                vline(mid_x, py, cy)
                hline(mid_x, cx - 1, cy)
                # Corner glyph where vertical meets child horizontal.
                if 0 <= mid_x < cols:
                    corner_y = cy - 1 if cy > py else cy + 1
                    if 0 <= corner_y < rows:
                        canvas[corner_y][mid_x] = "┌" if cy > py else "└"

    # Draw labels last.
    for nid, (x, y, full) in coords.items():
        put(x, y, full)

    # Build output rows, trimming trailing spaces and empty bottom rows.
    lines = ["".join(row).rstrip() for row in canvas]
    while lines and not lines[-1].strip():
        lines.pop()

    header = f"evo-river  metric={metric}  frontier={len(frontier)}  spine={len(spine)}"
    legend = "markers: * frontier  ▲ best-spine  colors: green=kept red=failed yellow=skip blue=active"
    if not use_color:
        legend = "markers: * frontier  ▲ best-spine  (colors disabled)"

    return "\n".join([header, "─" * min(width, len(header)), *lines, "", legend])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render evo experiment tree as a time-river.")
    parser.add_argument("--run", help="evo run id (defaults to active run)")
    parser.add_argument("--graph", help="path to a graph.json fixture")
    parser.add_argument("--width", type=int, default=78, help="terminal width")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    parser.add_argument("--metric", default="max", help="score direction (max|min)")
    args = parser.parse_args(argv)

    use_color = not args.no_color and os.environ.get("TERM", "") not in ("", "dumb")

    if args.graph:
        graph = _load_graph(Path(args.graph))
    else:
        evo = _load_evo()
        root = _repo_root()
        if evo is not None and root is not None:
            load_graph, load_config = evo
            graph = load_graph(root)
            cfg = load_config(root)
            args.metric = cfg.get("metric", args.metric)
        else:
            graph = _default_graph_fixture()

    print(render_river(graph, metric=args.metric, width=args.width, use_color=use_color))
    return 0


if __name__ == "__main__":
    sys.exit(main())
