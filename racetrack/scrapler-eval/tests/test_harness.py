import unittest
from scrapler_eval.adapters import all_candidates, build
from scrapler_eval.adapters.baseline import RawFetch, JsonBlobExtract
from scrapler_eval.harness import run_bracket, run_one, render_result_md
from scrapler_eval.gates import GateSet
from scrapler_eval.ladder import load_ladder, load_config
from scrapler_eval.interface import Candidate, FetchResult, Task, Tier, WeightClass


class _Boom(Candidate):
    name = "boom"
    weight_class = WeightClass.FETCHER
    def available(self): return True
    def fetch(self, task): raise RuntimeError("kaboom")


class _Missing(Candidate):
    name = "missing-deps"
    weight_class = WeightClass.FETCHER
    requires = ["nonexistent"]
    def available(self): return False


def _fixed_ts():
    return 1785000000.0


class TestHarness(unittest.TestCase):
    def setUp(self):
        self.tasks = load_ladder()
        self.cfg = load_config()
        self.gate_spec = {"retrieved_content": {"min_chars": 100}}

    def test_end_to_end_produces_leaderboard(self):
        res = run_bracket(all_candidates(), self.tasks, self.gate_spec, self.cfg,
                          ts_fn=_fixed_ts)
        board = res["leaderboard"]
        self.assertTrue(board)
        # raw-fetch (class1, 3 tasks) should top the overall board on the fixtures
        self.assertEqual(board[0].candidate, "raw-fetch-baseline")
        self.assertGreater(board[0].normalized, 90.0)

    def test_extractor_beats_weak_extractor(self):
        res = run_bracket(all_candidates(), self.tasks, self.gate_spec, self.cfg,
                          ts_fn=_fixed_ts)
        cls4 = res["per_class"][4]
        names = [r.candidate for r in cls4]
        self.assertEqual(names[0], "json-blob-extractor")  # strong extractor wins its class

    def test_exception_is_recorded_not_raised(self):
        res = run_bracket([_Boom()], self.tasks, self.gate_spec, self.cfg, ts_fn=_fixed_ts)
        recs = res["records"]
        self.assertTrue(recs)
        self.assertTrue(all(not r.gate_passed for r in recs))
        self.assertTrue(any("exception" in (r.error or "") for r in recs))

    def test_unavailable_candidate_skipped_and_recorded(self):
        res = run_bracket([_Missing()], self.tasks, self.gate_spec, self.cfg, ts_fn=_fixed_ts)
        recs = res["records"]
        self.assertTrue(recs)
        self.assertTrue(all("unavailable" in (r.error or "") for r in recs))

    def test_task_routing_by_class(self):
        # raw-fetch (class1) runs only non-extractor tasks; json-blob runs only extractor tasks
        res = run_bracket([RawFetch(), JsonBlobExtract()], self.tasks, self.gate_spec,
                          self.cfg, ts_fn=_fixed_ts)
        by = {}
        for r in res["records"]:
            by.setdefault(r.candidate, set()).add(r.task_id)
        self.assertNotIn("x-product-fields", by["raw-fetch-baseline"])
        self.assertEqual(by["json-blob-extractor"], {"x-product-fields"})

    def test_gate_failure_shows_in_failure_clusters(self):
        res = run_bracket(all_candidates(), self.tasks, self.gate_spec, self.cfg, ts_fn=_fixed_ts)
        self.assertTrue(res["failure_clusters"])  # regex-article gets gated out

    def test_render_result_md_has_sections(self):
        res = run_bracket(all_candidates(), self.tasks, self.gate_spec, self.cfg, ts_fn=_fixed_ts)
        md = render_result_md(res, "t")
        self.assertIn("Overall leaderboard", md)
        self.assertIn("Why candidates lost", md)

    def test_events_emitted(self):
        seen = []
        run_bracket([RawFetch()], self.tasks, self.gate_spec, self.cfg,
                    on_event=lambda k, d: seen.append(k), ts_fn=_fixed_ts)
        self.assertIn("bracket_start", seen)
        self.assertIn("bracket_done", seen)

    def test_build_skips_unknown_names(self):
        cands = build(["raw-fetch-baseline", "does-not-exist"])
        self.assertEqual([c.name for c in cands], ["raw-fetch-baseline"])


if __name__ == "__main__":
    unittest.main()
