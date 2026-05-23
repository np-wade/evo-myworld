"""Tests for the PreToolUse policy nudge that steers the orchestrator
back to the /optimize protocol.

When the orchestrator (in optimize_mode) tries to:
  - Edit / Write / NotebookEdit a file (any host's edit-like tool), OR
  - Bash a non-allowlisted command (anything other than `evo …`,
    host-spawn commands, or read-only inspection)

…the drain emits a hard-deny envelope on the 1st violation and every
5th violation thereafter, with a banner explaining the protocol. In
between, the tool calls go through silently (no block, no nudge).

The intent: re-anchor the agent's mental model of the optimize protocol
without nagging it every single tool call. Block-first-then-spaced
matches the user's spec.

Tests use real drain.py functions + real session records. No mocks of
real impls.

Run: pytest tests/unit/test_policy_nudge.py -v
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
    return next(iter((root / ".evo").glob("run_*")))


def _drive_pretooluse(
    root: Path, sid: str, tool_name: str, tool_input: dict,
    host: str = "claude-code",
) -> dict:
    """Drive drain_session as a PreToolUse hook would. Returns parsed
    JSON envelope."""
    from evo.inject.drain import drain_session
    buf = io.StringIO()
    payload = {
        "session_id": sid,
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    with patch("sys.stdout", buf):
        drain_session(root, sid, host=host, hook_event="PreToolUse", payload=payload)
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
# Cross-host tool classifier
# ---------------------------------------------------------------------------

class TestToolClassifier(unittest.TestCase):

    def test_claude_code_names(self):
        from evo.inject.drain import _classify_tool
        self.assertEqual(_classify_tool("claude-code", "Edit"), "edit")
        self.assertEqual(_classify_tool("claude-code", "Write"), "edit")
        self.assertEqual(_classify_tool("claude-code", "NotebookEdit"), "edit")
        self.assertEqual(_classify_tool("claude-code", "Bash"), "bash")
        self.assertEqual(_classify_tool("claude-code", "Read"), "read")
        self.assertEqual(_classify_tool("claude-code", "Glob"), "read")
        self.assertEqual(_classify_tool("claude-code", "Grep"), "read")

    def test_cursor_names(self):
        from evo.inject.drain import _classify_tool
        self.assertEqual(_classify_tool("cursor", "edit_file"), "edit")
        self.assertEqual(_classify_tool("cursor", "create_file"), "edit")
        self.assertEqual(_classify_tool("cursor", "search_replace"), "edit")
        self.assertEqual(_classify_tool("cursor", "run_terminal_cmd"), "bash")
        self.assertEqual(_classify_tool("cursor", "shell"), "bash")
        self.assertEqual(_classify_tool("cursor", "read_file"), "read")

    def test_codex_names(self):
        from evo.inject.drain import _classify_tool
        # Codex uses similar names to claude-code (Edit/Write) plus shell variants
        self.assertEqual(_classify_tool("codex", "edit"), "edit")
        self.assertEqual(_classify_tool("codex", "shell"), "bash")
        self.assertEqual(_classify_tool("codex", "exec"), "bash")

    def test_unknown_returns_other(self):
        from evo.inject.drain import _classify_tool
        self.assertEqual(_classify_tool("claude-code", "TodoWrite"), "other")
        self.assertEqual(_classify_tool("claude-code", "WebSearch"), "other")
        self.assertEqual(_classify_tool("claude-code", None), "other")
        self.assertEqual(_classify_tool("claude-code", ""), "other")


# ---------------------------------------------------------------------------
# Bash allowlist
# ---------------------------------------------------------------------------

class TestBashAllowlist(unittest.TestCase):

    def test_evo_commands_allowed(self):
        from evo.inject.drain import _is_allowed_orchestrator_bash
        self.assertTrue(_is_allowed_orchestrator_bash("evo status"))
        self.assertTrue(_is_allowed_orchestrator_bash("evo scratchpad"))
        self.assertTrue(_is_allowed_orchestrator_bash("evo direct 'foo'"))
        self.assertTrue(_is_allowed_orchestrator_bash("  evo wait --timeout 60"))

    def test_host_spawn_commands_allowed(self):
        from evo.inject.drain import _is_allowed_orchestrator_bash
        # Background subagent spawn patterns from the optimize skill
        self.assertTrue(_is_allowed_orchestrator_bash(
            "claude --print --model claude-sonnet-4-5 'do task'"
        ))
        self.assertTrue(_is_allowed_orchestrator_bash(
            "codex exec --full-auto 'do task'"
        ))
        self.assertTrue(_is_allowed_orchestrator_bash(
            "cursor-agent -p 'brief'"
        ))
        self.assertTrue(_is_allowed_orchestrator_bash(
            "opencode run --model anthropic/claude-sonnet-4-5 'brief'"
        ))
        self.assertTrue(_is_allowed_orchestrator_bash(
            "nohup claude --print 'brief' > /tmp/agent.log 2>&1 &"
        ))

    def test_readonly_inspection_allowed(self):
        from evo.inject.drain import _is_allowed_orchestrator_bash
        for cmd in (
            "git status", "git log --oneline -10", "git diff HEAD~1",
            "ls -la .evo", "cat .evo/config.json",
            "find . -name '*.py'", "grep -r 'TODO' src/",
            "head -20 README.md", "tail -50 /tmp/log",
            "pwd", "env | grep EVO", "echo hello",
            "wc -l file.txt", "which python",
        ):
            self.assertTrue(_is_allowed_orchestrator_bash(cmd),
                            f"expected allowed: {cmd!r}")

    def test_running_experiments_by_hand_blocked(self):
        from evo.inject.drain import _is_allowed_orchestrator_bash
        for cmd in (
            "python bench.py",
            "python3 -m pytest tests/",
            "pytest -xvs tests/",
            "./run_benchmark.sh",
            "make eval",
            "node index.js",
            "rm -rf experiments/",
            "mkdir custom_exp",
            "cp src/foo.py worktree/",
            "sed -i 's/x/y/' file.py",
            "curl http://localhost:8080/run",
        ):
            self.assertFalse(_is_allowed_orchestrator_bash(cmd),
                             f"expected NOT allowed: {cmd!r}")


# ---------------------------------------------------------------------------
# First edit blocks, then every 5th
# ---------------------------------------------------------------------------

class TestEditBlockCadence(_Base):

    def _setup_orchestrator(self) -> None:
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")

    def test_first_edit_is_blocked_with_banner(self):
        self._setup_orchestrator()
        out = _drive_pretooluse(self.root, "orch", "Edit",
                                {"file_path": "/some/file.py"})
        self.assertEqual(out.get("permission"), "deny",
                         f"first Edit must be hard-denied; got {out!r}")
        self.assertIn("optimize", (out.get("reason") or "").lower(),
                      f"banner must mention optimize protocol")

    def test_edits_2_3_4_pass_silently(self):
        self._setup_orchestrator()
        # Violation #1 — blocked
        _drive_pretooluse(self.root, "orch", "Edit", {"file_path": "/f.py"})
        # Violations 2, 3, 4 — silent
        for n in (2, 3, 4):
            out = _drive_pretooluse(self.root, "orch", "Edit", {"file_path": "/f.py"})
            self.assertNotEqual(
                out.get("permission"), "deny",
                f"violation #{n} must not block — only #1 and #5 do; got {out!r}"
            )

    def test_5th_violation_blocks_again(self):
        self._setup_orchestrator()
        # Trigger 5 violations: #1 (blocked), #2/3/4 (silent), #5 (blocked again)
        outs = [
            _drive_pretooluse(self.root, "orch", "Edit", {"file_path": "/f.py"})
            for _ in range(5)
        ]
        self.assertEqual(outs[0].get("permission"), "deny", "#1 must block")
        for i in (1, 2, 3):
            self.assertNotEqual(outs[i].get("permission"), "deny",
                                f"#{i+1} must NOT block")
        self.assertEqual(outs[4].get("permission"), "deny",
                         f"#5 must block; got {outs[4]!r}")

    def test_10th_violation_also_blocks(self):
        self._setup_orchestrator()
        outs = [
            _drive_pretooluse(self.root, "orch", "Edit", {"file_path": "/f.py"})
            for _ in range(10)
        ]
        # Blocks: 1, 5, 10
        for blocked in (0, 4, 9):
            self.assertEqual(
                outs[blocked].get("permission"), "deny",
                f"#{blocked+1} must block; got {outs[blocked]!r}"
            )


# ---------------------------------------------------------------------------
# Non-evo Bash also blocked
# ---------------------------------------------------------------------------

class TestBashBlock(_Base):

    def _setup_orchestrator(self) -> None:
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")

    def test_first_non_evo_bash_is_blocked(self):
        self._setup_orchestrator()
        out = _drive_pretooluse(
            self.root, "orch", "Bash", {"command": "python bench.py"},
        )
        self.assertEqual(out.get("permission"), "deny",
                         f"non-evo Bash must block on #1; got {out!r}")

    def test_evo_bash_command_never_blocked(self):
        self._setup_orchestrator()
        for cmd in ("evo status", "evo scratchpad", "evo wait", "evo direct 'foo'"):
            out = _drive_pretooluse(self.root, "orch", "Bash", {"command": cmd})
            self.assertNotEqual(
                out.get("permission"), "deny",
                f"evo Bash command must never block: {cmd!r}; got {out!r}"
            )

    def test_subagent_spawn_bash_never_blocked(self):
        self._setup_orchestrator()
        for cmd in (
            "claude --print 'brief' &",
            "nohup codex exec --full-auto 'brief' > /tmp/a.log 2>&1 &",
        ):
            out = _drive_pretooluse(self.root, "orch", "Bash", {"command": cmd})
            self.assertNotEqual(
                out.get("permission"), "deny",
                f"subagent-spawn bash must never block: {cmd!r}; got {out!r}"
            )

    def test_edit_and_bash_violations_share_counter(self):
        """A combined violation stream of edits + bashes blocks at #1 and #5
        overall, not per-rule."""
        self._setup_orchestrator()
        outs = []
        # Mix edits and non-evo bash
        outs.append(_drive_pretooluse(self.root, "orch", "Edit", {"file_path": "/a.py"}))
        outs.append(_drive_pretooluse(self.root, "orch", "Bash", {"command": "python x.py"}))
        outs.append(_drive_pretooluse(self.root, "orch", "Edit", {"file_path": "/b.py"}))
        outs.append(_drive_pretooluse(self.root, "orch", "Bash", {"command": "make"}))
        outs.append(_drive_pretooluse(self.root, "orch", "Edit", {"file_path": "/c.py"}))

        self.assertEqual(outs[0].get("permission"), "deny", "combined #1 blocks")
        for i in (1, 2, 3):
            self.assertNotEqual(outs[i].get("permission"), "deny",
                                f"combined #{i+1} must NOT block")
        self.assertEqual(outs[4].get("permission"), "deny", "combined #5 blocks")


# ---------------------------------------------------------------------------
# Negative cases — must NOT block
# ---------------------------------------------------------------------------

class TestPolicyNudgeDoesNotBlock(_Base):

    def test_subagent_edits_never_blocked(self):
        register_session(self.root, "sub", "claude-code", exp_id="exp_0042")
        mark_engaged(self.root, "sub")
        # Even if optimize_mode somehow set — subagents are always exempt
        for _ in range(10):
            out = _drive_pretooluse(self.root, "sub", "Edit", {"file_path": "/f.py"})
            self.assertNotEqual(out.get("permission"), "deny",
                                "subagents must never be policy-blocked")

    def test_non_optimize_mode_session_never_blocked(self):
        register_session(self.root, "casual", "claude-code")
        mark_engaged(self.root, "casual")
        # optimize_mode NOT set — casual session
        for _ in range(10):
            out = _drive_pretooluse(self.root, "casual", "Edit", {"file_path": "/f.py"})
            self.assertNotEqual(out.get("permission"), "deny",
                                "non-optimize-mode session must not be blocked")

    def test_read_tools_never_blocked(self):
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")
        for tool in ("Read", "Glob", "Grep"):
            out = _drive_pretooluse(self.root, "orch", tool, {"file_path": "/f.py"})
            self.assertNotEqual(out.get("permission"), "deny",
                                f"{tool} must never be blocked")

    def test_other_tools_never_blocked(self):
        """Tools that don't fit edit/bash/read (e.g., TodoWrite, WebFetch)
        must not be blocked — only file mutation + shell execution."""
        register_session(self.root, "orch", "claude-code")
        mark_engaged(self.root, "orch")
        mark_optimize_mode(self.root, "orch")
        for tool in ("TodoWrite", "WebFetch", "WebSearch"):
            out = _drive_pretooluse(self.root, "orch", tool, {"x": "y"})
            self.assertNotEqual(out.get("permission"), "deny",
                                f"{tool} must never be blocked")


# ---------------------------------------------------------------------------
# Cross-host behavior — Cursor edit tool names
# ---------------------------------------------------------------------------

class TestCursorPolicyNudge(_Base):

    def _setup_cursor_orchestrator(self) -> None:
        register_session(self.root, "cursor_sid", "cursor")
        mark_engaged(self.root, "cursor_sid")
        mark_optimize_mode(self.root, "cursor_sid")

    def test_cursor_edit_file_blocked(self):
        """Cursor uses edit_file / search_replace / create_file etc.
        instead of Edit/Write. The classifier handles these the same
        way and the policy gate fires."""
        self._setup_cursor_orchestrator()
        # Note: cursor uses different envelope shapes — we only verify
        # the block happens. Output may differ from claude-code's deny.
        out = _drive_pretooluse(
            self.root, "cursor_sid", "edit_file",
            {"file_path": "/f.py"},
            host="cursor",
        )
        # On cursor, the policy block can come back as a different shape,
        # but the key signal is some form of refusal / nudge. Specifically
        # cursor's deny envelope is "permission": "deny" or "ask".
        self.assertTrue(
            out.get("permission") in ("deny", "ask"),
            f"cursor edit_file must be denied/asked on first violation; got {out!r}"
        )


if __name__ == "__main__":
    unittest.main()
