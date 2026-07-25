"""The run loop — drives candidates over the ladder and produces a leaderboard.

Composes the core modules (Lightning-style loop with callbacks; Haystack-style
composable stages): for each candidate, for each task → fetch/extract → score
axes → item_quality → gates → RunRecord → store. Then cluster failures and rank.

The heavy scraper deps live in adapters; this module is pure stdlib + the local
core modules. A candidate whose deps are missing (`available()==False`) is
skipped and recorded as scratched — never crashes the race (CONTRACT rule 4).
Robustness: a task may be run N times; the repeated qualities feed
metrics.robustness_score.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import replace
from typing import Callable, Optional

from . import metrics, failure as failuremod
from .gates import GateSet
from .interface import (
    AxisScores, Candidate, ExtractResult, FetchResult, LeaderRow, RunRecord,
    Task, WeightClass,
)
from .leaderboard import rank, rank_by_class, to_markdown
from .ladder import read_fixture_html
from .store import RunStore, ResultCache


def _now() -> float:
    return time.time()


def _field_stats(cfg: dict) -> dict:
    """Map ladder.json field_stats -> the keys metrics.score expects."""
    fs = (cfg or {}).get("field_stats", {})
    lat = fs.get("latency_ms", {})
    cost = fs.get("cost", {})
    return {
        "latency_min_ms": float(lat.get("min", 0.0)),
        "latency_max_ms": float(lat.get("max", 30000.0)),
        "cost_max": float(cost.get("max", 5e8)),
    }


def _scratch_record(cand: Candidate, task: Task, reason: str, ts: float) -> RunRecord:
    axes = AxisScores(extra={"weight_class": float(int(cand.weight_class))})
    return RunRecord(
        candidate=cand.name, task_id=task.id, tier=task.tier.value,
        axes=axes, quality=0.0, gate_passed=False,
        fetch=FetchResult(ok=False, error=reason, blocked=False),
        extract=None, error=reason, ts=ts,
    )


def run_one(
    cand: Candidate,
    task: Task,
    field_stats: dict,
    gates: GateSet,
    retries: int = 1,
    ts_fn: Callable[[], float] = _now,
) -> RunRecord:
    """Run a single candidate on a single task (with optional repeats for
    robustness), score it, gate it, and return the RunRecord."""
    ts = ts_fn()
    is_extractor = int(cand.weight_class) == int(WeightClass.EXTRACTOR)
    qualities: list[float] = []
    last_fetch: Optional[FetchResult] = None
    last_extract: Optional[ExtractResult] = None

    for _ in range(max(1, retries)):
        try:
            if is_extractor:
                html = read_fixture_html(task) if task.url.startswith("file://") else ""
                extract = cand.extract(html, task)
                # wrap extract into a fetch-shaped result so shared axes score
                fetch = FetchResult(ok=extract.ok, text=extract.text, html=html,
                                    error=extract.error)
                last_extract = extract
            else:
                fetch = cand.fetch(task)
                last_extract = None
            last_fetch = fetch
        except Exception as exc:  # adapter blew up on this item — record, don't die
            return _scratch_record(cand, task,
                                   f"exception: {exc.__class__.__name__}: {exc}", ts)
        axes_once = metrics.score(fetch, last_extract, task, field_stats)
        qualities.append(metrics.item_quality(axes_once, int(cand.weight_class)))

    # final axes computed with the robustness sample folded in
    fs = dict(field_stats)
    fs["qualities"] = qualities
    axes = metrics.score(last_fetch, last_extract, task, fs)
    axes.extra["weight_class"] = float(int(cand.weight_class))
    quality = sum(qualities) / len(qualities) if qualities else 0.0

    rec = RunRecord(
        candidate=cand.name, task_id=task.id, tier=task.tier.value,
        axes=axes, quality=quality, gate_passed=True,
        fetch=last_fetch, extract=last_extract, ts=ts,
    )
    passed, reasons = gates.check_all(rec)
    rec.gate_passed = passed
    if not passed:
        rec.error = "; ".join(reasons)
    return rec


def run_bracket(
    candidates: list[Candidate],
    tasks: list[Task],
    gate_spec: dict,
    cfg: dict,
    store: Optional[RunStore] = None,
    weights: Optional[dict] = None,
    retries: int = 1,
    on_event: Optional[Callable[[str, dict], None]] = None,
    ts_fn: Callable[[], float] = _now,
) -> dict:
    """Race all candidates over all tasks. Returns a dict with:
    records, leaderboard (list[LeaderRow]), per_class, failure_clusters.
    A candidate is only run on tasks matching its weight class OR any task when
    it declares class 1-3 and the task isn't an extractor-only task."""
    field_stats = _field_stats(cfg)
    gates = GateSet.from_spec(gate_spec or {})
    records: list[RunRecord] = []

    def emit(kind: str, data: dict):
        if on_event:
            on_event(kind, data)

    emit("bracket_start", {"candidates": [c.name for c in candidates], "n_tasks": len(tasks)})

    for cand in candidates:
        if not cand.available():
            for task in _tasks_for(cand, tasks):
                rec = _scratch_record(cand, task, "unavailable: missing deps", ts_fn())
                records.append(rec)
                if store:
                    store.record(rec)
            emit("candidate_skipped", {"candidate": cand.name})
            continue
        for task in _tasks_for(cand, tasks):
            rec = run_one(cand, task, field_stats, gates, retries=retries, ts_fn=ts_fn)
            records.append(rec)
            if store:
                store.record(rec)
            emit("task_done", {"candidate": cand.name, "task": task.id,
                               "quality": round(rec.quality, 3), "gate": rec.gate_passed})

    board = rank(records, weights=weights)
    per_class = {k: rank(v) for k, v in _by_class_records(records).items()}
    clusters = failuremod.cluster(records)
    emit("bracket_done", {"winner": board[0].candidate if board else None})
    return {
        "records": records,
        "leaderboard": board,
        "per_class": per_class,
        "failure_clusters": clusters,
    }


def _tasks_for(cand: Candidate, tasks: list[Task]) -> list[Task]:
    """Which tasks a candidate should run. Extractors run only extractor tasks
    (schema present); fetch-class candidates run non-extractor tasks."""
    is_extractor = int(cand.weight_class) == int(WeightClass.EXTRACTOR)
    out = []
    for t in tasks:
        task_is_extractor = bool(t.schema.get("fields")) or t.meta.get("class") == 4
        if is_extractor and task_is_extractor:
            out.append(t)
        elif not is_extractor and not task_is_extractor:
            out.append(t)
    return out


def _by_class_records(records: list[RunRecord]) -> dict:
    out: dict[int, list[RunRecord]] = {}
    for r in records:
        wc = int(r.axes.extra.get("weight_class", 1))
        out.setdefault(wc, []).append(r)
    return out


def render_result_md(result: dict, title: str) -> str:
    """Full race result: overall board + per-class + why-they-lost."""
    parts = [f"# Race result: {title}\n"]
    parts.append(to_markdown(result["leaderboard"], "Overall leaderboard"))
    for wc, rows in sorted(result["per_class"].items()):
        parts.append("\n" + to_markdown(rows, f"Weight class {wc}"))
    parts.append("\n## Why candidates lost\n")
    parts.append(failuremod.cluster_report_md(result["failure_clusters"]))
    return "\n".join(parts)
