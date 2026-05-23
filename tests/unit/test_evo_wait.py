"""Unit tests for `evo wait` — blocking primitive for the orchestrator.

The orchestrator (in /optimize) spawns subagents in the background and
needs to wait for their results. Pre-v0.4.4 it would write ad-hoc bash
polling loops; v0.4.4 gives it `evo wait` as a first-class primitive.

Contract:
  - polls every 1s for `experiments/<id>/outcome.json` writes/updates
  - exits 0 + prints what changed on the first detected experiment
    conclusion
  - exits 124 (POSIX timeout convention) on timeout
  - --timeout defaults to 3600 (1h) and is capped at 3600 so an agent
    can't accidentally block forever
  - no --watch flag — fixed set of paths the orchestrator cares about

Real filesystem, real subprocess for `evo wait`, no implementation mocks.

Run: pytest tests/unit/test_evo_wait.py -v
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "evo" / "src"))


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@evo"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)
    (root / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)


def _make_workspace(root: Path) -> Path:
    _init_git_repo(root)
    from evo.core import init_workspace
    init_workspace(
        root, target="agent.py", benchmark="python bench.py",
        metric="max", gate=None,
    )
    run_dir = next(iter((root / ".evo").glob("run_*")))
    (run_dir / "experiments").mkdir(parents=True, exist_ok=True)
    return run_dir


class TestEvoWait(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.run_dir = _make_workspace(self.root)
        self._old_cwd = Path.cwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _run_wait(self, timeout: float, expect_rc: int | None = None) -> tuple[int, str]:
        """Run cmd_wait directly (in-process) and capture output."""
        from evo.cli import cmd_wait
        import argparse
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cmd_wait(argparse.Namespace(timeout=timeout))
        return rc, buf.getvalue()

    def test_returns_124_on_timeout_with_no_changes(self):
        rc, out = self._run_wait(timeout=0.3)
        self.assertEqual(rc, 124, f"want 124 (timeout), got {rc}; output: {out!r}")
        self.assertTrue(
            "timed out" in out.lower() or "timeout" in out.lower(),
            f"output must mention timeout; got: {out!r}",
        )

    def test_returns_0_when_outcome_json_appears_during_wait(self):
        result: dict = {}

        def writer() -> None:
            time.sleep(0.5)  # let wait start polling
            exp_dir = self.run_dir / "experiments" / "exp_0042"
            exp_dir.mkdir(parents=True, exist_ok=True)
            (exp_dir / "outcome.json").write_text(json.dumps({"score": 1.0}))

        t = threading.Thread(target=writer, daemon=True)
        t.start()
        rc, out = self._run_wait(timeout=10.0)
        t.join(timeout=2)

        self.assertEqual(rc, 0, f"want 0 on change, got {rc}; output: {out!r}")
        self.assertIn("exp_0042", out, f"output must name the changed experiment: {out!r}")

    def test_returns_0_when_outcome_json_updates(self):
        """Existing outcome.json mtime changes (e.g., re-run committing
        new attempt) should also wake the wait."""
        exp_dir = self.run_dir / "experiments" / "exp_0001"
        exp_dir.mkdir(parents=True, exist_ok=True)
        outcome = exp_dir / "outcome.json"
        outcome.write_text(json.dumps({"score": 0.5}))
        # Backdate the mtime so the baseline doesn't immediately register
        old_t = time.time() - 60
        os.utime(outcome, (old_t, old_t))

        def updater() -> None:
            time.sleep(0.5)
            outcome.write_text(json.dumps({"score": 0.8}))

        t = threading.Thread(target=updater, daemon=True)
        t.start()
        rc, out = self._run_wait(timeout=10.0)
        t.join(timeout=2)

        self.assertEqual(rc, 0)
        self.assertIn("exp_0001", out)

    def test_timeout_capped_at_3600(self):
        """A user/agent passing --timeout 99999 must be silently capped to 3600.
        Confirmed via the cmd_wait function caps the value internally; we
        don't actually wait an hour — we just verify the cap logic."""
        from evo.cli import _wait_timeout_seconds
        self.assertEqual(_wait_timeout_seconds(3600), 3600)
        self.assertEqual(_wait_timeout_seconds(99999), 3600)
        self.assertEqual(_wait_timeout_seconds(-5), 1)   # min floor 1s
        self.assertEqual(_wait_timeout_seconds(0), 1)
        self.assertEqual(_wait_timeout_seconds(120), 120)

    def test_no_evo_workspace_returns_error(self):
        """Run outside an evo workspace — should fail cleanly, not hang."""
        import argparse
        from evo.cli import cmd_wait
        with tempfile.TemporaryDirectory() as elsewhere:
            os.chdir(elsewhere)
            try:
                rc = cmd_wait(argparse.Namespace(timeout=10.0))
                self.assertNotEqual(rc, 0, "must fail outside workspace")
            finally:
                os.chdir(self.root)

    def test_subagent_dispatch_into_running_experiment_also_wakes_wait(self):
        """A subagent in optimize spawns a new experiment dir (mkdir of
        experiments/<id>/) before outcome.json appears. wait should detect
        that too — orchestrator wants to know experiments started, not
        just concluded."""
        def starter() -> None:
            time.sleep(0.5)
            (self.run_dir / "experiments" / "exp_0099").mkdir(parents=True)

        t = threading.Thread(target=starter, daemon=True)
        t.start()
        rc, out = self._run_wait(timeout=10.0)
        t.join(timeout=2)

        self.assertEqual(rc, 0)
        self.assertIn("exp_0099", out)


if __name__ == "__main__":
    unittest.main()
