"""Tests for scrapler_eval.failure — signatures + clustering, stdlib unittest.

No network, no heavy deps. Builds RunRecords for every failure mode and asserts
signatures, cluster grouping/sorting, single-candidate slicing, clean-record
suppression, and the markdown 'why candidates lost' report.
"""

import unittest

from scrapler_eval.failure import (
    AXES_THAT_MATTER,
    cluster,
    cluster_report_md,
    dominant_weak_axis,
    failure_signature,
    per_candidate_failures,
    FailureCluster,
)
from scrapler_eval.interface import AxisScores, FetchResult, RunRecord


def mk(
    candidate="curl_imp",
    task_id="t0",
    tier="tier0_static",
    axes=None,
    quality=1.0,
    gate_passed=True,
    fetch=None,
    error="",
):
    """Build a RunRecord with sensible clean defaults."""
    return RunRecord(
        candidate=candidate,
        task_id=task_id,
        tier=tier,
        axes=axes if axes is not None else AxisScores(),
        quality=quality,
        gate_passed=gate_passed,
        fetch=fetch,
        error=error,
    )


class TestFailureSignature(unittest.TestCase):
    def test_error_signature_first_line_only(self):
        rec = mk(error="Timeout after 30s\nstack frame 1\nstack frame 2")
        self.assertEqual(failure_signature(rec), "error:Timeout after 30s")

    def test_error_takes_priority_over_everything(self):
        # blocked + fetch not ok + gate fail all present, but record error wins.
        rec = mk(
            error="boom",
            gate_passed=False,
            fetch=FetchResult(ok=False, blocked=True, status=403),
        )
        self.assertEqual(failure_signature(rec), "error:boom")

    def test_blocked_signature_carries_tier(self):
        rec = mk(tier="tier3_antibot", fetch=FetchResult(ok=False, blocked=True, status=403))
        self.assertEqual(failure_signature(rec), "blocked:tier=tier3_antibot")

    def test_blocked_takes_priority_over_fetch_fail(self):
        rec = mk(tier="tier1_dynamic", fetch=FetchResult(ok=False, blocked=True, status=503))
        self.assertEqual(failure_signature(rec), "blocked:tier=tier1_dynamic")

    def test_fetch_fail_signature_carries_status(self):
        rec = mk(fetch=FetchResult(ok=False, blocked=False, status=500))
        self.assertEqual(failure_signature(rec), "fetch_fail:status=500")

    def test_gate_fail_signature(self):
        rec = mk(fetch=FetchResult(ok=True, status=200), gate_passed=False)
        self.assertEqual(failure_signature(rec), "gate_fail")

    def test_low_quality_signature_uses_weakest_axis(self):
        axes = AxisScores(
            retrieval=0.9, completeness=0.8, evasion=0.2, field_accuracy=0.7, robustness=0.6
        )
        rec = mk(fetch=FetchResult(ok=True, status=200), quality=0.3, axes=axes)
        self.assertEqual(failure_signature(rec), "low_quality:evasion")

    def test_clean_record_has_no_signature(self):
        rec = mk(fetch=FetchResult(ok=True, status=200), quality=0.95)
        self.assertEqual(failure_signature(rec), "")

    def test_quality_exactly_half_is_not_low_quality(self):
        rec = mk(fetch=FetchResult(ok=True, status=200), quality=0.5)
        self.assertEqual(failure_signature(rec), "")


class TestDominantWeakAxis(unittest.TestCase):
    def test_picks_single_lowest(self):
        axes = AxisScores(retrieval=0.4, completeness=0.9, evasion=0.9, field_accuracy=0.9, robustness=0.9)
        self.assertEqual(dominant_weak_axis(axes), "retrieval")

    def test_tie_breaks_to_earlier_axis(self):
        # retrieval and evasion both 0.1; retrieval is earlier in AXES_THAT_MATTER.
        axes = AxisScores(retrieval=0.1, completeness=0.9, evasion=0.1, field_accuracy=0.9, robustness=0.9)
        self.assertEqual(dominant_weak_axis(axes), "retrieval")

    def test_ignores_search_and_footprint_axes(self):
        # relevance/recall/latency_norm/cost_norm are 0 but must NOT be picked.
        axes = AxisScores(
            retrieval=0.3, completeness=0.8, evasion=0.8, field_accuracy=0.8, robustness=0.8,
            relevance=0.0, recall=0.0, latency_norm=0.0, cost_norm=0.0,
        )
        self.assertEqual(dominant_weak_axis(axes), "retrieval")
        self.assertNotIn("relevance", AXES_THAT_MATTER)
        self.assertNotIn("latency_norm", AXES_THAT_MATTER)


class TestCluster(unittest.TestCase):
    def test_groups_shared_signature(self):
        recs = [
            mk(candidate="a", task_id="t1", fetch=FetchResult(ok=False, status=500)),
            mk(candidate="b", task_id="t2", fetch=FetchResult(ok=False, status=500)),
        ]
        clusters = cluster(recs)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].signature, "fetch_fail:status=500")
        self.assertEqual(clusters[0].count, 2)
        self.assertEqual(clusters[0].candidates, ["a", "b"])
        self.assertEqual(clusters[0].task_ids, ["t1", "t2"])

    def test_sorted_by_count_desc(self):
        recs = [
            # gate_fail x3
            mk(candidate="a", task_id="t1", fetch=FetchResult(ok=True, status=200), gate_passed=False),
            mk(candidate="b", task_id="t2", fetch=FetchResult(ok=True, status=200), gate_passed=False),
            mk(candidate="c", task_id="t3", fetch=FetchResult(ok=True, status=200), gate_passed=False),
            # error x1
            mk(candidate="a", task_id="t4", error="nope"),
        ]
        clusters = cluster(recs)
        self.assertEqual([c.signature for c in clusters], ["gate_fail", "error:nope"])
        self.assertEqual([c.count for c in clusters], [3, 1])

    def test_distinct_candidates_and_tasks(self):
        recs = [
            mk(candidate="a", task_id="t1", error="x"),
            mk(candidate="a", task_id="t1", error="x"),  # exact dup
            mk(candidate="a", task_id="t2", error="x"),
        ]
        clusters = cluster(recs)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].count, 3)          # counts every record
        self.assertEqual(clusters[0].candidates, ["a"])  # distinct
        self.assertEqual(clusters[0].task_ids, ["t1", "t2"])

    def test_clean_records_produce_no_cluster(self):
        recs = [
            mk(candidate="a", task_id="t1", fetch=FetchResult(ok=True, status=200), quality=0.9),
            mk(candidate="b", task_id="t2", fetch=FetchResult(ok=True, status=200), quality=0.8),
        ]
        self.assertEqual(cluster(recs), [])

    def test_mixed_clean_and_failing(self):
        recs = [
            mk(candidate="a", task_id="t1", fetch=FetchResult(ok=True, status=200), quality=0.9),
            mk(candidate="a", task_id="t2", error="crash"),
        ]
        clusters = cluster(recs)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].signature, "error:crash")

    def test_sample_error_captured_from_fetch(self):
        recs = [mk(candidate="a", task_id="t1", fetch=FetchResult(ok=False, status=502, error="bad gateway"))]
        clusters = cluster(recs)
        self.assertEqual(clusters[0].sample_error, "bad gateway")

    def test_all_five_failure_modes_cluster_separately(self):
        recs = [
            mk(candidate="a", task_id="e", error="boom"),
            mk(candidate="a", task_id="b", tier="tier3_antibot", fetch=FetchResult(ok=False, blocked=True)),
            mk(candidate="a", task_id="f", fetch=FetchResult(ok=False, status=404)),
            mk(candidate="a", task_id="g", fetch=FetchResult(ok=True, status=200), gate_passed=False),
            mk(
                candidate="a", task_id="q", fetch=FetchResult(ok=True, status=200), quality=0.2,
                axes=AxisScores(retrieval=0.1, completeness=0.9, evasion=0.9, field_accuracy=0.9, robustness=0.9),
            ),
        ]
        sigs = {c.signature for c in cluster(recs)}
        self.assertEqual(
            sigs,
            {
                "error:boom",
                "blocked:tier=tier3_antibot",
                "fetch_fail:status=404",
                "gate_fail",
                "low_quality:retrieval",
            },
        )


class TestPerCandidateFailures(unittest.TestCase):
    def test_filters_to_one_candidate(self):
        recs = [
            mk(candidate="a", task_id="t1", error="x"),
            mk(candidate="b", task_id="t2", error="y"),
            mk(candidate="a", task_id="t3", error="z"),
        ]
        clusters = per_candidate_failures(recs, "a")
        for c in clusters:
            self.assertEqual(c.candidates, ["a"])
        self.assertEqual({c.signature for c in clusters}, {"error:x", "error:z"})

    def test_absent_candidate_yields_nothing(self):
        recs = [mk(candidate="a", task_id="t1", error="x")]
        self.assertEqual(per_candidate_failures(recs, "ghost"), [])


class TestClusterReportMd(unittest.TestCase):
    def test_report_contains_top_signature_and_header(self):
        recs = [
            mk(candidate="a", task_id="t1", fetch=FetchResult(ok=True, status=200), gate_passed=False),
            mk(candidate="b", task_id="t2", fetch=FetchResult(ok=True, status=200), gate_passed=False),
            mk(candidate="a", task_id="t3", error="rare"),
        ]
        clusters = cluster(recs)
        md = cluster_report_md(clusters)
        self.assertIn("Why candidates lost", md)
        self.assertIn("gate_fail", md)          # top cluster (count 2)
        self.assertIn("| count |", md)
        # top signature row appears before the rarer one
        self.assertLess(md.index("gate_fail"), md.index("error:rare"))

    def test_report_lists_candidates_and_example_task(self):
        recs = [
            mk(candidate="cloakbrowser", task_id="task-9", fetch=FetchResult(ok=False, status=500)),
        ]
        md = cluster_report_md(cluster(recs))
        self.assertIn("cloakbrowser", md)
        self.assertIn("task-9", md)
        self.assertIn("fetch_fail:status=500", md)

    def test_empty_clusters_report(self):
        md = cluster_report_md([])
        self.assertIn("Why candidates lost", md)
        self.assertIn("no failures", md)

    def test_report_is_markdown_table(self):
        md = cluster_report_md([FailureCluster(signature="gate_fail", count=1, candidates=["a"], task_ids=["t1"])])
        # header + separator + one data row all pipe-delimited
        rows = [ln for ln in md.splitlines() if ln.startswith("|")]
        self.assertGreaterEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
