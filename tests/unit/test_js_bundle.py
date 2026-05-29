"""Tests for the TypeScript drain port — engagement helpers and host
string parameterization.

Real bun runs against the real TS source (no mocks). Each test
synthesizes a small TS snippet that imports from
plugins/evo/src/evo/opencode_plugin/drain.ts, runs it, and asserts on
real on-disk side effects (session record fields, offset file contents).

Skipped if bun isn't on PATH.

Run: pytest tests/unit/test_js_bundle.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "evo" / "src"))

from evo.inject.paths import inject_root, session_file, workspace_events_path


def _has_bun() -> bool:
    return shutil.which("bun") is not None


def _make_inject_dirs(root: Path) -> Path:
    """Set up a fake .evo/run_0000/inject layout (no full git workspace
    needed — the TS drain only touches files under inject/)."""
    run_dir = root / ".evo" / "run_0000"
    for sub in ("sessions", "events", "offsets", "markers", "delivered", "acks"):
        (run_dir / "inject" / sub).mkdir(parents=True, exist_ok=True)
    return run_dir


def _run_ts(snippet: str) -> dict:
    """Run a TS snippet via bun and parse JSON stdout."""
    drain_path = REPO_ROOT / "plugins" / "evo" / "src" / "evo" / "opencode_plugin" / "drain.ts"
    with tempfile.NamedTemporaryFile("w", suffix=".ts", delete=False) as f:
        f.write(f"""
import {{ markEngaged, isEvoCommand, registerSession, initOffsetToLatest, isRegistered }} from "{drain_path}";
{snippet}
""")
        path = f.name
    try:
        result = subprocess.run(
            ["bun", "run", path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"bun failed: {result.stderr}")
        out = (result.stdout or "").strip()
        if not out:
            return {}
        return json.loads(out)
    finally:
        os.unlink(path)


@unittest.skipUnless(_has_bun(), "bun not on PATH")
class TestIsEvoCommand(unittest.TestCase):

    def test_matches_evo_prefix(self):
        result = _run_ts("""
const cases = [
  "evo status",
  " evo status",
  "evo",
  "evo direct 'foo'",
  "evon status",          // not evo (no space)
  "/usr/bin/evo status",  // not at start
  "echo evo status",      // not at start
  "",
  null,
];
const out = cases.map(c => ({input: c, match: isEvoCommand(c as any)}));
process.stdout.write(JSON.stringify(out));
""")
        # First four should match; rest should not
        labels = [r["input"] for r in result]
        matches = [r["match"] for r in result]
        # Just check key cases
        expected = {
            "evo status": True,
            "evo": True,
            "evo direct 'foo'": True,
            "evon status": False,
            "/usr/bin/evo status": False,
            "echo evo status": False,
            "": False,
        }
        actual = dict(zip(labels, matches))
        for cmd, want in expected.items():
            assert actual.get(cmd) is want, (
                f"isEvoCommand({cmd!r}): want {want}, got {actual.get(cmd)}"
            )


@unittest.skipUnless(_has_bun(), "bun not on PATH")
class TestMarkEngaged(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.run_dir = _make_inject_dirs(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_register_then_mark_engaged_flips_flag_and_records_timestamp(self):
        run_dir = str(self.run_dir)
        sid = "ts_test_sess"

        _run_ts(f"""
registerSession({json.dumps(run_dir)}, {json.dumps(sid)}, "opencode");
const transitioned = markEngaged({json.dumps(run_dir)}, {json.dumps(sid)});
process.stdout.write(JSON.stringify({{transitioned}}));
""")

        rec_path = self.run_dir / "inject" / "sessions" / f"{sid}.json"
        rec = json.loads(rec_path.read_text())
        assert rec["has_evo_engaged"] is True
        assert rec["engaged_at"] is not None

    def test_mark_engaged_is_idempotent_no_transition_on_second_call(self):
        run_dir = str(self.run_dir)
        sid = "ts_idem"

        out = _run_ts(f"""
registerSession({json.dumps(run_dir)}, {json.dumps(sid)}, "opencode");
const first = markEngaged({json.dumps(run_dir)}, {json.dumps(sid)});
const second = markEngaged({json.dumps(run_dir)}, {json.dumps(sid)});
process.stdout.write(JSON.stringify({{first, second}}));
""")
        assert out["first"] is True, "first call should transition"
        assert out["second"] is False, "second call should be no-op"


@unittest.skipUnless(_has_bun(), "bun not on PATH")
class TestRegisterSessionSeedsOffset(unittest.TestCase):
    """TS register_session must mirror Python's safety contract:
    a freshly registered session has its workspace offset seeded to the
    current queue tail, so pre-registration events don't deliver."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.run_dir = _make_inject_dirs(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_register_session_seeds_offset_to_tail(self):
        run_dir = str(self.run_dir)
        sid = "ts_seed"

        # Pre-stage an event in workspace.jsonl (simulating an old
        # directive queued before this session registers).
        ws_path = self.run_dir / "inject" / "events" / "workspace.jsonl"
        ev_id = "01TEST0000000000000000AAAA"
        ws_path.write_text(json.dumps({
            "schema_version": 1, "id": ev_id, "ts": "2026-01-01T00:00:00+00:00",
            "text": "stale message",
        }) + "\n")

        _run_ts(f"""
registerSession({json.dumps(run_dir)}, {json.dumps(sid)}, "opencode");
""")

        offset_path = self.run_dir / "inject" / "offsets" / f"{sid}.json"
        assert offset_path.exists(), "register_session must create offset file"
        offset = json.loads(offset_path.read_text())
        assert offset["last_workspace_event_id"] == ev_id, (
            f"offset must be seeded to current tail; got {offset!r}"
        )


@unittest.skipUnless(_has_bun(), "bun not on PATH")
class TestPiHostStringInBundle(unittest.TestCase):
    """The pi npm bundle must bind host='pi' (not 'openclaw' as it did
    pre-0.4.4). Test by loading the actual published-bundle file and
    checking the makeRegister call."""

    def test_pi_bundle_binds_host_pi(self):
        bundle = REPO_ROOT / "plugins" / "evo" / "npm" / "extensions" / "evo" / "index.js"
        if not bundle.exists():
            self.skipTest("pi npm bundle not built (run npm/scripts/sync-from-source.sh)")
        text = bundle.read_text()
        assert 'makeRegister("pi")' in text, (
            "pi npm bundle must bind makeRegister('pi'); "
            "if it still binds 'openclaw', the pi-tagged-as-openclaw bug regressed"
        )
        assert 'makeRegister("openclaw")' not in text, (
            "pi npm bundle must NOT bind openclaw"
        )

    def test_openclaw_bundle_binds_host_openclaw(self):
        bundle = (
            REPO_ROOT / "plugins" / "evo" / "src" / "evo" / "openclaw_plugin"
            / "evo.bundle.js"
        )
        if not bundle.exists():
            self.skipTest("openclaw bundle not built")
        text = bundle.read_text()
        assert 'makeRegister("openclaw")' in text


if __name__ == "__main__":
    unittest.main()
