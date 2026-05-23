"""Unit tests for the ACK channel.

Two layers:

  L1 — delivery ack (automatic). When `drain_session` emits events, it
       writes inject/delivered/<event_id>.json with the receiving session,
       host, hook_event, and timestamp. No model cooperation required;
       this just records "the drain process emitted JSON for this event."

  L2 — model ack (explicit). The directive text the model receives now
       embeds the event_id and instructs the model to run `evo ack <id>`.
       The CLI command writes inject/acks/<id>.json. Proves the model
       saw and processed the directive.

Plus a `evo direct status <id>` subcommand that shows both states, and an
`evo direct --wait` flag that polls for the ack with a timeout.

No mocks of real impls — uses real cmd_direct, real drain_session, real
filesystem.

Run: pytest tests/unit/test_ack_channel.py -v
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "evo" / "src"))

from evo.inject import marker, queue
from evo.inject.paths import (
    inject_root,
    session_file,
    workspace_events_path,
)
from evo.inject.registry import register_session, mark_engaged


# ---------------------------------------------------------------------------
# Helpers (mirror test_inject.py conventions)
# ---------------------------------------------------------------------------

_HOST_ENV_VARS = (
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_THREAD_ID",
    "HERMES_SESSION_ID",
    "OPENCODE_SESSION_ID",
    "EVO_EXP_ID",
)


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
        root,
        target="agent.py",
        benchmark="python bench.py",
        metric="max",
        gate=None,
    )


def _clear_host_env() -> None:
    for v in _HOST_ENV_VARS:
        os.environ.pop(v, None)


def _build_args(*args: str, **kwargs) -> argparse.Namespace:
    return argparse.Namespace(args=list(args), **kwargs)


# ---------------------------------------------------------------------------
# L1: delivery ack — drain writes inject/delivered/<event_id>.json
# ---------------------------------------------------------------------------

class TestDeliveryAck(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        _make_workspace(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_drain_writes_delivery_record_per_event(self):
        from evo.inject.drain import drain_session
        from evo.inject.paths import delivered_file

        register_session(self.root, "sess_x", "claude-code")
        mark_engaged(self.root, "sess_x")
        ev_id = queue.append_workspace_event(self.root, "delete file X")
        marker.touch(self.root, "sess_x")

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            drain_session(
                self.root, "sess_x",
                host="claude-code", hook_event="PreToolUse",
            )

        # L1 record exists
        path = delivered_file(self.root, ev_id)
        assert path.exists(), f"delivery record not written at {path}"
        rec = json.loads(path.read_text())
        assert rec["event_id"] == ev_id
        assert rec["session_id"] == "sess_x"
        assert rec["host"] == "claude-code"
        assert rec["hook_event"] == "PreToolUse"
        assert "delivered_at" in rec

    def test_drain_does_not_write_delivery_record_when_no_events(self):
        from evo.inject.drain import drain_session
        from evo.inject.paths import delivered_dir

        register_session(self.root, "sess_y", "claude-code")
        mark_engaged(self.root, "sess_y")
        marker.touch(self.root, "sess_y")
        # No event in queue

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            drain_session(
                self.root, "sess_y",
                host="claude-code", hook_event="PreToolUse",
            )

        # No delivery records written
        d = delivered_dir(self.root)
        records = list(d.glob("*.json")) if d.exists() else []
        assert records == [], f"unexpected delivery records: {records}"

    def test_multiple_events_each_get_their_own_record(self):
        from evo.inject.drain import drain_session
        from evo.inject.paths import delivered_file

        register_session(self.root, "sess_z", "claude-code")
        mark_engaged(self.root, "sess_z")
        e1 = queue.append_workspace_event(self.root, "first")
        e2 = queue.append_workspace_event(self.root, "second")
        marker.touch(self.root, "sess_z")

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            drain_session(
                self.root, "sess_z",
                host="claude-code", hook_event="PreToolUse",
            )

        assert delivered_file(self.root, e1).exists()
        assert delivered_file(self.root, e2).exists()


# ---------------------------------------------------------------------------
# Directive text includes the event id
# ---------------------------------------------------------------------------

class TestDirectiveIncludesId(unittest.TestCase):

    def test_format_directive_text_embeds_event_id(self):
        from evo.inject.drain import format_directive_text

        events = [
            {"id": "01HX7K000000000000000000ABCDEF", "text": "delete file X"},
        ]
        text = format_directive_text(events)
        # Must include the id so the model can ack it
        assert "01HX7K000000000000000000ABCDEF" in text, (
            f"directive text must include event id; got: {text!r}"
        )
        # Must instruct the agent to ack
        assert "evo ack" in text, (
            f"directive text must instruct the agent to run `evo ack`; got: {text!r}"
        )

    def test_format_directive_text_includes_multiple_ids(self):
        from evo.inject.drain import format_directive_text
        events = [
            {"id": "01AAA00000000000000000000000AA", "text": "first"},
            {"id": "01BBB00000000000000000000000BB", "text": "second"},
        ]
        text = format_directive_text(events)
        assert "01AAA00000000000000000000000AA" in text
        assert "01BBB00000000000000000000000BB" in text


# ---------------------------------------------------------------------------
# L2: evo ack CLI command writes inject/acks/<id>.json
# ---------------------------------------------------------------------------

class TestEvoAckCli(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        _make_workspace(self.root)
        self._old_cwd = Path.cwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_evo_ack_writes_ack_file(self):
        from evo.cli import cmd_ack
        from evo.inject.paths import ack_file

        register_session(self.root, "ack_sess", "claude-code")
        mark_engaged(self.root, "ack_sess")

        ev_id = "01HX7K000000000000000000ABCDEF"
        # Simulate the agent running `evo ack <id>` — it shells the CLI
        # with its CLAUDE_CODE_SESSION_ID set so we can attribute the ack.
        with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "ack_sess"}, clear=False):
            _clear_host_env()
            os.environ["CLAUDE_CODE_SESSION_ID"] = "ack_sess"
            rc = cmd_ack(argparse.Namespace(event_id=ev_id))

        assert rc == 0
        path = ack_file(self.root, ev_id)
        assert path.exists(), f"ack file not created at {path}"
        rec = json.loads(path.read_text())
        assert rec["event_id"] == ev_id
        assert rec["session_id"] == "ack_sess"
        assert rec["host"] == "claude-code"
        assert "acked_at" in rec

    def test_evo_ack_is_idempotent(self):
        from evo.cli import cmd_ack
        from evo.inject.paths import ack_file

        register_session(self.root, "ack_sess2", "claude-code")
        mark_engaged(self.root, "ack_sess2")

        ev_id = "01HX7K000000000000000000FFFFFF"
        with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "ack_sess2"}, clear=False):
            _clear_host_env()
            os.environ["CLAUDE_CODE_SESSION_ID"] = "ack_sess2"
            cmd_ack(argparse.Namespace(event_id=ev_id))
            cmd_ack(argparse.Namespace(event_id=ev_id))  # second call

        path = ack_file(self.root, ev_id)
        rec = json.loads(path.read_text())
        # Idempotent: same ack file, ack_count tracks repeats
        assert rec["event_id"] == ev_id
        assert rec.get("ack_count", 1) == 2  # incremented on second ack

    def test_evo_ack_works_without_session_env(self):
        # Even outside a host session (e.g. user manually marking acked),
        # the ack file should still be written with session_id=None.
        from evo.cli import cmd_ack
        from evo.inject.paths import ack_file

        ev_id = "01HX7K000000000000000000DEADBE"
        _clear_host_env()
        rc = cmd_ack(argparse.Namespace(event_id=ev_id))
        assert rc == 0
        path = ack_file(self.root, ev_id)
        rec = json.loads(path.read_text())
        assert rec["event_id"] == ev_id
        assert rec.get("session_id") is None


# ---------------------------------------------------------------------------
# evo direct status: shows delivery + ack state
# ---------------------------------------------------------------------------

class TestDirectStatus(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        _make_workspace(self.root)
        self._old_cwd = Path.cwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _run_status(self, event_id: str) -> tuple[int, str]:
        from evo.cli import cmd_direct_status
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cmd_direct_status(argparse.Namespace(event_id=event_id))
        return rc, buf.getvalue()

    def test_status_shows_queued_only_when_not_yet_delivered(self):
        ev_id = queue.append_workspace_event(self.root, "pending")
        rc, out = self._run_status(ev_id)
        assert rc == 0
        out_lower = out.lower()
        assert "queued" in out_lower
        # No delivery record yet — the status output should signal that.
        assert "no record" in out_lower or "(none)" in out_lower or "not delivered" in out_lower
        # No ack yet either.
        assert "no ack" in out_lower or "(none)" in out_lower

    def test_status_shows_delivery_after_drain(self):
        from evo.inject.drain import drain_session

        register_session(self.root, "stat_sess", "claude-code")
        mark_engaged(self.root, "stat_sess")
        ev_id = queue.append_workspace_event(self.root, "deliverable")
        marker.touch(self.root, "stat_sess")

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            drain_session(self.root, "stat_sess", host="claude-code", hook_event="PreToolUse")

        rc, out = self._run_status(ev_id)
        assert rc == 0
        assert "stat_sess" in out, f"status must mention delivery to stat_sess; got: {out!r}"

    def test_status_shows_ack_after_evo_ack(self):
        from evo.cli import cmd_ack
        register_session(self.root, "ack_visible", "claude-code")
        mark_engaged(self.root, "ack_visible")
        ev_id = queue.append_workspace_event(self.root, "ackable")

        with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "ack_visible"}, clear=False):
            _clear_host_env()
            os.environ["CLAUDE_CODE_SESSION_ID"] = "ack_visible"
            cmd_ack(argparse.Namespace(event_id=ev_id))

        rc, out = self._run_status(ev_id)
        assert rc == 0
        assert "ack" in out.lower(), f"status must mention ack; got: {out!r}"
        assert "ack_visible" in out, f"status must show acking session; got: {out!r}"


# ---------------------------------------------------------------------------
# evo direct --wait: polls for ack with timeout
# ---------------------------------------------------------------------------

class TestDirectWait(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        _make_workspace(self.root)
        self._old_cwd = Path.cwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_wait_returns_success_when_ack_arrives(self):
        from evo.cli import cmd_direct
        from evo.inject.paths import ack_file

        register_session(self.root, "wait_sess", "claude-code")
        mark_engaged(self.root, "wait_sess")

        # Spawn a background thread that writes the ack a few ms after
        # `evo direct --wait` starts polling.
        import threading

        # We need the event_id to write the ack. Run cmd_direct in the
        # foreground; it'll print the id; concurrently another thread
        # writes the ack. We pre-write the ack by knowing how the id is
        # derived isn't possible (it's a ulid). So instead we run cmd_direct
        # in a background thread that captures the id and reports it via
        # an event; the main thread writes the ack once it sees the id.
        captured = io.StringIO()
        ev_id_holder: dict = {}

        def background_writer() -> None:
            # Poll for the event to appear in workspace.jsonl
            for _ in range(50):
                events = queue.read_events_after(workspace_events_path(self.root), None)
                if events:
                    ev_id_holder["id"] = events[-1]["id"]
                    # Write ack file directly (simulating evo ack from the host)
                    p = ack_file(self.root, ev_id_holder["id"])
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps({
                        "event_id": ev_id_holder["id"],
                        "session_id": "wait_sess",
                        "host": "claude-code",
                        "acked_at": "2026-05-23T10:30:00+00:00",
                    }))
                    return
                time.sleep(0.05)

        t = threading.Thread(target=background_writer, daemon=True)
        t.start()

        with patch("sys.stdout", captured):
            rc = cmd_direct(_build_args("test wait", wait=True, wait_timeout=5.0))

        t.join(timeout=2.0)
        assert rc == 0
        assert "acked" in captured.getvalue().lower(), (
            f"--wait should report ack received; got: {captured.getvalue()!r}"
        )

    def test_wait_times_out_cleanly(self):
        from evo.cli import cmd_direct

        register_session(self.root, "timeout_sess", "claude-code")
        mark_engaged(self.root, "timeout_sess")

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            # No ack will ever arrive — wait should time out cleanly.
            rc = cmd_direct(_build_args("no ack coming", wait=True, wait_timeout=0.3))

        # rc != 0 to signal timeout (exit code 3 by convention)
        assert rc != 0, f"timeout must return non-zero rc; got rc={rc}"
        assert "timeout" in captured.getvalue().lower() or "timed out" in captured.getvalue().lower()


if __name__ == "__main__":
    unittest.main()
