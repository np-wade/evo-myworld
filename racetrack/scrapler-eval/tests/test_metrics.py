"""Unit tests for scrapler_eval.metrics — stdlib unittest, no network/deps.

IR primitives are checked against a hand-worked example whose precision,
recall, AP, MRR and nDCG values are computed on paper in the docstrings below.
"""

from __future__ import annotations

import unittest

from scrapler_eval.interface import (
    AxisScores,
    ExtractResult,
    FetchResult,
    Task,
    Tier,
    WeightClass,
)
from scrapler_eval import metrics as m


def _fetch(**kw) -> FetchResult:
    """Build a FetchResult with sensible defaults, overridable by kwargs."""
    base = dict(ok=True, text="", blocked=False)
    base.update(kw)
    return FetchResult(**base)


def _task(**kw) -> Task:
    """Build a frozen-tier Task with an answer_key, overridable by kwargs."""
    base = dict(id="t1", tier=Tier.STATIC, url="file:///x")
    base.update(kw)
    return Task(**base)


class TestRetrieval(unittest.TestCase):
    """retrieval_score: real content vs block/empty."""

    def test_clean_fetch_is_one(self):
        """A non-blocked ok fetch above threshold scores 1.0."""
        f = _fetch(text="x" * 500)
        self.assertEqual(m.retrieval_score(f, threshold=200), 1.0)

    def test_blocked_is_zero(self):
        """A blocked fetch scores 0.0 regardless of text."""
        f = _fetch(text="x" * 500, blocked=True)
        self.assertEqual(m.retrieval_score(f), 0.0)

    def test_empty_is_zero(self):
        """An ok fetch with no text scores 0.0."""
        self.assertEqual(m.retrieval_score(_fetch(text="")), 0.0)

    def test_graded_below_threshold(self):
        """Between empty and threshold the score grades linearly."""
        f = _fetch(text="x" * 50)
        self.assertAlmostEqual(m.retrieval_score(f, threshold=200), 0.25, places=6)

    def test_not_ok_is_zero(self):
        """A failed fetch (ok=False) scores 0.0."""
        self.assertEqual(m.retrieval_score(_fetch(ok=False, text="x" * 500)), 0.0)


class TestCompleteness(unittest.TestCase):
    """completeness_score: captured / expected precedence."""

    def test_expected_chars(self):
        """expected_chars: len(text)/expected, capped at 1.0."""
        f = _fetch(text="x" * 150)
        t = _task(answer_key={"expected_chars": 300})
        self.assertAlmostEqual(m.completeness_score(f, t), 0.5, places=6)

    def test_expected_chars_capped(self):
        """Overshooting expected_chars caps at 1.0."""
        f = _fetch(text="x" * 600)
        t = _task(answer_key={"expected_chars": 300})
        self.assertEqual(m.completeness_score(f, t), 1.0)

    def test_expected_blocks_from_artifacts(self):
        """expected_blocks divides captured blocks (from artifacts)."""
        f = _fetch(artifacts={"blocks": [1, 2, 3]})
        t = _task(answer_key={"expected_blocks": 6})
        self.assertAlmostEqual(m.completeness_score(f, t), 0.5, places=6)

    def test_expected_blocks_from_text(self):
        """With no blocks artifact, paragraphs in text are counted."""
        f = _fetch(text="para one\n\npara two\n\n  \n\npara three")
        t = _task(answer_key={"expected_blocks": 3})
        self.assertEqual(m.completeness_score(f, t), 1.0)

    def test_must_contain_fraction(self):
        """must_contain: fraction of required substrings present."""
        f = _fetch(text="alpha gamma")
        t = _task(answer_key={"must_contain": ["alpha", "beta", "gamma", "delta"]})
        self.assertAlmostEqual(m.completeness_score(f, t), 0.5, places=6)

    def test_no_key_is_zero(self):
        """No usable answer key -> cannot judge completeness -> 0.0."""
        self.assertEqual(m.completeness_score(_fetch(text="hi"), _task()), 0.0)


class TestEvasion(unittest.TestCase):
    """evasion_score: detector pass fraction / block heuristic."""

    def test_detector_pass_float(self):
        """A float detector_pass fraction passes through clamped."""
        f = _fetch(artifacts={"detector_pass": 0.75})
        self.assertEqual(m.evasion_score(f), 0.75)

    def test_detector_pass_list(self):
        """A list of pass/fail booleans is averaged."""
        f = _fetch(artifacts={"detector_pass": [True, True, False, False]})
        self.assertEqual(m.evasion_score(f), 0.5)

    def test_blocked_no_detector_is_zero(self):
        """No detector signal + blocked -> 0.0."""
        self.assertEqual(m.evasion_score(_fetch(blocked=True)), 0.0)

    def test_clean_no_detector_is_one(self):
        """No detector signal + clean ok fetch -> 1.0."""
        self.assertEqual(m.evasion_score(_fetch(ok=True)), 1.0)


class TestLatencyCost(unittest.TestCase):
    """latency_norm and cost_norm inverted normalization + guards."""

    def test_latency_norm_basic(self):
        """(max - latency)/(max - min): 200 in [100,500] -> 0.75."""
        self.assertAlmostEqual(m.latency_norm(200, 100, 500), 0.75, places=6)

    def test_latency_norm_divzero_guard(self):
        """max == min (no spread) ties everyone at 1.0."""
        self.assertEqual(m.latency_norm(200, 300, 300), 1.0)

    def test_latency_norm_clamps_slowest(self):
        """Latency above max clamps to 0.0."""
        self.assertEqual(m.latency_norm(900, 100, 500), 0.0)

    def test_cost_norm_basic(self):
        """footprint 100 (bytes only) vs max 200 -> 1 - 0.5 = 0.5."""
        f = _fetch(bytes_down=100, llm_tokens=0, peak_rss_mb=0)
        self.assertAlmostEqual(m.cost_norm(f, 200), 0.5, places=6)

    def test_cost_norm_footprint_components(self):
        """footprint = bytes + tokens*4 + rss*1e6."""
        f = _fetch(bytes_down=0, llm_tokens=25, peak_rss_mb=0)  # 100
        self.assertAlmostEqual(m.cost_norm(f, 200), 0.5, places=6)

    def test_cost_norm_divzero_guard(self):
        """Non-positive field_max_cost -> 1.0 (no measurable spread)."""
        self.assertEqual(m.cost_norm(_fetch(bytes_down=10), 0), 1.0)


class TestRobustness(unittest.TestCase):
    """robustness_score: 1 - population stddev, clamped."""

    def test_perfect_consistency(self):
        """Identical qualities -> stddev 0 -> 1.0."""
        self.assertAlmostEqual(m.robustness_score([0.8, 0.8, 0.8]), 1.0, places=9)

    def test_variance_lowers_score(self):
        """[0.0, 1.0] has population stddev 0.5 -> 0.5."""
        self.assertAlmostEqual(m.robustness_score([0.0, 1.0]), 0.5, places=6)

    def test_empty_guard(self):
        """Empty / single-sample input has no variance -> 1.0."""
        self.assertEqual(m.robustness_score([]), 1.0)
        self.assertEqual(m.robustness_score([0.3]), 1.0)


class TestFieldAccuracy(unittest.TestCase):
    """field_accuracy: normalized field match fraction."""

    def test_all_match_normalized(self):
        """Case/whitespace-insensitive full match -> 1.0."""
        t = _task(answer_key={"fields": {"title": "Hello World", "price": "9.99"}})
        e = ExtractResult(fields={"title": "hello   world", "price": "9.99"})
        self.assertEqual(m.field_accuracy(e, t), 1.0)

    def test_partial_match(self):
        """One of two fields correct -> 0.5."""
        t = _task(answer_key={"fields": {"a": "1", "b": "2"}})
        e = ExtractResult(fields={"a": "1", "b": "wrong"})
        self.assertAlmostEqual(m.field_accuracy(e, t), 0.5, places=6)

    def test_missing_field_counts_wrong(self):
        """A missing field is not a hit."""
        t = _task(answer_key={"fields": {"a": "1", "b": "2"}})
        e = ExtractResult(fields={"a": "1"})
        self.assertAlmostEqual(m.field_accuracy(e, t), 0.5, places=6)

    def test_collection_field_uses_set_overlap(self):
        """A collection-valued field matches on full IoU-style overlap."""
        t = _task(answer_key={"fields": {"tags": ["x", "y"]}})
        e = ExtractResult(fields={"tags": ["y", "x"]})
        self.assertEqual(m.field_accuracy(e, t), 1.0)

    def test_no_fields_guard(self):
        """No expected fields -> 0.0 (divide-by-zero guard)."""
        self.assertEqual(m.field_accuracy(ExtractResult(), _task()), 0.0)


class TestIRPrimitives(unittest.TestCase):
    """Worked example (ranked ids, relevance) with hand-computed values.

    ranked    = [d1, d2, d3, d4, d5]
    relevant  = {d1, d3, d5}   (R = 3)
      P@3  = |{d1,d3}| / 3               = 2/3   = 0.6667
      P@5  = |{d1,d3,d5}| / 5            = 3/5   = 0.6
      recall (all retrieved)             = 3/3   = 1.0
      AP   = (1/1 + 2/3 + 3/5) / 3       = 2.2667/3 = 0.7556
      MRR  (first hit at rank 1)         = 1/1   = 1.0
    """

    RANKED = ["d1", "d2", "d3", "d4", "d5"]
    RELEVANT = {"d1", "d3", "d5"}

    def test_precision_at_k(self):
        """P@3 = 0.6667, P@5 = 0.6."""
        self.assertAlmostEqual(m.precision_at_k(self.RANKED, self.RELEVANT, 3),
                               0.6667, places=4)
        self.assertAlmostEqual(m.precision_at_k(self.RANKED, self.RELEVANT, 5),
                               0.6, places=6)

    def test_precision_at_k_zero_guard(self):
        """k <= 0 or empty ranking -> 0.0."""
        self.assertEqual(m.precision_at_k(self.RANKED, self.RELEVANT, 0), 0.0)
        self.assertEqual(m.precision_at_k([], self.RELEVANT, 3), 0.0)

    def test_recall_full_and_partial(self):
        """Full retrieval -> 1.0; partial -> 1/3; no relevant -> 0.0."""
        self.assertEqual(m.recall(self.RANKED, self.RELEVANT), 1.0)
        self.assertAlmostEqual(m.recall(["d1", "d2"], self.RELEVANT),
                               1.0 / 3.0, places=6)
        self.assertEqual(m.recall(self.RANKED, set()), 0.0)

    def test_average_precision(self):
        """AP over the worked example = 0.7556."""
        self.assertAlmostEqual(
            m.average_precision(self.RANKED, self.RELEVANT), 0.7556, places=4
        )

    def test_average_precision_empty_guard(self):
        """Empty ranking or no relevant items -> 0.0."""
        self.assertEqual(m.average_precision([], self.RELEVANT), 0.0)
        self.assertEqual(m.average_precision(self.RANKED, set()), 0.0)

    def test_mrr(self):
        """First relevant at rank 1 -> 1.0; at rank 3 -> 1/3; none -> 0.0."""
        self.assertEqual(m.mrr(self.RANKED, self.RELEVANT), 1.0)
        self.assertAlmostEqual(
            m.mrr(["d2", "d4", "d3"], {"d3", "d5"}), 1.0 / 3.0, places=6
        )
        self.assertEqual(m.mrr(["d2", "d4"], {"d9"}), 0.0)

    def test_ndcg(self):
        """nDCG worked example.

        ranked = [d1,d2,d3,d4], rel = {d1:3, d2:2, d3:3, d4:0}
          DCG  = 3/log2(2) + 2/log2(3) + 3/log2(4) + 0 = 5.76186
          IDCG = 3/log2(2) + 3/log2(3) + 2/log2(4) + 0 = 5.89279
          nDCG = 5.76186 / 5.89279 = 0.9778
        """
        ranked = ["d1", "d2", "d3", "d4"]
        rel = {"d1": 3, "d2": 2, "d3": 3, "d4": 0}
        self.assertAlmostEqual(m.ndcg_at_k(ranked, rel, 4), 0.9778, places=4)

    def test_ndcg_perfect_order_is_one(self):
        """Already-ideal ordering scores exactly 1.0."""
        ranked = ["a", "b", "c"]
        rel = {"a": 3, "b": 2, "c": 1}
        self.assertAlmostEqual(m.ndcg_at_k(ranked, rel, 3), 1.0, places=9)

    def test_ndcg_empty_guards(self):
        """k <= 0, empty ranking, or all-zero relevance -> 0.0."""
        self.assertEqual(m.ndcg_at_k([], {"a": 1}, 3), 0.0)
        self.assertEqual(m.ndcg_at_k(["a"], {"a": 1}, 0), 0.0)
        self.assertEqual(m.ndcg_at_k(["a"], {"a": 0}, 3), 0.0)


class TestHelpers(unittest.TestCase):
    """Ported pure-math primitives: precision, f1, set_overlap."""

    def test_precision_and_guard(self):
        """precision = TP/(TP+FP); zero predictions -> 0.0."""
        self.assertAlmostEqual(m.precision(3, 1), 0.75, places=6)
        self.assertEqual(m.precision(0, 0), 0.0)

    def test_f1_harmonic_mean(self):
        """F1 = 2PR/(P+R); both zero -> 0.0."""
        self.assertAlmostEqual(m.f1(0.5, 1.0), 2 / 3, places=6)
        self.assertEqual(m.f1(0.0, 0.0), 0.0)

    def test_set_overlap(self):
        """Jaccard/IoU set overlap on token strings + empty edge case."""
        self.assertAlmostEqual(m.set_overlap("a b c", "b c d"), 0.5, places=6)
        self.assertEqual(m.set_overlap("", ""), 1.0)
        self.assertEqual(m.set_overlap("a", "b"), 0.0)


class TestItemQuality(unittest.TestCase):
    """item_quality blends per weight class."""

    def test_scraper_blend(self):
        """Class 1-3: 0.4R + 0.3C + 0.2E + 0.1Rob."""
        axes = AxisScores(retrieval=0.5, completeness=1.0, evasion=0.0,
                          robustness=1.0)
        # 0.2 + 0.3 + 0.0 + 0.1 = 0.6
        self.assertAlmostEqual(
            m.item_quality(axes, WeightClass.FETCHER), 0.6, places=6
        )
        self.assertAlmostEqual(
            m.item_quality(axes, WeightClass.ENGINE), 0.6, places=6
        )

    def test_extractor_blend(self):
        """Class 4: 0.7 * field_accuracy + 0.3 * completeness."""
        axes = AxisScores(field_accuracy=1.0, completeness=0.5)
        # 0.7 + 0.15 = 0.85
        self.assertAlmostEqual(
            m.item_quality(axes, WeightClass.EXTRACTOR), 0.85, places=6
        )

    def test_search_blend(self):
        """Class 5: 0.5 rel + 0.3 recall + 0.1 fresh + 0.1 selfhost."""
        axes = AxisScores(relevance=0.8, recall=0.5, freshness=1.0, selfhost=1.0)
        # 0.4 + 0.15 + 0.1 + 0.1 = 0.75
        self.assertAlmostEqual(
            m.item_quality(axes, WeightClass.SEARCH), 0.75, places=6
        )

    def test_clamped_to_unit(self):
        """A blend can never exceed 1.0."""
        axes = AxisScores(retrieval=1.0, completeness=1.0, evasion=1.0,
                          robustness=1.0)
        self.assertAlmostEqual(m.item_quality(axes, 1), 1.0, places=9)


class TestScoreCompose(unittest.TestCase):
    """score() fills AxisScores by delegating to every axis scorer."""

    def test_scraping_task(self):
        """A frozen scraping task fills scraping axes; search axes stay 0."""
        f = _fetch(text="x" * 300, bytes_down=100, latency_ms=200)
        t = _task(answer_key={"expected_chars": 300,
                              "fields": {"title": "hi"}})
        e = ExtractResult(fields={"title": "hi"})
        stats = {"latency_min_ms": 100, "latency_max_ms": 500,
                 "cost_max": 200, "qualities": [0.9, 0.9]}
        axes = m.score(f, e, t, stats)
        self.assertEqual(axes.retrieval, 1.0)
        self.assertEqual(axes.completeness, 1.0)
        self.assertEqual(axes.evasion, 1.0)
        self.assertAlmostEqual(axes.latency_norm, 0.75, places=6)
        self.assertAlmostEqual(axes.cost_norm, 0.5, places=6)
        self.assertEqual(axes.robustness, 1.0)
        self.assertEqual(axes.field_accuracy, 1.0)
        self.assertEqual(axes.relevance, 0.0)  # not a search task

    def test_search_task_fills_search_axes(self):
        """A task with 'relevant' fills relevance/recall from ranked artifacts."""
        f = _fetch(text="results", artifacts={
            "ranked": ["d1", "d2", "d3"], "freshness": 0.9, "selfhost": 1.0})
        t = _task(query="q", answer_key={"relevant": ["d1", "d3"], "k": 3})
        axes = m.score(f, None, t, {})
        self.assertAlmostEqual(axes.relevance, 2.0 / 3.0, places=6)
        self.assertEqual(axes.recall, 1.0)
        self.assertEqual(axes.freshness, 0.9)
        self.assertEqual(axes.selfhost, 1.0)

    def test_none_extract_field_accuracy_zero(self):
        """No extractor result -> field_accuracy stays 0.0."""
        axes = m.score(_fetch(text="x" * 300), None, _task(), {})
        self.assertEqual(axes.field_accuracy, 0.0)


if __name__ == "__main__":
    unittest.main()
