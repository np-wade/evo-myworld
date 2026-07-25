"""Tests for scrapler_eval.provenance — pure stdlib unittest, no network.

Covers: deterministic ts echo (no wall-clock call), git-absent / non-repo
degradation, Heartbeat round-trip + overwrite semantics + atomic write
(no leftover temp), and result_header content.
"""

import glob
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from scrapler_eval import provenance

# A fixed epoch second: 2021-01-01T00:00:00Z. Used everywhere so tests never
# depend on the wall clock.
FIXED_TS = 1609459200.0
FIXED_UTC = "2021-01-01T00:00:00+00:00"

GIT = shutil.which("git")


def _init_repo(path: str) -> None:
    """Init a throwaway git repo with one commit at `path`."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    run = lambda *a: subprocess.run(
        a, cwd=path, env=env, capture_output=True, text=True, check=True
    )
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t.t")
    run("git", "config", "user.name", "t")
    with open(os.path.join(path, "seed.txt"), "w") as fh:
        fh.write("seed\n")
    run("git", "add", "seed.txt")
    run("git", "commit", "-q", "-m", "seed")


class TestStamp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_stamp_has_all_keys(self):
        s = provenance.stamp(FIXED_TS, repo_dir=self.tmp)
        for key in ("git_sha", "git_dirty", "host", "python", "platform",
                    "ts", "utc"):
            self.assertIn(key, s)

    def test_stamp_echoes_passed_ts_no_wallclock(self):
        # If stamp() ever called time.time(), patching it to explode would raise.
        with mock.patch("time.time", side_effect=AssertionError("wall clock!")):
            s = provenance.stamp(FIXED_TS, repo_dir=self.tmp)
        self.assertEqual(s["ts"], FIXED_TS)
        self.assertEqual(s["utc"], FIXED_UTC)

    def test_stamp_outside_repo_is_unknown(self):
        # tmp dir is not a git repo -> sha unknown, dirty False, no crash.
        s = provenance.stamp(FIXED_TS, repo_dir=self.tmp)
        self.assertEqual(s["git_sha"], "unknown")
        self.assertFalse(s["git_dirty"])

    def test_stamp_git_absent_is_unknown(self):
        # Simulate git binary missing everywhere -> "unknown", no crash.
        with mock.patch.object(provenance, "_git", return_value=None):
            s = provenance.stamp(FIXED_TS, repo_dir=self.tmp)
        self.assertEqual(s["git_sha"], "unknown")
        self.assertFalse(s["git_dirty"])

    def test_stamp_types(self):
        s = provenance.stamp(FIXED_TS, repo_dir=self.tmp)
        self.assertIsInstance(s["git_dirty"], bool)
        self.assertIsInstance(s["git_sha"], str)
        self.assertIsInstance(s["utc"], str)

    @unittest.skipUnless(GIT, "git not installed")
    def test_stamp_in_clean_repo(self):
        _init_repo(self.tmp)
        s = provenance.stamp(FIXED_TS, repo_dir=self.tmp)
        self.assertNotEqual(s["git_sha"], "unknown")
        self.assertEqual(len(s["git_sha"]), 40)  # full HEAD sha
        self.assertFalse(s["git_dirty"])

    @unittest.skipUnless(GIT, "git not installed")
    def test_stamp_dirty_repo(self):
        _init_repo(self.tmp)
        with open(os.path.join(self.tmp, "seed.txt"), "a") as fh:
            fh.write("changed\n")
        s = provenance.stamp(FIXED_TS, repo_dir=self.tmp)
        self.assertTrue(s["git_dirty"])


class TestStampLine(unittest.TestCase):
    def test_stamp_line_compact_single_line(self):
        s = provenance.stamp(FIXED_TS, repo_dir=tempfile.gettempdir())
        line = provenance.stamp_line(s)
        self.assertNotIn("\n", line)
        self.assertIn(FIXED_UTC, line)

    def test_stamp_line_shortens_sha_and_flags_dirty(self):
        fake = {
            "git_sha": "abcdef1234567890" + "0" * 24,
            "git_dirty": True,
            "host": "box", "python": "3.14.4", "platform": "Linux",
            "ts": FIXED_TS, "utc": FIXED_UTC,
        }
        line = provenance.stamp_line(fake)
        self.assertIn("sha=abcdef1", line)      # 7-char short sha
        self.assertIn("(dirty)", line)
        self.assertNotIn("abcdef1234567890", line)

    def test_stamp_line_unknown_sha_no_dirty(self):
        fake = {
            "git_sha": "unknown", "git_dirty": False, "host": "box",
            "python": "3.14.4", "platform": "Linux", "ts": FIXED_TS,
            "utc": FIXED_UTC,
        }
        line = provenance.stamp_line(fake)
        self.assertIn("sha=unknown", line)
        self.assertNotIn("(dirty)", line)


class TestHeartbeat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, "heartbeat.txt")
        self.hb = provenance.Heartbeat(self.path, run_id="race42")

    def test_read_before_beat_is_empty(self):
        self.assertEqual(self.hb.read(), "")

    def test_beat_then_read_roundtrips(self):
        written = self.hb.beat("fetching tier0", FIXED_TS)
        read_back = self.hb.read()
        self.assertEqual(read_back, written)
        self.assertIn("[race42]", read_back)
        self.assertIn("fetching tier0", read_back)
        self.assertIn(FIXED_UTC, read_back)

    def test_beat_uses_passed_ts(self):
        with mock.patch("time.time", side_effect=AssertionError("wall clock!")):
            self.hb.beat("x", FIXED_TS)
        self.assertIn(FIXED_UTC, self.hb.read())

    def test_beat_overwrites_not_appends(self):
        self.hb.beat("first message", FIXED_TS)
        self.hb.beat("second message", FIXED_TS + 60)
        content = self.hb.read()
        self.assertIn("second message", content)
        self.assertNotIn("first message", content)
        # exactly one status line
        with open(self.path) as fh:
            raw = fh.read()
        self.assertEqual(raw.count("\n"), 1)

    def test_beat_includes_extra(self):
        line = self.hb.beat("scoring", FIXED_TS, extra={"cand": "curl", "done": 3})
        self.assertIn("cand=curl", line)
        self.assertIn("done=3", line)

    def test_beat_leaves_no_temp_file(self):
        self.hb.beat("clean up", FIXED_TS)
        leftovers = glob.glob(os.path.join(self.tmp, "*.tmp"))
        self.assertEqual(leftovers, [])
        # only the heartbeat file remains
        self.assertEqual(os.listdir(self.tmp), ["heartbeat.txt"])

    def test_beat_returns_written_line(self):
        line = self.hb.beat("returning", FIXED_TS)
        self.assertEqual(line, self.hb.read())


class TestResultHeader(unittest.TestCase):
    def _stamp(self):
        return {
            "git_sha": "deadbeef" + "0" * 32, "git_dirty": True,
            "host": "wslbox", "python": "3.14.4", "platform": "Linux-x86_64",
            "ts": FIXED_TS, "utc": FIXED_UTC,
        }

    def test_header_contains_bracket_and_sha(self):
        header = provenance.result_header(
            self._stamp(), "grand-final", n_candidates=15, n_tasks=42
        )
        self.assertIn("grand-final", header)
        self.assertIn("deadbeef", header)

    def test_header_contains_counts_and_dirty(self):
        header = provenance.result_header(
            self._stamp(), "fetcher-class", n_candidates=5, n_tasks=20
        )
        self.assertIn("5", header)
        self.assertIn("20", header)
        self.assertIn("yes", header)  # dirty flag rendered

    def test_header_is_markdown_with_embedded_stampline(self):
        header = provenance.result_header(
            self._stamp(), "b", n_candidates=1, n_tasks=1
        )
        self.assertTrue(header.startswith("# Scrapler Eval"))
        self.assertIn("<!--", header)  # embedded provenance comment
        self.assertIn(FIXED_UTC, header)


if __name__ == "__main__":
    unittest.main()
