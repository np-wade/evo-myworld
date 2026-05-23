"""Tests for the stop-hook self-continuation nudge.

When the orchestrator (in /optimize) emits a `Stop` (or `SubagentStop`)
event, the drain injects a `{"decision": "block", "reason": ...}`
envelope that re-prompts the agent to keep going — using `evo wait` to
block on subagent results or continuing to plan the next round.

Loop guard: progress-gated. If two consecutive Stop fires happen with
no new experiment committed since the previous nudge, suppress the
second nudge so the agent can actually stop (it's genuinely done or
stuck and shouldn't be force-looped forever).

No mocks of real impls. Tests drive `drain_session` directly with
synthesized payloads + real on-disk state.

Run: pytest tests/unit/test_stop_nudge.py -v
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "evo" / "src"))

from evo.inject import queue
from evo.inject.paths import session_file
from evo.inject.registry import register_session, mark_engaged, mark_optimize_mode


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


def _drain_stop(root: Path, sid: str, host: str = "claude-code",
                hook_event: str = "Stop") -> dict:
    """Drive drain_session with a Stop event; return the parsed emitted JSON."""
    from evo.inject.drain import drain_session
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        drain_session(root, sid, host=host, hook_event=hook_event)
    out = buf.getvalue().strip()
    return json.loads(out) if out else {}


class _Base(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.run_dir = _make_workspace(self.root)

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# Positive: orchestrator + optimize_mode + Stop → block with continuation
# ---------------------------------------------------------------------------

class TestStopNudgeFires(_Base):

    def test_orchestrator_in_optimize_mode_is_nudged_on_stop(self):
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")

        out = _drain_stop(self.root, "orch", hook_event="Stop")
        self.assertEqual(out.get("decision"), "block",
                         f"Stop nudge must emit decision:block; got {out!r}")
        reason = out.get("reason") or ""
        self.assertIn("optimize", reason.lower(),
                      f"reason must mention optimize protocol; got {reason!r}")
        self.assertIn("evo wait", reason.lower(),
                      f"reason must mention evo wait as the wait primitive")

    def test_orchestrator_in_optimize_mode_is_nudged_on_subagent_stop(self):
        """SubagentStop on the orchestrator session (when its Task subagent
        ends) should also keep the orchestrator going."""
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")

        out = _drain_stop(self.root, "orch", hook_event="SubagentStop")
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("optimize", (out.get("reason") or "").lower())

    def test_codex_orchestrator_also_nudged(self):
        register_session(self.root, "cdx", "codex")
        mark_engaged(self.root, "cdx")
        mark_optimize_mode(self.root, "cdx")
        out = _drain_stop(self.root, "cdx", host="codex", hook_event="Stop")
        self.assertEqual(out.get("decision"), "block")


# ---------------------------------------------------------------------------
# Negative: don't nudge in cases where we shouldn't
# ---------------------------------------------------------------------------

class TestStopNudgeDoesNotFire(_Base):

    def test_non_optimize_mode_session_not_nudged(self):
        register_session(self.root, "other", "claude-code")
        mark_engaged(self.root, "other")
        # optimize_mode NOT set
        out = _drain_stop(self.root, "other", hook_event="Stop")
        # Existing engagement-only Stop emits empty additionalContext envelope
        # (no events queued). Must NOT be a decision:block.
        self.assertNotEqual(out.get("decision"), "block",
                            "non-optimize-mode session must not be force-continued")

    def test_subagent_not_nudged(self):
        """Subagents must NOT be force-continued. They have their own
        bounded scope; the orchestrator owns the loop."""
        register_session(self.root, "sub", "claude-code", exp_id="exp_0042")
        mark_engaged(self.root, "sub")
        # Even if optimize_mode somehow got flipped on a subagent record,
        # the stop-nudge check should exclude subagents via exp_id presence.
        out = _drain_stop(self.root, "sub", hook_event="SubagentStop")
        self.assertNotEqual(out.get("decision"), "block",
                            "subagent must not be force-continued")

    def test_pre_tool_use_event_not_treated_as_stop(self):
        """The stop-nudge should ONLY fire on Stop/SubagentStop. A PreToolUse
        on the same session must emit the normal envelope (or nothing)."""
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")
        out = _drain_stop(self.root, "orch", hook_event="PreToolUse")
        self.assertNotEqual(out.get("decision"), "block",
                            "PreToolUse must not trigger stop-nudge")


# ---------------------------------------------------------------------------
# Progress-gated loop guard
# ---------------------------------------------------------------------------

class TestStopNudgeLoopGuard(_Base):

    def _commit_experiment(self, exp_id: str) -> None:
        """Simulate a subagent committing an experiment (creates the dir,
        which is the signal stop-nudge progress-tracks)."""
        (self.run_dir / "experiments" / exp_id).mkdir(parents=True, exist_ok=True)
        (self.run_dir / "experiments" / exp_id / "outcome.json").write_text(
            json.dumps({"score": 1.0})
        )

    def test_two_consecutive_stops_without_progress_does_NOT_nudge_twice(self):
        """First Stop fires nudge. If next Stop fires with no new
        experiment since, the second one must NOT nudge — the agent
        is genuinely done or stuck."""
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")

        first = _drain_stop(self.root, "orch", hook_event="Stop")
        self.assertEqual(first.get("decision"), "block", "first Stop nudges")

        # No experiment committed between the two stops
        second = _drain_stop(self.root, "orch", hook_event="Stop")
        self.assertNotEqual(
            second.get("decision"), "block",
            "second consecutive Stop without progress must not nudge — "
            "agent must be allowed to actually stop"
        )

    def test_progress_between_stops_unblocks_nudge_again(self):
        """First Stop nudges. After progress (experiment committed), the
        next Stop nudges again (the loop continues working)."""
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")

        first = _drain_stop(self.root, "orch", hook_event="Stop")
        self.assertEqual(first.get("decision"), "block")

        # Subagent commits an experiment — progress!
        self._commit_experiment("exp_0001")

        second = _drain_stop(self.root, "orch", hook_event="Stop")
        self.assertEqual(
            second.get("decision"), "block",
            "Stop after progress must nudge again — the loop is working"
        )

    def test_three_stops_progress_progress_no_progress(self):
        """Realistic sequence: stop → progress → stop → progress → stop
        (no progress). Third stop must not nudge."""
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")

        out1 = _drain_stop(self.root, "orch", hook_event="Stop")
        self.assertEqual(out1.get("decision"), "block")

        self._commit_experiment("exp_0001")

        out2 = _drain_stop(self.root, "orch", hook_event="Stop")
        self.assertEqual(out2.get("decision"), "block")

        # No new progress this time
        out3 = _drain_stop(self.root, "orch", hook_event="Stop")
        self.assertNotEqual(out3.get("decision"), "block",
                            "third stop without progress must let agent stop")


# ---------------------------------------------------------------------------
# Reason content: autonomous-driving language
# ---------------------------------------------------------------------------

class TestStopNudgeReasonContent(_Base):

    def test_reason_says_dont_ask_user(self):
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")
        out = _drain_stop(self.root, "orch", hook_event="Stop")
        reason = (out.get("reason") or "").lower()
        # Mention autonomy / not asking the user
        self.assertTrue(
            "autonom" in reason or "user" in reason,
            f"reason should signal autonomous driving; got: {reason!r}"
        )

    def test_reason_mentions_evo_wait(self):
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")
        out = _drain_stop(self.root, "orch", hook_event="Stop")
        self.assertIn("evo wait", (out.get("reason") or "").lower())


if __name__ == "__main__":
    unittest.main()
