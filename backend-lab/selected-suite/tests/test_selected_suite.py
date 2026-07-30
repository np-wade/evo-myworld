import importlib.util
import sys
import unittest
from pathlib import Path


SUITE_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("selected_suite", SUITE_ROOT / "run.py")
suite = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = suite
SPEC.loader.exec_module(suite)


class SelectedSuiteTests(unittest.TestCase):
    def assert_scored_race_has_gate(self, results):
        scored = [result for result in results if result.status == "scored"]
        self.assertGreaterEqual(len(scored), 2)
        self.assertTrue(any(result.gate for result in scored))
        self.assertTrue(all(result.score is not None for result in scored))

    def test_contract_race(self):
        results = suite.race_contract()
        self.assert_scored_race_has_gate(results)
        self.assertTrue(all(r.gate for r in results if r.status == "scored"))

    def test_lifecycle_race(self):
        results = suite.race_lifecycle()
        self.assert_scored_race_has_gate(results)
        by_name = {result.candidate: result for result in results}
        self.assertTrue(by_name["evo-mission-dag"].metrics["cancel_cascade"])
        self.assertTrue(by_name["witt-spine-lanes"].metrics["failure_propagation"])

    def test_identity_trace_race(self):
        results = suite.race_identity_trace()
        self.assert_scored_race_has_gate(results)
        self.assertTrue(all(r.metrics["trace_join_rate"] == 1.0 for r in results if r.status == "scored"))

    def test_routing_exposes_collision_failure(self):
        results = suite.race_routing()
        by_name = {result.candidate: result for result in results}
        self.assertFalse(by_name["hardcoded-ports"].gate)
        self.assertFalse(by_name["prefix-front-door"].gate)
        self.assertTrue(by_name["health-registry-router"].gate)

    def test_hybrid_recall_race(self):
        results = suite.race_hybrid()
        self.assert_scored_race_has_gate(results)
        hybrid = next(result for result in results if result.candidate == "rrf-hybrid")
        self.assertTrue(hybrid.metrics["keyword_gate"])
        self.assertTrue(hybrid.metrics["semantic_gate"])
        vector = next(result for result in results if result.candidate == "vector-only")
        self.assertFalse(vector.metrics["keyword_gate"])

    def test_graph_race_exactness(self):
        results = suite.race_graph()
        self.assertTrue(all(result.gate for result in results if result.status == "scored"))

    def test_self_improvement_has_heldout_gate(self):
        results = suite.race_self_improvement()
        self.assert_scored_race_has_gate(results)
        self.assertTrue(all(result.metrics["unsafe_promotions_blocked"] > 0 for result in results if result.status == "scored"))
        self.assertTrue(all(not result.metrics["weight_updates"] for result in results if result.status == "scored"))
        by_name = {result.candidate: result for result in results}
        self.assertFalse(by_name["argmax"].gate)
        self.assertTrue(by_name["evo-pareto"].gate)


if __name__ == "__main__":
    unittest.main()
