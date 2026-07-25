"""failure.py — per-task failure trace + clustering ("why a candidate lost").

Pure stdlib. Turns the stream of per-item RunRecords a race produces into a
small set of human-readable failure clusters, so the leaderboard can explain
WHY each candidate dropped each item instead of only showing that it did.

Donor lineage — latitude-dev_latitude-llm (event -> signal -> incident):
    In latitude-llm, low-level trace *events* are matched into *Signals* by a
    shared matching criterion, and Signals escalate into *Incidents* once their
    occurrence count crosses a threshold; the incident view sorts by occurrence
    count so the biggest recurring problem surfaces first
    (see apps/workers/src/workers/signals-match.ts and
     apps/web/src/domains/signals/signals.functions.ts — escalationOccurrence /
     histogram bucket + count model).
    Ported IDEA (not the TS/Effect/DB machinery): derive a stable *signature*
    for each failing record (our "signal"), group records that share a
    signature into a FailureCluster (our "incident"), and rank clusters by
    occurrence count. Everything here is stdlib and offline.

The signature is the single load-bearing seam: metrics/gates fill a RunRecord,
and this module reads only fields already on the interface — no re-scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .interface import AxisScores, RunRecord

# The scraping axes that actually drive item_quality. Search axes (relevance,
# recall, freshness, selfhost) default to 0 for a scraping task and the footprint
# tie-breakers (latency_norm, cost_norm) are not "why the content was bad", so
# neither set counts as a *reason* a candidate underperformed. Order is the
# deterministic tie-break: on an exact tie the earlier axis wins.
AXES_THAT_MATTER: tuple[str, ...] = (
    "retrieval",
    "completeness",
    "evasion",
    "field_accuracy",
    "robustness",
)


def dominant_weak_axis(axes: AxisScores) -> str:
    """Name of the AxisScores field dragging quality down the most.

    Returns the field in AXES_THAT_MATTER with the lowest value; ties resolve to
    the earlier axis in AXES_THAT_MATTER (stable, so signatures are reproducible).
    """
    best_axis = AXES_THAT_MATTER[0]
    best_val = getattr(axes, best_axis)
    for name in AXES_THAT_MATTER[1:]:
        val = getattr(axes, name)
        if val < best_val:
            best_val = val
            best_axis = name
    return best_axis


def failure_signature(rec: RunRecord) -> str:
    """Stable signature for WHY this record failed/underperformed, or "" if clean.

    Priority order (first match wins):
      1. record-level error        -> "error:<first line>"
      2. fetch flagged as blocked  -> "blocked:tier=<tier>"
      3. fetch not ok              -> "fetch_fail:status=<status>"
      4. a gate scratched it       -> "gate_fail"
      5. quality below 0.5         -> "low_quality:<dominant weak axis>"
      6. otherwise                 -> "" (no failure — no cluster)
    """
    if rec.error:
        first_line = rec.error.splitlines()[0].strip() if rec.error.strip() else ""
        return "error:" + first_line
    if rec.fetch is not None and rec.fetch.blocked:
        return "blocked:tier=" + rec.tier
    if rec.fetch is not None and not rec.fetch.ok:
        return "fetch_fail:status=" + str(rec.fetch.status)
    if not rec.gate_passed:
        return "gate_fail"
    if rec.quality < 0.5:
        return "low_quality:" + dominant_weak_axis(rec.axes)
    return ""


@dataclass
class FailureCluster:
    """An "incident": all failing records that share one signature."""
    signature: str
    count: int
    candidates: list[str] = field(default_factory=list)   # distinct candidates hit
    task_ids: list[str] = field(default_factory=list)     # distinct tasks hit
    sample_error: str = ""                                # one representative error string


def _sample_error(rec: RunRecord) -> str:
    """Best available human-readable error text for a record."""
    if rec.error:
        return rec.error.splitlines()[0].strip() if rec.error.strip() else rec.error
    if rec.fetch is not None and rec.fetch.error:
        return rec.fetch.error.splitlines()[0].strip()
    return ""


def cluster(records: list[RunRecord]) -> list[FailureCluster]:
    """Group records with a non-empty signature into clusters, sorted by count desc.

    Ties on count break by signature (ascending) for a deterministic ordering.
    Candidates and task_ids within a cluster are distinct and sorted.
    """
    groups: dict[str, list[RunRecord]] = {}
    for rec in records:
        sig = failure_signature(rec)
        if not sig:
            continue
        groups.setdefault(sig, []).append(rec)

    clusters: list[FailureCluster] = []
    for sig, recs in groups.items():
        sample = ""
        for rec in recs:
            sample = _sample_error(rec)
            if sample:
                break
        clusters.append(
            FailureCluster(
                signature=sig,
                count=len(recs),
                candidates=sorted({rec.candidate for rec in recs}),
                task_ids=sorted({rec.task_id for rec in recs}),
                sample_error=sample,
            )
        )

    clusters.sort(key=lambda c: (-c.count, c.signature))
    return clusters


def per_candidate_failures(records: list[RunRecord], candidate: str) -> list[FailureCluster]:
    """Failure clusters for a single candidate only."""
    return cluster([rec for rec in records if rec.candidate == candidate])


def cluster_report_md(clusters: list[FailureCluster]) -> str:
    """Markdown 'why candidates lost' table.

    Columns: signature | count | candidates hit | example task. Rows follow the
    incoming cluster order (cluster() already ranks by occurrence count).
    """
    lines = [
        "### Why candidates lost",
        "",
        "| signature | count | candidates hit | example task |",
        "| --- | ---: | --- | --- |",
    ]
    if not clusters:
        lines.append("| _(no failures)_ | 0 |  |  |")
        return "\n".join(lines)

    for c in clusters:
        cands = ", ".join(c.candidates)
        example = c.task_ids[0] if c.task_ids else ""
        lines.append(f"| {c.signature} | {c.count} | {cands} | {example} |")
    return "\n".join(lines)


__all__ = [
    "AXES_THAT_MATTER",
    "dominant_weak_axis",
    "failure_signature",
    "FailureCluster",
    "cluster",
    "per_candidate_failures",
    "cluster_report_md",
]
