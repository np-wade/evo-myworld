"""Tests for scrapler_eval.leaderboard — pure stdlib unittest, no network,
no heavy deps. RunRecords are built by hand with known qualities so every
assertion is hand-computable."""

from __future__ import annotations

import unittest

from scrapler_eval.interface import AxisScores, RunRecord, WeightClass
from scrapler_eval.leaderboard import (
    DEFAULT_WEIGHTS,
    arena_elo,
    grand_final,
    rank,
    rank_by_class,
    to_markdown,
)


def mk(
    candidate: str,
    task_id: str,
    quality: float,
    *,
    weight_class: int = int(WeightClass.FETCHER),
    evasion: float = 0.0,
    latency_norm: float = 0.0,
    cost_norm: float = 0.0,
    robustness: float = 0.0,
    gate_passed: bool = True,
) -> RunRecord:
    axes = AxisScores(
        evasion=evasion,
        latency_norm=latency_norm,
        cost_norm=cost_norm,
        robustness=robustness,
        extra={"weight_class": float(weight_class)},
    )
    return RunRecord(
        candidate=candidate,
        task_id=task_id,
        tier="tier0_static",
        axes=axes,
        quality=quality,
        gate_passed=gate_passed,
    )


class TestCoverageMath(unittest.TestCase):
    def test_coverage_total_is_sum_of_quality(self):
        recs = [mk("A", "t1", 0.5), mk("A", "t2", 0.25), mk("A", "t3", 1.0)]
        row = rank(recs)[0]
        self.assertAlmostEqual(row.coverage_total, 1.75)

    def test_normalized_is_100x_coverage_over_n(self):
        recs = [mk("A", "t1", 0.5), mk("A", "t2", 0.5), mk("A", "t3", 0.5), mk("A", "t4", 0.5)]
        row = rank(recs)[0]
        # coverage=2.0, n=4 -> 100*2/4 = 50.0
        self.assertAlmostEqual(row.coverage_total, 2.0)
        self.assertEqual(row.n_tasks, 4)
        self.assertAlmostEqual(row.normalized, 50.0)

    def test_gate_pass_rate(self):
        recs = [
            mk("A", "t1", 1.0, gate_passed=True),
            mk("A", "t2", 1.0, gate_passed=True),
            mk("A", "t3", 1.0, gate_passed=False),
            mk("A", "t4", 1.0, gate_passed=False),
        ]
        row = rank(recs)[0]
        self.assertAlmostEqual(row.gate_pass_rate, 0.5)


class TestRankOrder(unittest.TestCase):
    def _two_candidates(self):
        # A dominates B on every task.
        return [
            mk("A", "t1", 1.0), mk("A", "t2", 1.0), mk("A", "t3", 1.0),
            mk("B", "t1", 0.1), mk("B", "t2", 0.1), mk("B", "t3", 0.1),
        ]

    def test_rank_order_best_first(self):
        rows = rank(self._two_candidates())
        self.assertEqual([r.candidate for r in rows], ["A", "B"])
        self.assertGreater(rows[0].leaderboard, rows[1].leaderboard)

    def test_axis_means_averaged(self):
        recs = [
            mk("A", "t1", 1.0, evasion=1.0, robustness=0.4),
            mk("A", "t2", 1.0, evasion=0.0, robustness=0.6),
        ]
        row = rank(recs)[0]
        self.assertAlmostEqual(row.axis_means["evasion"], 0.5)
        self.assertAlmostEqual(row.axis_means["robustness"], 0.5)

    def test_blended_score_exact(self):
        # Single record with clean axes so we can hand-compute the blend.
        recs = [mk("A", "t1", 0.8, evasion=0.6, latency_norm=0.9,
                   cost_norm=0.7, robustness=0.5)]
        row = rank(recs)[0]
        w = DEFAULT_WEIGHTS
        expected = (
            w["quality"] * 0.8
            + w["evasion"] * 0.6
            - w["latency"] * (1.0 - 0.9)
            - w["cost"] * (1.0 - 0.7)
            + w["robustness"] * 0.5
        )
        self.assertAlmostEqual(row.leaderboard, expected)

    def test_custom_weights_override(self):
        recs = [mk("A", "t1", 1.0, evasion=0.0, latency_norm=1.0,
                   cost_norm=1.0, robustness=0.0)]
        # Only quality counts; penalties zeroed by latency/cost norm = 1.
        row = rank(recs, weights={"quality": 1.0, "evasion": 0.0,
                                  "latency": 0.0, "cost": 0.0, "robustness": 0.0})[0]
        self.assertAlmostEqual(row.leaderboard, 1.0)


class TestArenaElo(unittest.TestCase):
    def test_one_battle_winner_up_loser_down(self):
        # A beats B on one shared task; both start at base=1000, k=32.
        # expected_A = 1/(1+10^0) = 0.5 ; update = 32*(1-0.5) = 16.
        recs = [mk("A", "t1", 1.0), mk("B", "t1", 0.0)]
        elos = arena_elo(recs, k=32.0, base=1000.0)
        self.assertAlmostEqual(elos["A"], 1016.0)
        self.assertAlmostEqual(elos["B"], 984.0)

    def test_draw_no_change(self):
        recs = [mk("A", "t1", 0.5), mk("B", "t1", 0.5)]
        elos = arena_elo(recs, k=32.0, base=1000.0)
        self.assertAlmostEqual(elos["A"], 1000.0)
        self.assertAlmostEqual(elos["B"], 1000.0)

    def test_no_shared_task_stays_at_base(self):
        recs = [mk("A", "t1", 1.0), mk("B", "t2", 1.0)]
        elos = arena_elo(recs, k=32.0, base=1000.0)
        self.assertAlmostEqual(elos["A"], 1000.0)
        self.assertAlmostEqual(elos["B"], 1000.0)

    def test_custom_base_rating(self):
        recs = [mk("A", "t1", 1.0), mk("B", "t1", 0.0)]
        elos = arena_elo(recs, k=32.0, base=1500.0)
        self.assertAlmostEqual(elos["A"], 1516.0)
        self.assertAlmostEqual(elos["B"], 1484.0)

    def test_second_battle_uses_updated_ratings(self):
        # A beats B twice on t1,t2. After first battle A=1016,B=984.
        # Second: exp_A = 1/(1+10^((984-1016)/400)) = 1/(1+10^-0.08).
        recs = [
            mk("A", "t1", 1.0), mk("B", "t1", 0.0),
            mk("A", "t2", 1.0), mk("B", "t2", 0.0),
        ]
        elos = arena_elo(recs, k=32.0, base=1000.0)
        exp_a2 = 1.0 / (1.0 + 10.0 ** ((984.0 - 1016.0) / 400.0))
        a_final = 1016.0 + 32.0 * (1.0 - exp_a2)
        self.assertAlmostEqual(elos["A"], a_final)
        self.assertAlmostEqual(elos["B"], 2000.0 - a_final)

    def test_rank_fills_elo_into_rows(self):
        recs = [mk("A", "t1", 1.0), mk("B", "t1", 0.0)]
        rows = rank(recs)
        by = {r.candidate: r for r in rows}
        self.assertAlmostEqual(by["A"].elo, 1016.0)
        self.assertAlmostEqual(by["B"].elo, 984.0)


class TestRankByClass(unittest.TestCase):
    def test_split_by_weight_class(self):
        recs = [
            mk("Fetcher1", "t1", 0.9, weight_class=int(WeightClass.FETCHER)),
            mk("Fetcher2", "t1", 0.5, weight_class=int(WeightClass.FETCHER)),
            mk("Browser1", "t1", 0.8, weight_class=int(WeightClass.BROWSER)),
        ]
        by_class = rank_by_class(recs)
        self.assertIn(int(WeightClass.FETCHER), by_class)
        self.assertIn(int(WeightClass.BROWSER), by_class)
        self.assertEqual(len(by_class[int(WeightClass.FETCHER)]), 2)
        self.assertEqual(len(by_class[int(WeightClass.BROWSER)]), 1)

    def test_per_class_order_independent(self):
        recs = [
            mk("F_lo", "t1", 0.1, weight_class=1),
            mk("F_hi", "t1", 0.9, weight_class=1),
            mk("B_only", "t1", 0.5, weight_class=2),
        ]
        by_class = rank_by_class(recs)
        fetchers = [r.candidate for r in by_class[1]]
        self.assertEqual(fetchers, ["F_hi", "F_lo"])

    def test_weight_class_recorded_on_row(self):
        recs = [mk("B1", "t1", 0.5, weight_class=int(WeightClass.BROWSER))]
        row = rank(recs)[0]
        self.assertEqual(row.weight_class, int(WeightClass.BROWSER))


class TestGrandFinal(unittest.TestCase):
    def test_grand_final_ranks_winners_on_overlap(self):
        recs = [
            # class 1 winner
            mk("W1", "shared", 0.9, weight_class=1),
            mk("W1", "w1only", 0.9, weight_class=1),
            # class 2 winner
            mk("W2", "shared", 0.3, weight_class=2),
            mk("W2", "w2only", 0.3, weight_class=2),
            # a non-winner should be excluded
            mk("Loser", "shared", 1.0, weight_class=1),
        ]
        rows = grand_final({1: "W1", 2: "W2"}, recs)
        names = [r.candidate for r in rows]
        self.assertEqual(names, ["W1", "W2"])
        self.assertNotIn("Loser", names)
        # ranked only on the shared task -> each has n_tasks == 1
        self.assertTrue(all(r.n_tasks == 1 for r in rows))

    def test_grand_final_fallback_when_no_overlap(self):
        recs = [
            mk("W1", "t1", 0.9, weight_class=1),
            mk("W2", "t2", 0.3, weight_class=2),
        ]
        rows = grand_final({1: "W1", 2: "W2"}, recs)
        self.assertEqual({r.candidate for r in rows}, {"W1", "W2"})

    def test_grand_final_empty_winners(self):
        self.assertEqual(grand_final({}, []), [])


class TestToMarkdown(unittest.TestCase):
    def test_markdown_contains_winner_and_header(self):
        recs = [
            mk("A", "t1", 1.0), mk("A", "t2", 1.0),
            mk("B", "t1", 0.1), mk("B", "t2", 0.1),
        ]
        md = to_markdown(rank(recs), "Fetcher class")
        self.assertIn("Fetcher class", md)
        self.assertIn("candidate", md)
        self.assertIn("🏆", md)
        # winner (A) marked, appears before B
        self.assertIn("A", md)
        self.assertLess(md.index("A"), md.index("| 2 |"))

    def test_markdown_empty_rows(self):
        md = to_markdown([], "Empty")
        self.assertIn("no candidates", md)


if __name__ == "__main__":
    unittest.main()
