"""Tests for scrapler_eval.gates — pure stdlib unittest, no network, no deps.

Run: python3 -m unittest tests.test_gates -v
"""

import unittest

from scrapler_eval.interface import (
    AxisScores,
    ExtractResult,
    FetchResult,
    RunRecord,
    Tier,
)
from scrapler_eval.gates import (
    GATE_TYPES,
    BudgetGate,
    FieldPresenceGate,
    Gate,
    GateSet,
    MinQualityGate,
    NotBlockedGate,
    RetrievedContentGate,
    SearchRelevanceGate,
)


def make_record(
    *,
    candidate="cand",
    task_id="t0",
    tier=Tier.STATIC.value,
    axes=None,
    quality=0.0,
    fetch=None,
    extract=None,
):
    """Build a RunRecord by hand for a test."""
    return RunRecord(
        candidate=candidate,
        task_id=task_id,
        tier=tier,
        axes=axes if axes is not None else AxisScores(),
        quality=quality,
        fetch=fetch,
        extract=extract,
    )


class RetrievedContentGateTests(unittest.TestCase):
    def test_passes_with_enough_real_content(self):
        rec = make_record(fetch=FetchResult(ok=True, text="x" * 300))
        passed, reason = RetrievedContentGate(min_chars=200).check(rec)
        self.assertTrue(passed)
        self.assertIn("300", reason)

    def test_scratched_on_tier0_no_fetch(self):
        # Tier-0 "must retrieve real content or be scratched": no fetch at all.
        rec = make_record(fetch=None)
        passed, reason = RetrievedContentGate().check(rec)
        self.assertFalse(passed)
        self.assertIn("no fetch", reason)

    def test_fails_when_too_short(self):
        rec = make_record(fetch=FetchResult(ok=True, text="tiny"))
        passed, reason = RetrievedContentGate(min_chars=200).check(rec)
        self.assertFalse(passed)
        self.assertIn("min 200", reason)

    def test_fails_when_blocked_even_if_long(self):
        rec = make_record(fetch=FetchResult(ok=True, blocked=True, text="x" * 999))
        passed, reason = RetrievedContentGate().check(rec)
        self.assertFalse(passed)
        self.assertIn("blocked", reason)

    def test_falls_back_to_html_when_no_text(self):
        rec = make_record(fetch=FetchResult(ok=True, html="<p>" + "y" * 300 + "</p>"))
        passed, _ = RetrievedContentGate(min_chars=200).check(rec)
        self.assertTrue(passed)

    def test_fails_when_fetch_not_ok(self):
        rec = make_record(fetch=FetchResult(ok=False, error="timeout", text="x" * 500))
        passed, reason = RetrievedContentGate().check(rec)
        self.assertFalse(passed)
        self.assertIn("timeout", reason)


class NotBlockedGateTests(unittest.TestCase):
    def test_passes_when_not_blocked(self):
        rec = make_record(fetch=FetchResult(ok=True, blocked=False, text="ok"))
        passed, _ = NotBlockedGate().check(rec)
        self.assertTrue(passed)

    def test_fails_when_blocked(self):
        rec = make_record(fetch=FetchResult(ok=True, blocked=True))
        passed, reason = NotBlockedGate().check(rec)
        self.assertFalse(passed)
        self.assertIn("blocked", reason)

    def test_fails_with_no_fetch(self):
        passed, reason = NotBlockedGate().check(make_record(fetch=None))
        self.assertFalse(passed)


class MinQualityGateTests(unittest.TestCase):
    def test_passes_at_threshold(self):
        rec = make_record(quality=0.7)
        passed, _ = MinQualityGate(0.7).check(rec)
        self.assertTrue(passed)

    def test_fails_below_threshold(self):
        rec = make_record(quality=0.4)
        passed, reason = MinQualityGate(0.7).check(rec)
        self.assertFalse(passed)
        self.assertIn("0.400", reason)


class BudgetGateTests(unittest.TestCase):
    def test_passes_within_budget(self):
        rec = make_record(fetch=FetchResult(ok=True, latency_ms=1000, peak_rss_mb=500))
        passed, _ = BudgetGate(max_latency_ms=30000, max_rss_mb=4000).check(rec)
        self.assertTrue(passed)

    def test_budget_exceeded_latency(self):
        rec = make_record(fetch=FetchResult(ok=True, latency_ms=45000, peak_rss_mb=100))
        passed, reason = BudgetGate(max_latency_ms=30000, max_rss_mb=4000).check(rec)
        self.assertFalse(passed)
        self.assertIn("latency", reason)

    def test_budget_exceeded_rss(self):
        # WSL is memory-capped: blowing the RSS ceiling scratches the run.
        rec = make_record(fetch=FetchResult(ok=True, latency_ms=10, peak_rss_mb=8000))
        passed, reason = BudgetGate(max_latency_ms=30000, max_rss_mb=4000).check(rec)
        self.assertFalse(passed)
        self.assertIn("peak_rss", reason)

    def test_none_limits_disable_halves(self):
        rec = make_record(fetch=FetchResult(ok=True, latency_ms=1e9, peak_rss_mb=1e9))
        passed, _ = BudgetGate(max_latency_ms=None, max_rss_mb=None).check(rec)
        self.assertTrue(passed)


class FieldPresenceGateTests(unittest.TestCase):
    def test_passes_when_all_present(self):
        rec = make_record(extract=ExtractResult(fields={"title": "T", "price": 9}))
        passed, _ = FieldPresenceGate(["title", "price"]).check(rec)
        self.assertTrue(passed)

    def test_fails_when_missing_field(self):
        rec = make_record(extract=ExtractResult(fields={"title": "T"}))
        passed, reason = FieldPresenceGate(["title", "price"]).check(rec)
        self.assertFalse(passed)
        self.assertIn("price", reason)

    def test_fails_on_none_valued_field(self):
        rec = make_record(extract=ExtractResult(fields={"title": "T", "price": None}))
        passed, reason = FieldPresenceGate(["title", "price"]).check(rec)
        self.assertFalse(passed)
        self.assertIn("price", reason)

    def test_fails_with_no_extract(self):
        passed, reason = FieldPresenceGate(["title"]).check(make_record(extract=None))
        self.assertFalse(passed)
        self.assertIn("no extract", reason)


class SearchRelevanceGateTests(unittest.TestCase):
    def test_passes_via_relevance_axis(self):
        rec = make_record(axes=AxisScores(relevance=0.5))
        passed, _ = SearchRelevanceGate(min_hits=1).check(rec)
        self.assertTrue(passed)

    def test_passes_via_artifacts_hits(self):
        rec = make_record(fetch=FetchResult(ok=True, artifacts={"hits": 5}))
        passed, _ = SearchRelevanceGate(min_hits=3).check(rec)
        self.assertTrue(passed)

    def test_fails_no_relevant_hits(self):
        rec = make_record(axes=AxisScores(relevance=0.0))
        passed, reason = SearchRelevanceGate(min_hits=1).check(rec)
        self.assertFalse(passed)
        self.assertIn("0 relevant", reason)

    def test_fails_when_hits_below_min(self):
        rec = make_record(fetch=FetchResult(ok=True, artifacts={"hits": 1}))
        passed, _ = SearchRelevanceGate(min_hits=3).check(rec)
        self.assertFalse(passed)


class GateSetTests(unittest.TestCase):
    def test_check_all_passes_when_all_pass(self):
        rec = make_record(
            quality=0.9,
            fetch=FetchResult(ok=True, text="x" * 300, latency_ms=100, peak_rss_mb=200),
        )
        gs = GateSet([
            RetrievedContentGate(min_chars=200),
            NotBlockedGate(),
            MinQualityGate(0.5),
            BudgetGate(max_latency_ms=30000, max_rss_mb=4000),
        ])
        passed, reasons = gs.check_all(rec)
        self.assertTrue(passed)
        self.assertEqual(reasons, [])

    def test_check_all_aggregates_multiple_failures(self):
        rec = make_record(
            quality=0.1,
            fetch=FetchResult(ok=True, blocked=True, text="short",
                              latency_ms=99999, peak_rss_mb=99999),
        )
        gs = GateSet([
            RetrievedContentGate(min_chars=200),
            NotBlockedGate(),
            MinQualityGate(0.5),
            BudgetGate(max_latency_ms=30000, max_rss_mb=4000),
        ])
        passed, reasons = gs.check_all(rec)
        self.assertFalse(passed)
        # retrieved_content, not_blocked, min_quality, budget all fail
        self.assertEqual(len(reasons), 4)
        joined = " ".join(reasons)
        self.assertIn("retrieved_content:", joined)
        self.assertIn("not_blocked:", joined)
        self.assertIn("min_quality:", joined)
        self.assertIn("budget:", joined)

    def test_reasons_are_prefixed_with_gate_name(self):
        rec = make_record(quality=0.0)
        gs = GateSet([MinQualityGate(0.5)])
        _, reasons = gs.check_all(rec)
        self.assertEqual(len(reasons), 1)
        self.assertTrue(reasons[0].startswith("min_quality:"))

    def test_add_returns_self_and_appends(self):
        gs = GateSet()
        out = gs.add(NotBlockedGate())
        self.assertIs(out, gs)
        self.assertEqual(len(gs), 1)


class FromSpecTests(unittest.TestCase):
    def test_builds_gates_from_dict(self):
        spec = {
            "retrieved_content": {"min_chars": 200},
            "budget": {"max_latency_ms": 30000, "max_rss_mb": 4000},
        }
        gs = GateSet.from_spec(spec)
        self.assertEqual(len(gs), 2)
        types = {type(g) for g in gs.gates}
        self.assertEqual(types, {RetrievedContentGate, BudgetGate})

    def test_kwargs_are_applied(self):
        gs = GateSet.from_spec({"retrieved_content": {"min_chars": 512}})
        gate = gs.gates[0]
        self.assertIsInstance(gate, RetrievedContentGate)
        self.assertEqual(gate.min_chars, 512)

    def test_truthy_scalar_enables_default_gate(self):
        gs = GateSet.from_spec({"not_blocked": True})
        self.assertEqual(len(gs), 1)
        self.assertIsInstance(gs.gates[0], NotBlockedGate)

    def test_falsy_value_skips_gate(self):
        gs = GateSet.from_spec({"not_blocked": False, "min_quality": {"threshold": 0.5}})
        self.assertEqual(len(gs), 1)
        self.assertIsInstance(gs.gates[0], MinQualityGate)

    def test_unknown_gate_raises(self):
        with self.assertRaises(KeyError):
            GateSet.from_spec({"nope_gate": {}})

    def test_spec_roundtrips_to_working_gateset(self):
        spec = {
            "retrieved_content": {"min_chars": 100},
            "budget": {"max_latency_ms": 5000, "max_rss_mb": 1000},
        }
        gs = GateSet.from_spec(spec)
        good = make_record(fetch=FetchResult(ok=True, text="z" * 150,
                                             latency_ms=10, peak_rss_mb=10))
        bad = make_record(fetch=FetchResult(ok=True, text="z" * 150,
                                            latency_ms=99999, peak_rss_mb=10))
        self.assertTrue(gs.check_all(good)[0])
        self.assertFalse(gs.check_all(bad)[0])


class RegistryTests(unittest.TestCase):
    def test_registry_covers_all_concrete_gates(self):
        expected = {
            "retrieved_content", "not_blocked", "min_quality",
            "budget", "field_presence", "search_relevance",
        }
        self.assertEqual(set(GATE_TYPES), expected)

    def test_registry_values_are_gate_subclasses(self):
        for cls in GATE_TYPES.values():
            self.assertTrue(issubclass(cls, Gate))


if __name__ == "__main__":
    unittest.main()
