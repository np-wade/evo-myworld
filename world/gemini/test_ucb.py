import unittest
import math
import random
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

from evo import frontier_strategies as fs
from world.gemini.ucb import pick_ucb1

class TestUCB1FrontierStrategy(unittest.TestCase):
    def test_ucb1_mathematical_logic(self):
        # We test that exploration weight c shifts preference
        # from high-children/high-score to low-children/lower-score.
        nodes = [
            {"id": "exp_A", "score": 0.90, "eval_epoch": 1, "hypothesis": "A"},
            {"id": "exp_B", "score": 0.80, "eval_epoch": 1, "hypothesis": "B"},
        ]
        
        # We will mock repo_root and load_graph to avoid relying on actual workspace
        mock_graph = {
            "nodes": {
                "root": {"children": ["exp_A", "exp_B"]},
                # exp_A has 3 children
                "exp_A": {"children": ["exp_A1", "exp_A2", "exp_A3"]},
                # exp_B has 0 children
                "exp_B": {"children": []},
            }
        }
        
        # Total nodes N = 3 (root, exp_A, exp_B)
        # N - 1 = 2
        # If c = 0, exp_A must win (score 0.90 vs 0.80)
        # If c = 2.0, exp_B should win due to exploration bonus:
        # exp_A UCB = 0.90 + 2.0 * sqrt(ln(2) / 4) = 0.90 + 2.0 * sqrt(0.693 / 4) = 0.90 + 0.83 = 1.73
        # exp_B UCB = 0.80 + 2.0 * sqrt(ln(2) / 1) = 0.80 + 2.0 * sqrt(0.693) = 0.80 + 1.66 = 2.46
        
        with patch("evo.core.repo_root", return_value="/mock/root"), \
             patch("evo.core.load_graph", return_value=mock_graph):
            
            # Case 1: c = 0.0 (Exploitation only)
            out_exploit, _ = fs.pick(nodes, {"kind": "ucb1", "params": {"c": 0.0, "k": 1}}, "max", seed=42)
            self.assertEqual(out_exploit[0]["id"], "exp_A")
            
            # Case 2: c = 2.0 (Exploration favored)
            out_explore, _ = fs.pick(nodes, {"kind": "ucb1", "params": {"c": 2.0, "k": 1}}, "max", seed=42)
            self.assertEqual(out_explore[0]["id"], "exp_B")

    def test_min_metric_flips_direction(self):
        nodes = [
            {"id": "exp_A", "score": 10.0, "eval_epoch": 1, "hypothesis": "A"}, # lower is better, so B is better
            {"id": "exp_B", "score": 5.0, "eval_epoch": 1, "hypothesis": "B"},
        ]
        mock_graph = {
            "nodes": {
                "root": {"children": ["exp_A", "exp_B"]},
                "exp_A": {"children": []},
                "exp_B": {"children": []},
            }
        }
        with patch("evo.core.repo_root", return_value="/mock/root"), \
             patch("evo.core.load_graph", return_value=mock_graph):
            
            # With c=0, exp_B must win (since 5.0 is less than 10.0 under "min" metric)
            out, _ = fs.pick(nodes, {"kind": "ucb1", "params": {"c": 0.0, "k": 1}}, "min", seed=42)
            self.assertEqual(out[0]["id"], "exp_B")

    def test_k_limit(self):
        nodes = [
            {"id": "exp_A", "score": 0.90, "eval_epoch": 1},
            {"id": "exp_B", "score": 0.80, "eval_epoch": 1},
            {"id": "exp_C", "score": 0.70, "eval_epoch": 1},
        ]
        mock_graph = {
            "nodes": {
                "root": {}, "exp_A": {}, "exp_B": {}, "exp_C": {}
            }
        }
        with patch("evo.core.repo_root", return_value="/mock/root"), \
             patch("evo.core.load_graph", return_value=mock_graph):
            out, _ = fs.pick(nodes, {"kind": "ucb1", "params": {"c": 1.0, "k": 2}}, "max", seed=42)
            self.assertEqual(len(out), 2)

if __name__ == "__main__":
    unittest.main()
