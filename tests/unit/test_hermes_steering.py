"""Tests for the hermes steering port.

Hermes hook contract (verified against hermes-agent 0.10's
`hermes_cli/plugins.py#VALID_HOOKS`):
  - `pre_tool_call` — observer-only; return value ignored.
  - `pre_llm_call` — can return `{"context": "..."}` to inject context.
  - `post_tool_call` — observer-only.

No mid-turn delivery is possible (no hook with a mutable model-input
return value during the tool-calling loop). The port:
  - `pre_tool_call` records optimize-mode violations in policy_state.
  - `pre_llm_call` consumes any pending nudge and injects it into the
    next turn's context, alongside any queued directives.

Tests drive the hook functions directly with real on-disk session
state. No mocks of drain or registry.

Run: pytest tests/unit/test_hermes_steering.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "evo" / "src"))

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
    return next(iter((root / ".evo").glob("run_*")))


class _Base(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.run_dir = _make_workspace(self.root)
        # repo_root() walks up from cwd; chdir to the workspace so the
        # hermes plugin's _resolve_root() finds it.
        import os
        self._orig_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        import os
        os.chdir(self._orig_cwd)
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# Verify hermes plugin only registers hooks that hermes actually fires
# ---------------------------------------------------------------------------

class TestRegistersOnlyValidHooks(unittest.TestCase):

    # Match hermes-agent 0.10's hermes_cli/plugins.py#VALID_HOOKS exactly.
    HERMES_VALID_HOOKS = frozenset({
        "pre_tool_call", "post_tool_call",
        "pre_llm_call", "post_llm_call",
        "pre_api_request", "post_api_request",
        "on_session_start", "on_session_end",
        "on_session_finalize", "on_session_reset",
    })

    def test_register_only_uses_valid_hook_names(self):
        from evo.hermes_plugin import register

        registered: list[str] = []

        class _FakeCtx:
            def register_hook(self, name, cb):
                registered.append(name)

        register(_FakeCtx())
        for name in registered:
            self.assertIn(
                name, self.HERMES_VALID_HOOKS,
                f"hermes plugin registers {name!r}, which is NOT in hermes-agent "
                f"VALID_HOOKS. The hook will never fire."
            )

    def test_transform_tool_result_not_registered(self):
        """Regression: the previous evo plugin registered
        `transform_tool_result`, a hook hermes does not fire. The new
        port must not."""
        from evo.hermes_plugin import register

        registered: list[str] = []

        class _FakeCtx:
            def register_hook(self, name, cb):
                registered.append(name)

        register(_FakeCtx())
        self.assertNotIn("transform_tool_result", registered)


# ---------------------------------------------------------------------------
# pre_tool_call observer: records violations to policy_state
# ---------------------------------------------------------------------------

class TestPreToolCallRecordsViolations(_Base):

    def test_denied_tool_increments_counter(self):
        from evo.hermes_plugin import _on_pre_tool_call
        from evo.inject.drain import _read_policy_state

        register_session(self.root, "h1", "hermes")
        mark_engaged(self.root, "h1")
        mark_optimize_mode(self.root, "h1")

        _on_pre_tool_call(
            tool_name="file_write", args={"file_path": "/x"},
            task_id="h1", session_id="h1",
        )
        state = _read_policy_state(self.root, "h1")
        self.assertEqual(state.get("violation_count"), 1,
                         f"denied tool must increment counter; got {state!r}")
        self.assertTrue(state.get("nudge_pending"),
                        "nudge_pending flag must be set after a violation")

    def test_denied_bash_command_recorded(self):
        from evo.hermes_plugin import _on_pre_tool_call
        from evo.inject.drain import _read_policy_state

        register_session(self.root, "h1", "hermes")
        mark_engaged(self.root, "h1")
        mark_optimize_mode(self.root, "h1")

        _on_pre_tool_call(
            tool_name="terminal", args={"command": "sed -i s/a/b/ f.py"},
            task_id="h1", session_id="h1",
        )
        state = _read_policy_state(self.root, "h1")
        self.assertEqual(state.get("violation_count"), 1)

    def test_non_denied_tool_does_not_record(self):
        from evo.hermes_plugin import _on_pre_tool_call
        from evo.inject.drain import _read_policy_state

        register_session(self.root, "h1", "hermes")
        mark_engaged(self.root, "h1")
        mark_optimize_mode(self.root, "h1")

        for tn in ("read_file", "list_dir", "web_search", "grep"):
            _on_pre_tool_call(
                tool_name=tn, args={"path": "/x"},
                task_id="h1", session_id="h1",
            )
        state = _read_policy_state(self.root, "h1")
        self.assertEqual(state.get("violation_count", 0), 0,
                         f"non-denied tools must not record; got {state!r}")

    def test_outside_optimize_mode_not_recorded(self):
        from evo.hermes_plugin import _on_pre_tool_call
        from evo.inject.drain import _read_policy_state

        register_session(self.root, "h1", "hermes")
        mark_engaged(self.root, "h1")
        # optimize_mode NOT set
        _on_pre_tool_call(
            tool_name="file_write", args={}, task_id="h1", session_id="h1",
        )
        state = _read_policy_state(self.root, "h1")
        self.assertEqual(state.get("violation_count", 0), 0)

    def test_subagent_not_recorded(self):
        from evo.hermes_plugin import _on_pre_tool_call
        from evo.inject.drain import _read_policy_state
        from evo.inject.paths import session_file

        register_session(self.root, "h_sub", "hermes", exp_id="exp_0001")
        mark_engaged(self.root, "h_sub")
        # Force optimize_mode true (mark_optimize_mode refuses subagents)
        sf = session_file(self.root, "h_sub")
        data = json.loads(sf.read_text())
        data["optimize_mode"] = True
        sf.write_text(json.dumps(data))

        _on_pre_tool_call(
            tool_name="file_write", args={}, task_id="h_sub", session_id="h_sub",
        )
        state = _read_policy_state(self.root, "h_sub")
        self.assertEqual(state.get("violation_count", 0), 0,
                         "subagent must not be policy-recorded")


# ---------------------------------------------------------------------------
# pre_llm_call: consumes nudge + delivers directives
# ---------------------------------------------------------------------------

class TestPreLlmCallNudgeDelivery(_Base):

    def test_first_violation_injects_banner_on_next_pre_llm_call(self):
        from evo.hermes_plugin import _on_pre_tool_call, _on_pre_llm_call

        register_session(self.root, "h1", "hermes")
        mark_engaged(self.root, "h1")
        mark_optimize_mode(self.root, "h1")

        # Turn 1: denied tool fires.
        _on_pre_tool_call(
            tool_name="file_write", args={"file_path": "/x"},
            task_id="h1", session_id="h1",
        )
        # Turn 2: pre_llm_call should inject the banner.
        out = _on_pre_llm_call(session_id="h1")
        self.assertIsNotNone(out, "pending nudge must inject context")
        self.assertIn("EVO POLICY", out.get("context", ""))

    def test_alternating_cadence_on_consecutive_violations(self):
        from evo.hermes_plugin import _on_pre_tool_call, _on_pre_llm_call

        register_session(self.root, "h1", "hermes")
        mark_engaged(self.root, "h1")
        mark_optimize_mode(self.root, "h1")

        # Violation #1 → odd → next pre_llm_call nudges
        _on_pre_tool_call(tool_name="file_write", args={"file_path": "/a"},
                          task_id="h1", session_id="h1")
        out1 = _on_pre_llm_call(session_id="h1")
        self.assertIsNotNone(out1)
        self.assertIn("EVO POLICY", out1.get("context", ""))

        # Violation #2 → even → next pre_llm_call does NOT nudge
        _on_pre_tool_call(tool_name="file_write", args={"file_path": "/b"},
                          task_id="h1", session_id="h1")
        out2 = _on_pre_llm_call(session_id="h1")
        if out2 is not None:
            self.assertNotIn("EVO POLICY", out2.get("context", ""),
                             f"#2 must not nudge under alternating cadence; got {out2!r}")

        # Violation #3 → odd → nudges again
        _on_pre_tool_call(tool_name="file_write", args={"file_path": "/c"},
                          task_id="h1", session_id="h1")
        out3 = _on_pre_llm_call(session_id="h1")
        self.assertIsNotNone(out3)
        self.assertIn("EVO POLICY", out3.get("context", ""))

    def test_pre_llm_call_without_pending_violation_returns_none(self):
        from evo.hermes_plugin import _on_pre_llm_call

        register_session(self.root, "h1", "hermes")
        mark_engaged(self.root, "h1")
        mark_optimize_mode(self.root, "h1")

        # No violations recorded; no directives queued.
        out = _on_pre_llm_call(session_id="h1")
        self.assertIsNone(out, "no pending state must return None (no injection)")

    def test_pending_nudge_cleared_after_injection(self):
        from evo.hermes_plugin import _on_pre_tool_call, _on_pre_llm_call
        from evo.inject.drain import _read_policy_state

        register_session(self.root, "h1", "hermes")
        mark_engaged(self.root, "h1")
        mark_optimize_mode(self.root, "h1")

        _on_pre_tool_call(tool_name="file_write", args={},
                          task_id="h1", session_id="h1")
        _on_pre_llm_call(session_id="h1")
        state = _read_policy_state(self.root, "h1")
        self.assertFalse(state.get("nudge_pending", False),
                         "nudge_pending must clear after injection")


# ---------------------------------------------------------------------------
# Auto-arm optimize_mode from /optimize prompt
# ---------------------------------------------------------------------------

class TestHermesAutoArmOptimizeMode(_Base):

    def test_pre_llm_call_with_optimize_prompt_arms_mode(self):
        from evo.hermes_plugin import _on_pre_llm_call
        from evo.inject.registry import get_session

        _on_pre_llm_call(session_id="h_arm", prompt="/optimize fix the bug")
        sess = get_session(self.root, "h_arm")
        self.assertIsNotNone(sess)
        self.assertTrue(sess.get("optimize_mode"),
                        f"/optimize must auto-arm optimize_mode; got {sess!r}")

    def test_pre_llm_call_without_optimize_prompt_does_not_arm(self):
        from evo.hermes_plugin import _on_pre_llm_call
        from evo.inject.registry import get_session

        _on_pre_llm_call(session_id="h_noarm", prompt="what is the weather")
        sess = get_session(self.root, "h_noarm")
        self.assertIsNotNone(sess)
        self.assertFalse(sess.get("optimize_mode"),
                         f"non-/optimize prompt must not arm; got {sess!r}")


# ---------------------------------------------------------------------------
# Combined emit: policy banner + queued directive ordering
# ---------------------------------------------------------------------------

class TestHermesCombinedEmit(_Base):

    def test_banner_before_directive_in_context(self):
        from evo.hermes_plugin import _on_pre_tool_call, _on_pre_llm_call
        from evo.inject import queue, marker

        register_session(self.root, "h1", "hermes")
        mark_engaged(self.root, "h1")
        mark_optimize_mode(self.root, "h1")

        # Queue a directive and record a violation.
        queue.append_workspace_event(self.root, "TRY_COSINE")
        marker.touch(self.root, "h1")
        _on_pre_tool_call(tool_name="file_write", args={},
                          task_id="h1", session_id="h1")

        out = _on_pre_llm_call(session_id="h1")
        self.assertIsNotNone(out)
        ctx = out.get("context", "")
        self.assertIn("EVO POLICY", ctx, "banner must appear")
        self.assertIn("TRY_COSINE", ctx, "directive must appear")
        banner_pos = ctx.find("EVO POLICY")
        directive_pos = ctx.find("TRY_COSINE")
        self.assertLess(banner_pos, directive_pos,
                        "banner must come before directive so truncation "
                        "doesn't lose the corrective signal")


if __name__ == "__main__":
    unittest.main()
