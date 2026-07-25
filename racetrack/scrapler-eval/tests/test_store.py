"""Tests for scrapler_eval.store — pure stdlib, no network, no heavy deps.

Covers: JSONL run log round-trip, RunRecord<->dict nested-dataclass round-trip,
content-addressed cache key stability/sensitivity, cache miss->put->hit with the
anti-cheat reuse marker, hit/miss stats, and ScoreHistory time-series ordering.
"""

import tempfile
import unittest
from pathlib import Path

from scrapler_eval.interface import (
    AxisScores,
    ExtractResult,
    FetchResult,
    RunRecord,
)
from scrapler_eval.store import (
    ResultCache,
    RunStore,
    ScoreHistory,
    canonical_json,
    dict_to_record,
    record_to_dict,
)


def _make_record(candidate="curl-impersonate", task_id="t0", quality=0.8, ts=100.0):
    return RunRecord(
        candidate=candidate,
        task_id=task_id,
        tier="tier0_static",
        axes=AxisScores(retrieval=1.0, completeness=0.9, evasion=0.5,
                        field_accuracy=0.7, extra={"custom": 0.3}),
        quality=quality,
        gate_passed=True,
        fetch=FetchResult(ok=True, status=200, latency_ms=12.5, bytes_down=2048),
        extract=ExtractResult(fields={"title": "hello"}, text="body", ok=True),
        ts=ts,
    )


class TestSerialization(unittest.TestCase):
    def test_canonical_json_is_order_independent(self):
        a = canonical_json({"b": 1, "a": 2})
        b = canonical_json({"a": 2, "b": 1})
        self.assertEqual(a, b)

    def test_record_to_dict_flattens_nested(self):
        d = record_to_dict(_make_record())
        self.assertIsInstance(d["axes"], dict)
        self.assertIsInstance(d["fetch"], dict)
        self.assertIsInstance(d["extract"], dict)
        self.assertEqual(d["axes"]["retrieval"], 1.0)
        self.assertEqual(d["axes"]["extra"]["custom"], 0.3)

    def test_roundtrip_preserves_nested_axes(self):
        rec = _make_record()
        back = dict_to_record(record_to_dict(rec))
        self.assertEqual(back.candidate, rec.candidate)
        self.assertEqual(back.axes.retrieval, 1.0)
        self.assertEqual(back.axes.completeness, 0.9)
        self.assertEqual(back.axes.field_accuracy, 0.7)
        self.assertEqual(back.axes.extra, {"custom": 0.3})
        self.assertIsInstance(back.axes, AxisScores)
        self.assertIsInstance(back.fetch, FetchResult)
        self.assertEqual(back.fetch.status, 200)
        self.assertIsInstance(back.extract, ExtractResult)
        self.assertEqual(back.extract.fields, {"title": "hello"})

    def test_roundtrip_handles_missing_fetch_extract(self):
        rec = RunRecord(candidate="c", task_id="t", tier="tier0_static",
                        axes=AxisScores(), ts=1.0)
        back = dict_to_record(record_to_dict(rec))
        self.assertIsNone(back.fetch)
        self.assertIsNone(back.extract)
        self.assertIsInstance(back.axes, AxisScores)

    def test_dict_to_record_strips_cache_marker(self):
        d = record_to_dict(_make_record())
        d["_cache"] = "hit"
        back = dict_to_record(d)  # must not choke on the bookkeeping field
        self.assertEqual(back.candidate, "curl-impersonate")


class TestRunStore(unittest.TestCase):
    def test_record_history_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            store = RunStore(root)
            store.record(_make_record(candidate="A", task_id="t0", ts=1.0))
            store.record(_make_record(candidate="B", task_id="t0", ts=2.0))
            store.record(_make_record(candidate="A", task_id="t1", ts=3.0))
            hist = store.history("A")
            self.assertEqual(len(hist), 2)
            self.assertEqual([h["task_id"] for h in hist], ["t0", "t1"])
            self.assertEqual(hist[0]["axes"]["retrieval"], 1.0)

    def test_all_records_in_write_order(self):
        with tempfile.TemporaryDirectory() as root:
            store = RunStore(root)
            for i, ts in enumerate([5.0, 1.0, 3.0]):
                store.record(_make_record(task_id=f"t{i}", ts=ts))
            recs = store.all_records()
            self.assertEqual([r["ts"] for r in recs], [5.0, 1.0, 3.0])

    def test_empty_store_returns_empty(self):
        with tempfile.TemporaryDirectory() as root:
            store = RunStore(root)
            self.assertEqual(store.all_records(), [])
            self.assertEqual(store.history("nobody"), [])

    def test_history_full_record_reconstructs(self):
        with tempfile.TemporaryDirectory() as root:
            store = RunStore(root)
            rec = _make_record(candidate="Z", ts=9.0)
            store.record(rec)
            back = dict_to_record(store.history("Z")[0])
            self.assertEqual(back.axes.extra, {"custom": 0.3})
            self.assertEqual(back.fetch.bytes_down, 2048)


class TestResultCache(unittest.TestCase):
    def test_key_is_stable(self):
        with tempfile.TemporaryDirectory() as root:
            cache = ResultCache(root)
            k1 = cache.key("cand", "t0", {"headless": True, "timeout": 30})
            k2 = cache.key("cand", "t0", {"timeout": 30, "headless": True})
            self.assertEqual(k1, k2)  # cfg key order must not matter

    def test_key_is_config_sensitive(self):
        with tempfile.TemporaryDirectory() as root:
            cache = ResultCache(root)
            base = cache.key("cand", "t0", {"timeout": 30})
            self.assertNotEqual(base, cache.key("cand", "t0", {"timeout": 31}))
            self.assertNotEqual(base, cache.key("cand", "t1", {"timeout": 30}))
            self.assertNotEqual(base, cache.key("other", "t0", {"timeout": 30}))

    def test_miss_then_put_then_hit_marks_reuse(self):
        with tempfile.TemporaryDirectory() as root:
            cache = ResultCache(root)
            key = cache.key("cand", "t0", {"a": 1})
            self.assertIsNone(cache.get(key))  # miss
            rec = record_to_dict(_make_record())
            cache.put(key, rec)
            hit = cache.get(key)
            self.assertIsNotNone(hit)
            self.assertEqual(hit["_cache"], "hit")  # anti-cheat marker
            self.assertEqual(hit["candidate"], "curl-impersonate")

    def test_put_strips_marker_from_stored_file(self):
        with tempfile.TemporaryDirectory() as root:
            cache = ResultCache(root)
            key = cache.key("cand", "t0", {"a": 1})
            rec = record_to_dict(_make_record())
            rec["_cache"] = "hit"  # a poisoned/reused record
            cache.put(key, rec)
            path = Path(root) / "cache" / f"{key}.json"
            import json
            stored = json.loads(path.read_text())
            self.assertNotIn("_cache", stored)  # file is a fresh record

    def test_stats_counts_hits_and_misses(self):
        with tempfile.TemporaryDirectory() as root:
            cache = ResultCache(root)
            key = cache.key("cand", "t0", {"a": 1})
            cache.get(key)          # miss
            cache.get(key)          # miss
            cache.put(key, record_to_dict(_make_record()))
            cache.get(key)          # hit
            self.assertEqual(cache.stats(), {"hits": 1, "misses": 2})

    def test_cache_persists_across_instances(self):
        with tempfile.TemporaryDirectory() as root:
            key = ResultCache(root).key("cand", "t0", {"a": 1})
            ResultCache(root).put(key, record_to_dict(_make_record()))
            hit = ResultCache(root).get(key)
            self.assertIsNotNone(hit)
            self.assertEqual(hit["_cache"], "hit")


class TestScoreHistory(unittest.TestCase):
    def test_series_is_sorted_by_ts(self):
        with tempfile.TemporaryDirectory() as root:
            sh = ScoreHistory(root)
            sh.append("A", "quality", 0.5, ts=30.0)
            sh.append("A", "quality", 0.7, ts=10.0)
            sh.append("A", "quality", 0.6, ts=20.0)
            series = sh.series("A", "quality")
            self.assertEqual(series, [(10.0, 0.7), (20.0, 0.6), (30.0, 0.5)])

    def test_series_filters_candidate_and_metric(self):
        with tempfile.TemporaryDirectory() as root:
            sh = ScoreHistory(root)
            sh.append("A", "quality", 0.5, ts=1.0)
            sh.append("A", "evasion", 0.9, ts=1.0)
            sh.append("B", "quality", 0.1, ts=1.0)
            self.assertEqual(sh.series("A", "quality"), [(1.0, 0.5)])

    def test_latest_returns_value_at_max_ts(self):
        with tempfile.TemporaryDirectory() as root:
            sh = ScoreHistory(root)
            sh.append("A", "quality", 0.5, ts=30.0)
            sh.append("A", "quality", 0.9, ts=99.0)
            sh.append("A", "quality", 0.6, ts=20.0)
            self.assertEqual(sh.latest("A", "quality"), 0.9)

    def test_latest_none_when_empty(self):
        with tempfile.TemporaryDirectory() as root:
            sh = ScoreHistory(root)
            self.assertIsNone(sh.latest("nobody", "quality"))


if __name__ == "__main__":
    unittest.main()
