from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import frontier_strategies as fs
from .core import (
    ascii_tree,
    attempt_outcome_path,
    best_committed_node,
    best_committed_score,
    collect_gates_from_path,
    experiments_path,
    frontier_nodes,
    graph_path,
    infra_path,
    load_annotations,
    load_config,
    load_graph,
    notes_path,
    parse_diff_patch,
    path_to_node,
    scratchpad_path,
)


FRONTIER_DISPLAY_CAP = 50
AWAITING_DISPLAY_CAP = 10
ANNOTATIONS_DISPLAY_CAP = 15
RECENT_EXPERIMENTS_DISPLAY_CAP = 8
RECENT_EVALUATED_WINDOW = 20  # how far back to consider an evaluated node "recent"
                               # for the bounded tree's relevance check


def _format_strategy_label(strategy: dict[str, Any]) -> str:
    kind = strategy.get("kind", "?")
    params = strategy.get("params") or {}
    if not params:
        return kind
    params_str = " ".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{kind} {params_str}"


def _rank_frontier(root: Path, raw_frontier: list[dict[str, Any]],
                   config: dict[str, Any], metric: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rank branchable nodes via the configured strategy.

    Returns (ranked_summaries, strategy). On a broken config we fall back to
    score-sorted raw frontier with a synthetic 'fallback' strategy so the
    scratchpad still renders.
    """
    summaries = [
        {
            "id": n["id"],
            "score": n.get("score"),
            "eval_epoch": n.get("eval_epoch"),
            "hypothesis": n.get("hypothesis"),
        }
        for n in raw_frontier
    ]
    try:
        strategy = fs.resolve_from_config(config)
        outcomes: dict[str, dict] = {}
        if strategy["kind"] == "pareto_per_task":
            for n in raw_frontier:
                attempt = n.get("current_attempt")
                if not attempt:
                    continue
                path = attempt_outcome_path(root, n["id"], int(attempt))
                if path.exists():
                    try:
                        outcomes[n["id"]] = json.loads(path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        pass
        # seed=0 keeps the scratchpad render deterministic across calls;
        # actual dispatch uses fresh randomness.
        ranked, _ = fs.pick(summaries, strategy, metric, outcomes=outcomes, seed=0)
        return ranked, strategy
    except (ValueError, KeyError):
        ranked = sorted(
            summaries,
            key=lambda n: (-(n.get("score") if n.get("score") is not None else float("-inf")), n["id"]),
        )
        for i, n in enumerate(ranked, 1):
            n["rank"] = i
        return ranked, {"kind": "fallback", "params": {}}


def _truncate(text: str, limit: int = 240) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _hyp_short(text: str | None, limit: int = 120) -> str:
    """Hypothesis text rendered short for inline use in tree/frontier/awaiting."""
    if not text:
        return ""
    return _truncate(text, limit=limit)


def _build_branch_root_map(graph: dict[str, Any]) -> dict[str, str]:
    """For each non-root node, the id of its top-level ancestor (the child of root
    that begins this branch). Computed once per scratchpad render so annotation
    grouping stays O(annotations) instead of O(annotations * depth)."""
    nodes = graph["nodes"]
    cache: dict[str, str] = {"root": "root"}

    def resolve(node_id: str) -> str:
        if node_id in cache:
            return cache[node_id]
        node = nodes.get(node_id)
        if not node:
            return "root"
        parent = node.get("parent")
        if parent in (None, "root"):
            cache[node_id] = node_id
            return node_id
        result = resolve(parent)
        cache[node_id] = result
        return result

    for node_id in nodes:
        resolve(node_id)
    return cache


def _bounded_tree(graph: dict[str, Any], metric: str,
                  branch_root_map: dict[str, str],
                  recent_evaluated_ids: set[str],
                  best_path_ids: set[str]) -> str:
    """Render the tree, expanding only subtrees that contain active /
    best-path / recent-evaluated descendants. Cold subtrees collapse to one
    line: '<connector><id> <status> score=X (+N descendants, best=Y)'."""
    nodes = graph["nodes"]
    sign = -1 if (metric or "").lower() == "min" else 1

    relevance_cache: dict[str, bool] = {}

    def is_relevant(node_id: str) -> bool:
        if node_id in relevance_cache:
            return relevance_cache[node_id]
        node = nodes.get(node_id)
        if not node:
            relevance_cache[node_id] = False
            return False
        if node_id == "root":
            relevance_cache[node_id] = True
            return True
        if node.get("status") == "active":
            relevance_cache[node_id] = True
            return True
        if node_id in best_path_ids or node_id in recent_evaluated_ids:
            relevance_cache[node_id] = True
            return True
        for child_id in node.get("children", []):
            if child_id in nodes and is_relevant(child_id):
                relevance_cache[node_id] = True
                return True
        relevance_cache[node_id] = False
        return False

    stats_cache: dict[str, tuple[int, float | None]] = {}

    def descendant_stats(node_id: str) -> tuple[int, float | None]:
        if node_id in stats_cache:
            return stats_cache[node_id]
        count = 0
        best_score: float | None = None
        node = nodes.get(node_id)
        if not node:
            stats_cache[node_id] = (0, None)
            return 0, None
        for child_id in node.get("children", []):
            if child_id not in nodes:
                continue
            count += 1
            child = nodes[child_id]
            cs = child.get("score")
            if cs is not None:
                if best_score is None or sign * cs > sign * best_score:
                    best_score = cs
            sub_count, sub_best = descendant_stats(child_id)
            count += sub_count
            if sub_best is not None:
                if best_score is None or sign * sub_best > sign * best_score:
                    best_score = sub_best
        stats_cache[node_id] = (count, best_score)
        return count, best_score

    def label(node: dict[str, Any], collapsed: bool = False) -> str:
        parts: list[str] = [node["id"], node.get("status", "unknown")]
        if node.get("score") is not None:
            parts.append(f"score={node['score']}")
        if node.get("eval_epoch") is not None:
            parts.append(f"epoch={node['eval_epoch']}")
        if node.get("pruned_reason"):
            parts.append("pruned")
        if node.get("gates"):
            parts.append(f"gates={len(node['gates'])}")
        if node.get("hypothesis") and node["id"] != "root":
            parts.append(_hyp_short(node["hypothesis"]))
        line = " ".join(parts)
        if collapsed:
            sub_count, sub_best = descendant_stats(node["id"])
            best_str = f", best={sub_best}" if sub_best is not None else ""
            line += f" (+{sub_count} descendants{best_str})"
        return line

    lines: list[str] = []

    def walk(node_id: str, prefix: str = "", is_last: bool = True) -> None:
        node = nodes.get(node_id)
        if not node:
            return
        if node_id == "root":
            lines.append(label(node))
        else:
            connector = "└── " if is_last else "├── "
            if not is_relevant(node_id):
                lines.append(prefix + connector + label(node, collapsed=True))
                return
            lines.append(prefix + connector + label(node))
        children = sorted([c for c in node.get("children", []) if c in nodes])
        for index, child_id in enumerate(children):
            extension = "" if node_id == "root" else ("    " if is_last else "│   ")
            walk(child_id, prefix + extension, index == len(children) - 1)

    walk("root")
    return "\n".join(lines)


def _diff_summary(root: Path, exp_id: str, attempt: int) -> str | None:
    parsed = parse_diff_patch(root, exp_id, attempt)
    if not parsed:
        return None
    files = parsed["files"]
    file_str = ", ".join(files[:3])
    if len(files) > 3:
        file_str += f" (+{len(files) - 3} more)"
    return f"{file_str} (+{parsed['added']}/-{parsed['removed']})"


def _group_annotations_by_branch_task(
    annotations: list[dict[str, Any]],
    branch_root_map: dict[str, str],
) -> list[tuple[tuple[str, str], dict[str, Any]]]:
    """Group annotations by (branch_root, task_id), keeping only the latest per
    key. Sorted by timestamp descending so caller can take the top K most
    recent insights diverse across branches.

    Falls back to ('unknown', task_id) for annotations whose experiment_id is
    no longer in the graph (legacy data)."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in annotations:
        exp_id = entry.get("experiment_id")
        branch = branch_root_map.get(exp_id, "unknown") if exp_id else "unknown"
        task = entry.get("task_id") or "global"
        key = (branch, task)
        existing = latest.get(key)
        if existing is None or entry.get("timestamp", "") >= existing.get("timestamp", ""):
            latest[key] = entry
    return sorted(
        latest.items(),
        key=lambda item: item[1].get("timestamp", ""),
        reverse=True,
    )


def _dedup_discarded(discarded: list[dict[str, Any]], limit: int = 15) -> list[tuple[str, int]]:
    """Deduplicate discarded hypotheses by normalized text. Returns (hypothesis, count) pairs."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for node in discarded:
        hyp = node.get("hypothesis", "")
        key = " ".join(hyp.lower().split())
        counts[key] = counts.get(key, 0) + 1
        display[key] = hyp  # keep the original casing from the latest
    sorted_items = sorted(counts.items(), key=lambda item: -item[1])
    return [(display[key], count) for key, count in sorted_items[:limit]]


def build_scratchpad(root: Path) -> str:
    config = load_config(root)
    graph = load_graph(root)
    annotations = load_annotations(root).get("annotations", [])
    infra = json.loads(infra_path(root).read_text(encoding="utf-8")).get("events", []) if infra_path(root).exists() else []
    notes = notes_path(root).read_text(encoding="utf-8") if notes_path(root).exists() else ""
    metric = config.get("metric", "max")
    committed = [node for node in graph["nodes"].values() if node.get("status") == "committed"]
    discarded = [node for node in graph["nodes"].values() if node.get("status") == "discarded"]
    evaluated = [node for node in graph["nodes"].values() if node.get("status") == "evaluated"]
    active = [node for node in graph["nodes"].values() if node.get("status") == "active"]
    best = best_committed_score(graph, metric)
    frontier = frontier_nodes(graph)
    recent_all = sorted(
        [node for node in graph["nodes"].values() if node["id"] != "root"],
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )
    recent = recent_all[:RECENT_EXPERIMENTS_DISPLAY_CAP]
    branch_root_map = _build_branch_root_map(graph)
    recent_evaluated_ids = {
        n["id"] for n in recent_all[:RECENT_EVALUATED_WINDOW]
        if n.get("status") == "evaluated"
    }
    best_committed = best_committed_node(graph, metric)
    best_path_ids: set[str] = set()
    if best_committed and best_committed["id"] != "root":
        best_path_ids = {n["id"] for n in path_to_node(graph, best_committed["id"])}

    lines = [
        "# Scratchpad",
        "",
        "## Status",
        f"- Metric: `{metric}`",
        f"- Current eval epoch: `{config.get('current_eval_epoch', 1)}`",
        f"- Best score: `{best}`",
        f"- Total experiments: `{len(graph['nodes']) - 1}`",
        f"- Committed: `{len(committed)}`",
        f"- Evaluated (awaiting decision): `{len(evaluated)}`",
        f"- Discarded: `{len(discarded)}`",
        f"- Active workers: `{len(active)}`",
    ]

    # Tree (bounded: expand active / best-path / recent-evaluated subtrees;
    # collapse cold subtrees as one line each)
    lines.extend(["", "## Tree", "```"])
    lines.append(_bounded_tree(graph, metric, branch_root_map,
                               recent_evaluated_ids, best_path_ids))
    lines.extend(["```"])

    # Best path
    best_node = best_committed
    if best_node and best_node["id"] != "root":
        chain = path_to_node(graph, best_node["id"])
        lines.extend(["", "## Best Path"])
        path_parts = []
        for node in chain:
            if node["id"] == "root":
                path_parts.append("root")
            else:
                score_str = f" ({node.get('score')})" if node.get("score") is not None else ""
                path_parts.append(f"{node['id']}{score_str}")
        lines.append(" -> ".join(path_parts))

    # Frontier (strategy-ranked; deterministic seed for stable rendering)
    ranked_frontier, strategy = _rank_frontier(root, frontier, config, metric)
    lines.extend(["", f"## Frontier (strategy: {_format_strategy_label(strategy)})"])
    if ranked_frontier:
        shown = ranked_frontier[:FRONTIER_DISPLAY_CAP]
        for node in shown:
            lines.append(
                f"- `{node['id']}` score=`{node.get('score')}` "
                f"epoch=`{node.get('epoch')}` {_hyp_short(node.get('hypothesis'))}"
            )
        if len(ranked_frontier) > FRONTIER_DISPLAY_CAP:
            lines.append(
                f"(+{len(ranked_frontier) - FRONTIER_DISPLAY_CAP} more — see `evo frontier`)"
            )
    else:
        lines.append("- No frontier nodes yet.")

    if evaluated:
        lines.extend(["", "## Awaiting Decision"])
        lines.append("These nodes ran but neither committed nor discarded. Retry (edit + `evo run`) or abandon (`evo discard --reason`).")
        evaluated_recent = sorted(
            evaluated,
            key=lambda n: n.get("updated_at", ""),
            reverse=True,
        )
        for node in evaluated_recent[:AWAITING_DISPLAY_CAP]:
            attempts = int(node.get("evaluated_attempts", 0))
            lines.append(
                f"- `{node['id']}` score=`{node.get('score')}` attempts=`{attempts}` "
                f"gate_failed=`{node.get('gate_failures') or []}` {_hyp_short(node.get('hypothesis'))}"
            )
        if len(evaluated_recent) > AWAITING_DISPLAY_CAP:
            lines.append(
                f"(+{len(evaluated_recent) - AWAITING_DISPLAY_CAP} more — see `evo awaiting`)"
            )

    # Gates
    # Show gates from root (always active) + any unique gates on frontier nodes
    root_gates = graph["nodes"].get("root", {}).get("gates", [])
    if root_gates or any(n.get("gates") for n in frontier):
        lines.extend(["", "## Gates"])
        if root_gates:
            for g in root_gates:
                lines.append(f"- `{g['name']}` (root): `{_truncate(g['command'], 120)}`")
        seen_names = {g["name"] for g in root_gates}
        for node in frontier[:10]:
            effective = collect_gates_from_path(graph, node["id"])
            for g in effective:
                if g["name"] not in seen_names:
                    seen_names.add(g["name"])
                    lines.append(f"- `{g['name']}` (from tree): `{_truncate(g['command'], 120)}`")

    # Recent experiments
    lines.extend(["", "## Recent Experiments"])
    if recent:
        for node in recent:
            lines.append(
                f"- `{node['id']}` `{node.get('status')}` score=`{node.get('score')}` {_hyp_short(node.get('hypothesis'))}"
            )
    else:
        lines.append("- No experiments yet.")

    # Recent diffs
    recent_committed = [n for n in recent if n.get("status") == "committed" and n["id"] != "root"][:5]
    if recent_committed:
        lines.extend(["", "## Recent Diffs"])
        for node in recent_committed:
            summary = _diff_summary(root, node["id"], int(node.get("current_attempt", 0)))
            if summary:
                lines.append(f"- `{node['id']}`: {summary}")

    # Annotations grouped by (branch_root, task) — keeps insights from sibling
    # branches visible instead of letting the latest experiment globally
    # overwrite older per-task analyses.
    lines.extend(["", "## Annotations"])
    if annotations:
        grouped = _group_annotations_by_branch_task(annotations, branch_root_map)
        for (branch, task_id), entry in grouped[:ANNOTATIONS_DISPLAY_CAP]:
            lines.append(
                f"- branch `{branch}` / task `{task_id}` / `{entry['experiment_id']}`: "
                f"{_truncate(entry['analysis'])}"
            )
        if len(grouped) > ANNOTATIONS_DISPLAY_CAP:
            lines.append(
                f"(+{len(grouped) - ANNOTATIONS_DISPLAY_CAP} more — see `evo annotations`)"
            )
    else:
        lines.append("- No annotations yet.")

    # What Not To Try (deduplicated)
    lines.extend(["", "## What Not To Try"])
    if discarded:
        deduped = _dedup_discarded(discarded)
        for hyp, count in deduped:
            suffix = f" (x{count})" if count > 1 else ""
            lines.append(f"- {_truncate(hyp)}{suffix}")
    else:
        lines.append("- No discarded hypotheses yet.")

    # Infrastructure log
    lines.extend(["", "## Infrastructure Log"])
    if infra:
        for event in infra[-8:]:
            suffix = " (breaking)" if event.get("breaking") else ""
            # 0.3.0 frontier events shipped with key "at" and no "message"
            # (#22). Read tolerantly so workspaces upgrading to >=0.3.1 don't
            # KeyError on the pre-existing bad events still in their log.
            ts = event.get("timestamp") or event.get("at") or "?"
            msg = event.get("message") or f"{event.get('kind', '?')} event"
            lines.append(f"- {ts}: {msg}{suffix}")
    else:
        lines.append("- No infrastructure events yet.")

    # Notes -- aggregate per-node notes (from `evo set --note`) plus the
    # legacy notes.md (left writable for `core.append_note` callers; the
    # current shipping flow writes per-node).
    lines.extend(["", "## Notes"])
    per_node_notes: list[str] = []
    for node in graph["nodes"].values():
        if node.get("id") == "root":
            continue
        for entry in node.get("notes", []):
            ts = entry.get("timestamp", "")
            text = entry.get("text", "").strip()
            if not text:
                continue
            per_node_notes.append(f"- [{ts} {node['id']}] {text}")
    aggregated_parts: list[str] = []
    if per_node_notes:
        aggregated_parts.append("\n".join(per_node_notes[-12:]))
    if notes.strip():
        aggregated_parts.append(_truncate(notes, limit=1200))
    if aggregated_parts:
        lines.extend(aggregated_parts)
    else:
        lines.append("No notes yet.")
    lines.append("")
    return "\n".join(lines)


def write_scratchpad(root: Path) -> str:
    content = build_scratchpad(root)
    scratchpad_path(root).write_text(content, encoding="utf-8")
    return content
