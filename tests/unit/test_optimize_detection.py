"""Tests for auto-detection of /evo:optimize invocation from
UserPromptSubmit-like hook payloads.

When the user types `/evo:optimize` (claude-code), `$evo:optimize`
(codex), `/optimize` (cursor), etc., the corresponding host fires a
prompt-submit hook with the user's text in the payload. The drain
pattern-matches the text against host-specific patterns and flips
optimize_mode on the session record. No agent action required; no
skill changes.

These tests exercise drain.main() directly (the same entrypoint the
host hook invokes), with stdin patched to a synthetic payload. No
mocks of real impls — real registry, real filesystem, real drain.

Run: pytest tests/unit/test_optimize_detection.py -v
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

from evo.inject.paths import session_file
from evo.inject.registry import register_session


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@evo"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)
    (root / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)


def _make_workspace(root: Path) -> None:
    _init_git_repo(root)
    from evo.core import init_workspace
    init_workspace(
        root, target="agent.py", benchmark="python bench.py",
        metric="max", gate=None,
    )


def _read_record(root: Path, sid: str) -> dict | None:
    p = session_file(root, sid)
    if not p.exists():
        return None
    return json.loads(p.read_text())


class _BaseDetectionTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        _make_workspace(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _fire_prompt_submit(self, sid: str, host: str, prompt: str,
                            hook_event: str = "UserPromptSubmit") -> None:
        """Invoke drain.main() as the host hook would, with a synthetic
        payload. Returns nothing — assertion happens via reading the
        session record."""
        from evo.inject.drain import main
        # Self-contained Cursor invocation uses --host cursor + key on
        # conversation_id. Other hosts use the Rust hot path which passes
        # --run-dir + --session. Synthesize the right shape per host.
        if host == "cursor":
            payload = {
                "hook_event_name": hook_event,
                "conversation_id": sid,
                "workspace_roots": [str(self.root)],
                "prompt": prompt,
            }
            stdin_buf = io.StringIO(json.dumps(payload))
            stdout_buf = io.StringIO()
            with patch("sys.stdin", stdin_buf), patch("sys.stdout", stdout_buf):
                main(["--host", "cursor"])
        else:
            # Rust hot path: run_dir + session passed as args
            run_dir = next(iter((self.root / ".evo").glob("run_*")))
            payload = {
                "session_id": sid,
                "hook_event_name": hook_event,
                "prompt": prompt,
            }
            stdin_buf = io.StringIO(json.dumps(payload))
            stdout_buf = io.StringIO()
            with patch("sys.stdin", stdin_buf), patch("sys.stdout", stdout_buf):
                main(["--run-dir", str(run_dir), "--session", sid, "--host", host])


# ---------------------------------------------------------------------------
# Claude Code: /evo:optimize
# ---------------------------------------------------------------------------

class TestClaudeCodeDetection(_BaseDetectionTest):

    def test_slash_evo_optimize_flips_optimize_mode(self):
        register_session(self.root, "cc_sid", "claude-code")
        self._fire_prompt_submit("cc_sid", "claude-code", "/evo:optimize")
        rec = _read_record(self.root, "cc_sid")
        self.assertTrue(
            rec["optimize_mode"],
            "/evo:optimize at prompt start must flip optimize_mode on claude-code"
        )

    def test_slash_evo_optimize_with_args_still_matches(self):
        register_session(self.root, "cc_sid2", "claude-code")
        self._fire_prompt_submit(
            "cc_sid2", "claude-code",
            "/evo:optimize subagents=3 budget=10",
        )
        rec = _read_record(self.root, "cc_sid2")
        self.assertTrue(rec["optimize_mode"])

    def test_unrelated_prompt_does_not_flip(self):
        register_session(self.root, "cc_sid3", "claude-code")
        self._fire_prompt_submit("cc_sid3", "claude-code", "hello, please help me debug this")
        rec = _read_record(self.root, "cc_sid3")
        self.assertFalse(
            rec["optimize_mode"],
            "regular prompts must not flip the flag"
        )

    def test_brief_text_containing_invocation_mid_prompt_does_not_match(self):
        """The orchestrator's brief to a subagent might mention '/evo:optimize'
        as a literal string. The anchored regex must not match that — only
        prompts that START with the invocation count."""
        register_session(self.root, "cc_sid4", "claude-code")
        self._fire_prompt_submit(
            "cc_sid4", "claude-code",
            "Here is your brief: you are working under the /evo:optimize "
            "skill. Please run experiment exp_0042 and report results."
        )
        rec = _read_record(self.root, "cc_sid4")
        self.assertFalse(
            rec["optimize_mode"],
            "anchored regex must not match invocation mid-prompt"
        )


# ---------------------------------------------------------------------------
# Codex: $evo:optimize / $evo optimize
# ---------------------------------------------------------------------------

class TestCodexDetection(_BaseDetectionTest):

    def test_dollar_evo_colon_optimize(self):
        register_session(self.root, "cdx1", "codex")
        self._fire_prompt_submit("cdx1", "codex", "$evo:optimize")
        rec = _read_record(self.root, "cdx1")
        self.assertTrue(rec["optimize_mode"])

    def test_dollar_evo_space_optimize(self):
        register_session(self.root, "cdx2", "codex")
        self._fire_prompt_submit("cdx2", "codex", "$evo optimize")
        rec = _read_record(self.root, "cdx2")
        self.assertTrue(rec["optimize_mode"])

    def test_codex_pattern_does_not_match_claude_form(self):
        """A codex session that somehow received claude-code's slash form
        shouldn't flip — patterns are host-specific."""
        register_session(self.root, "cdx3", "codex")
        self._fire_prompt_submit("cdx3", "codex", "/evo:optimize")
        rec = _read_record(self.root, "cdx3")
        self.assertFalse(rec["optimize_mode"])


# ---------------------------------------------------------------------------
# Cursor: /optimize
# ---------------------------------------------------------------------------

class TestCursorDetection(_BaseDetectionTest):

    def test_slash_optimize(self):
        # Cursor uses its self-contained drain path — session is keyed on
        # conversation_id and registers lazily. The detection happens after
        # registration on the same event.
        self._fire_prompt_submit(
            "cursor_conv", "cursor", "/optimize",
            hook_event="beforeSubmitPrompt",
        )
        rec = _read_record(self.root, "cursor_conv")
        self.assertIsNotNone(rec, "session should register on first prompt event")
        self.assertTrue(
            rec["optimize_mode"],
            "/optimize at prompt start must flip optimize_mode on cursor"
        )


# ---------------------------------------------------------------------------
# Subagent fence — never flip optimize_mode on a subagent session
# ---------------------------------------------------------------------------

class TestSubagentFence(_BaseDetectionTest):

    def test_subagent_session_cannot_be_flipped_even_with_matching_prompt(self):
        """A subagent's first prompt is a brief. If the orchestrator's brief
        text happens to start with /evo:optimize (unusual but possible —
        e.g. the orchestrator pasted the skill invocation as a quoted
        instruction), the subagent must NOT be flipped."""
        register_session(
            self.root, "sub_sid", "claude-code", exp_id="exp_0099"
        )
        self._fire_prompt_submit(
            "sub_sid", "claude-code", "/evo:optimize do this thing"
        )
        rec = _read_record(self.root, "sub_sid")
        self.assertFalse(
            rec["optimize_mode"],
            "subagent session (exp_id set) must never be flipped"
        )


# ---------------------------------------------------------------------------
# Already-engaged orchestrator getting /optimize a second time
# ---------------------------------------------------------------------------

class TestIdempotentDetection(_BaseDetectionTest):

    def test_already_in_optimize_mode_stays_in_optimize_mode(self):
        from evo.inject.registry import mark_optimize_mode
        register_session(self.root, "idemp_sid", "claude-code")
        mark_optimize_mode(self.root, "idemp_sid")
        original_at = _read_record(self.root, "idemp_sid")["optimize_mode_at"]
        # Re-invoke /optimize
        self._fire_prompt_submit("idemp_sid", "claude-code", "/evo:optimize")
        rec = _read_record(self.root, "idemp_sid")
        self.assertTrue(rec["optimize_mode"], "stays on")
        self.assertEqual(
            rec["optimize_mode_at"], original_at,
            "timestamp should not bump on idempotent re-invocation"
        )


if __name__ == "__main__":
    unittest.main()
