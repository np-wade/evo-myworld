"""Mission DAG tests: durable recursive intent without a second scheduler."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evo.cli import build_parser, cmd_agent
from evo.core import graph_path, init_workspace, load_json
from evo.missions import (
    add_evidence,
    cancel_mission,
    claim_mission,
    create_mission,
    finish_mission,
    list_missions,
)


class MissionDagTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Evo Test"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "baseline"], cwd=self.root, check=True)
        init_workspace(self.root, target="bench.py", benchmark="python bench.py", metric="max", gate=None)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_dependencies_unlock_and_claims_are_atomic(self) -> None:
        research = create_mission(self.root, title="Map prior art", kind="research", brief="Read bounded source evidence.")
        build = create_mission(
            self.root, title="Implement winner", kind="build", brief="Implement only a proven approach.",
            depends_on=[research["id"]],
        )
        self.assertEqual(research["status"], "ready")
        self.assertEqual(build["status"], "planned")
        claim_mission(self.root, research["id"], owner_exp_id="exp_0001")
        finish_mission(self.root, research["id"], status="succeeded", summary="Two candidates compared.")
        ready = {mission["id"]: mission for mission in list_missions(self.root, status="ready")}
        self.assertIn(build["id"], ready)
        claimed = claim_mission(self.root, build["id"], owner_exp_id="exp_0002")
        self.assertEqual(claimed["status"], "running")
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            claim_mission(self.root, build["id"], owner_exp_id="exp_0003")

    def test_child_cap_cancellation_and_evidence(self) -> None:
        root = create_mission(
            self.root, title="Control plane", kind="integrate", brief="Wire durable controls.",
            max_depth=2, max_children=1,
        )
        child = create_mission(
            self.root, title="Verify controls", kind="verify", brief="Exercise lifecycle transitions.",
            parent_id=root["id"], max_depth=2, max_children=99,
        )
        with self.assertRaisesRegex(RuntimeError, "max_children=1"):
            create_mission(
                self.root, title="Too many", kind="build", brief="Should fail.",
                parent_id=root["id"], max_depth=2,
            )
        evidence = add_evidence(
            self.root, child["id"], uri="graphify://slice/example", sha256="a" * 64,
            summary="Bounded source range reviewed.",
        )
        self.assertEqual(evidence["sha256"], "a" * 64)
        self.assertEqual(cancel_mission(self.root, root["id"]), [root["id"], child["id"]])
        states = {mission["id"]: mission["status"] for mission in list_missions(self.root)}
        self.assertEqual(states[root["id"]], "cancelled")
        self.assertEqual(states[child["id"]], "cancelled")

    def test_blocked_mission_recovers_to_ready_when_dependency_succeeds(self) -> None:
        research = create_mission(self.root, title="Study", kind="research", brief="Read evidence.")
        build = create_mission(
            self.root, title="Build winner", kind="build", brief="Implement a proven approach.",
            depends_on=[research["id"]],
        )
        self.assertEqual(build["status"], "planned")
        # Agent parks the dependent mission as recoverable-blocked while it waits.
        blocked = finish_mission(self.root, build["id"], status="blocked", summary="Waiting on research.")
        self.assertEqual(blocked["status"], "blocked")
        # Dependency has not succeeded yet, so it must remain blocked (not terminal).
        current = {m["id"]: m["status"] for m in list_missions(self.root)}
        self.assertEqual(current[build["id"]], "blocked")
        # Complete the dependency; the blocked mission should return to ready and be claimable.
        claim_mission(self.root, research["id"], owner_exp_id="exp_0001")
        finish_mission(self.root, research["id"], status="succeeded", summary="Winner chosen.")
        ready = {m["id"]: m for m in list_missions(self.root, status="ready")}
        self.assertIn(build["id"], ready)
        claimed = claim_mission(self.root, build["id"], owner_exp_id="exp_0002")
        self.assertEqual(claimed["status"], "running")

    def test_blocked_mission_with_unsatisfied_deps_stays_blocked(self) -> None:
        research = create_mission(self.root, title="Study", kind="research", brief="Read evidence.")
        build = create_mission(
            self.root, title="Build winner", kind="build", brief="Implement a proven approach.",
            depends_on=[research["id"]],
        )
        finish_mission(self.root, build["id"], status="blocked", summary="Waiting on research.")
        # Multiple refreshes with the dependency still unfinished must not unblock it.
        for _ in range(3):
            states = {m["id"]: m["status"] for m in list_missions(self.root)}
            self.assertEqual(states[build["id"]], "blocked")
        # And it must never be claimable while blocked.
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            claim_mission(self.root, build["id"], owner_exp_id="exp_0009")

    def test_mutation_on_fresh_workspace_keeps_valid_graph_structure(self) -> None:
        with tempfile.TemporaryDirectory() as fresh:
            fresh_root = Path(fresh)
            # No init_workspace: graph.json does not exist yet.
            create_mission(fresh_root, title="Kickoff", kind="research", brief="Seed the DAG.")
            graph = load_json(graph_path(fresh_root), {})
            # A subsequent core graph reader indexes graph["nodes"]["root"] directly.
            self.assertIn("nodes", graph)
            self.assertIn("root", graph["nodes"])
            self.assertEqual(graph["nodes"]["root"]["id"], "root")
            self.assertEqual(graph.get("root"), "root")
            self.assertIn("missions", graph)

    def test_agent_aliases_delegate_to_one_canonical_lifecycle(self) -> None:
        parser = build_parser()
        start = parser.parse_args([
            "agent", "start", "--parent", "root", "-m", "Run the ready mission", "--background",
        ])
        with patch("evo.cli.cmd_dispatch", return_value=0) as dispatch:
            self.assertEqual(cmd_agent(start), 0)
            self.assertEqual(dispatch.call_args.args[0].dispatch_action, "run")
            self.assertEqual(dispatch.call_args.args[0].message, "Run the ready mission")
        steer = parser.parse_args(["agent", "steer", "--exp-id", "exp_0001", "Read", "the", "evidence"])
        with patch("evo.cli.cmd_direct", return_value=0) as direct:
            self.assertEqual(cmd_agent(steer), 0)
            self.assertEqual(direct.call_args.args[0].args, ["exp_0001", "Read", "the", "evidence"])


if __name__ == "__main__":
    unittest.main()
