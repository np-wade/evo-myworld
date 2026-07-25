"""Scrapler Eval Harness — leaderboard: coverage -> normalized -> blended rank,
plus head-to-head arena Elo, per-class brackets, and a grand final.

Pure stdlib. No third-party imports (see CONTRACT.md hard rule 6).

Elo lineage — ported faithfully from lm-sys/FastChat's arena rating code:
  fastchat/serve/monitor/rating_systems.py::compute_elo
    alpha = log(base)/scale ; prob = 1/(1+exp(alpha*(rb-ra)))
    update = k*(outcome-prob) ; ra += update ; rb -= update
FastChat uses (log-)base=10, scale=400, init_rating=1000, k=4 with pandas
DataFrames of pairwise battles. We drop pandas for plain lists/dicts and keep
the identical sequential update, expressed in the equivalent 10**-form:
    expected = 1 / (1 + 10 ** ((rb - ra) / 400))
Here our public `base` argument is the *initial rating* (FastChat's init_rating),
and the logistic scale stays fixed at 400 (the conventional Elo scale).

Weight class: RunRecord has no weight_class field (interface.py is frozen), so
candidates stash it in AxisScores.extra["weight_class"] (a float 1..5). Absent =>
WeightClass.FETCHER (1). This keeps everything on the shared contract.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Optional

from .interface import AxisScores, LeaderRow, RunRecord, WeightClass

# Default blend weights (bracket yaml overrides in production).
DEFAULT_WEIGHTS: dict[str, float] = {
    "quality": 0.45,     # w1 * quality_mean
    "evasion": 0.30,     # w2 * evasion_mean
    "latency": 0.10,     # w3 * latency_pen  (subtracted)
    "cost": 0.05,        # w4 * cost_pen     (subtracted)
    "robustness": 0.10,  # w5 * robustness_mean
}

# Logistic scale for Elo (conventional 400). base/init_rating is a public arg.
_ELO_SCALE = 400.0

# The scalar axes we average (everything on AxisScores except the `extra` dict).
_AXIS_FIELDS: tuple[str, ...] = tuple(
    f.name for f in fields(AxisScores) if f.name != "extra"
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _weight_class(rec: RunRecord) -> int:
    """Weight class for a record, read from axes.extra (frozen-interface safe)."""
    try:
        return int(rec.axes.extra.get("weight_class", WeightClass.FETCHER))
    except (AttributeError, TypeError, ValueError):
        return int(WeightClass.FETCHER)


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _group_by_candidate(records: list[RunRecord]) -> dict[str, list[RunRecord]]:
    groups: dict[str, list[RunRecord]] = {}
    for rec in records:
        groups.setdefault(rec.candidate, []).append(rec)
    return groups


def _axis_means(recs: list[RunRecord]) -> dict[str, float]:
    means: dict[str, float] = {}
    for name in _AXIS_FIELDS:
        means[name] = _mean([float(getattr(r.axes, name)) for r in recs])
    return means


# --------------------------------------------------------------------------- #
# 1. rank
# --------------------------------------------------------------------------- #
def rank(
    records: list[RunRecord],
    weights: Optional[dict[str, float]] = None,
) -> list[LeaderRow]:
    """Group by candidate, compute coverage/normalized/blended leaderboard score,
    fill LeaderRow (incl. head-to-head elo), sort desc by blended leaderboard."""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    elos = arena_elo(records)
    rows: list[LeaderRow] = []

    for candidate, recs in _group_by_candidate(records).items():
        n = len(recs)
        coverage_total = sum(float(r.quality) for r in recs)
        normalized = 100.0 * coverage_total / n if n else 0.0
        gate_pass_rate = _mean([1.0 if r.gate_passed else 0.0 for r in recs])
        axis_means = _axis_means(recs)

        quality_mean = _mean([float(r.quality) for r in recs])
        evasion_mean = axis_means["evasion"]
        robustness_mean = axis_means["robustness"]
        latency_pen = 1.0 - axis_means["latency_norm"]  # higher norm => lower penalty
        cost_pen = 1.0 - axis_means["cost_norm"]

        leaderboard = (
            w["quality"] * quality_mean
            + w["evasion"] * evasion_mean
            - w["latency"] * latency_pen
            - w["cost"] * cost_pen
            + w["robustness"] * robustness_mean
        )

        rows.append(
            LeaderRow(
                candidate=candidate,
                weight_class=_weight_class(recs[0]),
                coverage_total=coverage_total,
                normalized=normalized,
                leaderboard=leaderboard,
                elo=elos.get(candidate, float(1000.0)),
                gate_pass_rate=gate_pass_rate,
                n_tasks=n,
                axis_means=axis_means,
            )
        )

    rows.sort(key=lambda r: (r.leaderboard, r.elo, r.candidate), reverse=True)
    return rows


# --------------------------------------------------------------------------- #
# 2. arena_elo
# --------------------------------------------------------------------------- #
def _build_battles(records: list[RunRecord]) -> list[tuple[str, str, str, float]]:
    """One battle per candidate pair on every task shared by >=2 candidates.
    Battle = (task_id, cand_a, cand_b, outcome) with cand_a < cand_b by name and
    outcome from cand_a's view: 1.0 win / 0.0 loss / 0.5 draw (equal quality)."""
    by_task: dict[str, dict[str, float]] = {}
    for rec in records:
        # first record for a (candidate, task) wins the slot; deterministic on input.
        by_task.setdefault(rec.task_id, {}).setdefault(rec.candidate, float(rec.quality))

    battles: list[tuple[str, str, str, float]] = []
    for task_id, quals in by_task.items():
        if len(quals) < 2:
            continue
        names = sorted(quals)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                qa, qb = quals[a], quals[b]
                outcome = 1.0 if qa > qb else (0.0 if qa < qb else 0.5)
                battles.append((task_id, a, b, outcome))

    battles.sort(key=lambda x: (x[0], x[1], x[2]))
    return battles


def arena_elo(
    records: list[RunRecord],
    k: float = 32.0,
    base: float = 1000.0,
) -> dict[str, float]:
    """Sequential Elo over head-to-head battles (ported from FastChat compute_elo).
    `base` is the initial rating; logistic scale fixed at 400."""
    battles = _build_battles(records)

    ratings: dict[str, float] = {}
    for _task, a, b, _o in battles:
        ratings.setdefault(a, float(base))
        ratings.setdefault(b, float(base))

    for _task, a, b, outcome in battles:
        ra, rb = ratings[a], ratings[b]
        expected_a = 1.0 / (1.0 + 10.0 ** ((rb - ra) / _ELO_SCALE))
        update = k * (outcome - expected_a)
        ratings[a] = ra + update
        ratings[b] = rb - update

    # Candidates that never battled still deserve a baseline rating.
    for rec in records:
        ratings.setdefault(rec.candidate, float(base))
    return ratings


# --------------------------------------------------------------------------- #
# 3. rank_by_class
# --------------------------------------------------------------------------- #
def rank_by_class(
    records: list[RunRecord],
    weights: Optional[dict[str, float]] = None,
) -> dict[int, list[LeaderRow]]:
    """Split records by weight_class and rank each class as its own leaderboard."""
    by_class: dict[int, list[RunRecord]] = {}
    for rec in records:
        by_class.setdefault(_weight_class(rec), []).append(rec)
    return {wc: rank(recs, weights) for wc, recs in sorted(by_class.items())}


# --------------------------------------------------------------------------- #
# 4. grand_final
# --------------------------------------------------------------------------- #
def grand_final(
    class_winners: dict[int, str],
    records: list[RunRecord],
    weights: Optional[dict[str, float]] = None,
) -> list[LeaderRow]:
    """Rank the per-class winners against each other on their overlap tasks.

    Overlap = task_ids present for every winner (a fair shared field). If the
    winners share no common task, fall back to all of their records."""
    winners = set(class_winners.values())
    winner_recs = [r for r in records if r.candidate in winners]
    if not winner_recs:
        return []

    # task_ids each winner actually ran
    tasks_per_winner: dict[str, set[str]] = {}
    for r in winner_recs:
        tasks_per_winner.setdefault(r.candidate, set()).add(r.task_id)

    overlap: Optional[set[str]] = None
    for tasks in tasks_per_winner.values():
        overlap = set(tasks) if overlap is None else (overlap & tasks)
    overlap = overlap or set()

    final_recs = [r for r in winner_recs if r.task_id in overlap] or winner_recs
    return rank(final_recs, weights)


# --------------------------------------------------------------------------- #
# 5. to_markdown
# --------------------------------------------------------------------------- #
def to_markdown(rows: list[LeaderRow], title: str) -> str:
    """Clean markdown table: candidate | class | normalized | leaderboard | elo |
    gate% | n. The top row (winner) is marked."""
    lines = [
        f"## {title}",
        "",
        "| # | candidate | class | normalized | leaderboard | elo | gate% | n |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows):
        marker = " 🏆" if i == 0 else ""
        rank_cell = "1" if i == 0 else str(i + 1)
        lines.append(
            f"| {rank_cell} | {r.candidate}{marker} | {r.weight_class} | "
            f"{r.normalized:.2f} | {r.leaderboard:.4f} | {r.elo:.1f} | "
            f"{100.0 * r.gate_pass_rate:.1f} | {r.n_tasks} |"
        )
    if not rows:
        lines.append("| — | (no candidates) | — | — | — | — | — | — |")
    return "\n".join(lines) + "\n"


__all__ = ["rank", "arena_elo", "rank_by_class", "grand_final", "to_markdown"]
