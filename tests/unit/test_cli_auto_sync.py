"""Tests for `evo install/update <host>` auto-syncing the global CLI.

Background: skills, hooks, and the CLI binary share wire formats — if
they drift, the steering layer fails in ways that look mysterious from
the agent's perspective. `bin/evo-version-check` is a defense-in-depth
script that surfaces the drift at skill-startup time, but auto-sync
prevents it from appearing in the first place.

These tests exercise `_sync_cli_to_plugin_version` against the three
real environments:
  - editable install (dev workflow — auto-sync should skip)
  - regular install + `--version X` (sync to that PyPI release)
  - regular install + `--from-path Y` (warn but don't auto-install
    editable, since that'd be surprising)
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "evo" / "src"))


class _Base(unittest.TestCase):

    def setUp(self):
        from evo import host_install
        host_install._cli_synced_this_run = False

    def _args(self, **kw):
        ns = argparse.Namespace()
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns


class TestEditableDetection(_Base):

    def test_returns_true_when_evo_module_outside_site_packages(self):
        """In this test process, evo is imported from the working tree
        (not site-packages), so editable detection should be True."""
        from evo.host_install import _is_editable_evo_install
        self.assertTrue(_is_editable_evo_install())


class TestSyncSkipsEditable(_Base):

    def test_editable_install_does_not_call_uv(self):
        """The most important behavior: a dev with a `pip install -e` or
        `uv tool install --editable` setup should NEVER have their
        editable install clobbered by auto-sync."""
        from evo.host_install import _sync_cli_to_plugin_version
        with patch("evo.host_install.subprocess.call") as mock_call:
            rc = _sync_cli_to_plugin_version(self._args(version=None, from_path=None))
        self.assertEqual(rc, 0)
        mock_call.assert_not_called()

    def test_editable_install_with_from_path_prints_hint(self):
        from evo.host_install import _sync_cli_to_plugin_version
        with patch("evo.host_install.subprocess.call") as mock_call:
            with patch("builtins.print") as mock_print:
                _sync_cli_to_plugin_version(self._args(version=None, from_path="/x"))
        mock_call.assert_not_called()
        printed = "\n".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("editable", printed.lower())


class TestSyncWithVersion(_Base):

    def test_pypi_release_version_calls_uv_with_pin(self):
        """When CLI is not editable, --version X.Y.Z bumps the CLI to
        that exact PyPI release."""
        from evo import host_install
        with patch("evo.host_install._is_editable_evo_install", return_value=False), \
             patch("evo.host_install.subprocess.call", return_value=0) as mock_call:
            host_install._sync_cli_to_plugin_version(self._args(version="0.4.5", from_path=None))
        mock_call.assert_called_once_with(
            ["uv", "tool", "install", "--force", "evo-hq-cli==0.4.5"]
        )

    def test_no_version_calls_uv_for_latest(self):
        from evo import host_install
        with patch("evo.host_install._is_editable_evo_install", return_value=False), \
             patch("evo.host_install.subprocess.call", return_value=0) as mock_call:
            host_install._sync_cli_to_plugin_version(self._args(version=None, from_path=None))
        mock_call.assert_called_once_with(
            ["uv", "tool", "install", "--force", "evo-hq-cli"]
        )

    def test_branch_version_does_not_call_uv(self):
        """Branch names like 'main' or 'v0.4.4' aren't on PyPI. uv tool
        install would fail. Skip the CLI sync and let the user know."""
        from evo import host_install
        with patch("evo.host_install._is_editable_evo_install", return_value=False), \
             patch("evo.host_install.subprocess.call") as mock_call:
            with patch("builtins.print") as mock_print:
                host_install._sync_cli_to_plugin_version(
                    self._args(version="main", from_path=None)
                )
        mock_call.assert_not_called()
        printed = "\n".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("not a", printed.lower())


class TestSyncWithFromPath(_Base):

    def test_from_path_on_non_editable_warns(self):
        """User installed plugin from a local checkout but the CLI is a
        normal PyPI install. The two will diverge. Print a hint with the
        exact `uv tool install --editable` command but don't auto-run
        it (might be surprising)."""
        from evo import host_install
        with patch("evo.host_install._is_editable_evo_install", return_value=False), \
             patch("evo.host_install.subprocess.call") as mock_call:
            with patch("builtins.print") as mock_print:
                host_install._sync_cli_to_plugin_version(
                    self._args(version=None, from_path="/Users/me/evo-checkout")
                )
        mock_call.assert_not_called()
        printed = "\n".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("uv tool install --force --editable", printed)


class TestIdempotenceGuard(_Base):

    def test_second_call_is_noop(self):
        """`evo update` (bare) iterates over many hosts. The wrapper
        calls sync after each. Only the first should actually do
        anything; the rest must no-op."""
        from evo import host_install
        with patch("evo.host_install._is_editable_evo_install", return_value=False), \
             patch("evo.host_install.subprocess.call", return_value=0) as mock_call:
            host_install._sync_cli_to_plugin_version(self._args(version=None, from_path=None))
            host_install._sync_cli_to_plugin_version(self._args(version=None, from_path=None))
            host_install._sync_cli_to_plugin_version(self._args(version=None, from_path=None))
        self.assertEqual(
            mock_call.call_count, 1,
            "subsequent sync calls must no-op once flag is set"
        )

    def test_editable_skip_also_sets_guard(self):
        """Editable-skip path must also flip the guard, otherwise
        bare-update would re-attempt sync for each host."""
        from evo import host_install
        with patch("evo.host_install.subprocess.call") as mock_call:
            host_install._sync_cli_to_plugin_version(self._args(version=None, from_path=None))
            self.assertTrue(host_install._cli_synced_this_run)
            # Subsequent call with non-editable should still no-op:
            with patch("evo.host_install._is_editable_evo_install", return_value=False):
                host_install._sync_cli_to_plugin_version(
                    self._args(version="0.4.5", from_path=None)
                )
        mock_call.assert_not_called()


class TestWrapperWiring(_Base):

    def test_install_wrapper_calls_sync_on_success(self):
        from evo import host_install
        with patch.object(host_install.claude_code, "install", return_value=0), \
             patch("evo.host_install._sync_cli_to_plugin_version") as mock_sync:
            host_install.install("claude-code", self._args(version=None, from_path=None))
        mock_sync.assert_called_once()

    def test_install_wrapper_skips_sync_on_failure(self):
        """If the host install itself failed, don't sync the CLI —
        the user has a broken plugin install to deal with first."""
        from evo import host_install
        with patch.object(host_install.claude_code, "install", return_value=1), \
             patch("evo.host_install._sync_cli_to_plugin_version") as mock_sync:
            host_install.install("claude-code", self._args(version=None, from_path=None))
        mock_sync.assert_not_called()

    def test_update_wrapper_calls_sync_on_success(self):
        from evo import host_install
        with patch.object(host_install.claude_code, "update", return_value=0), \
             patch("evo.host_install._sync_cli_to_plugin_version") as mock_sync:
            host_install.update("claude-code", self._args(version=None, from_path=None))
        mock_sync.assert_called_once()

    def test_update_falls_back_to_install_then_syncs(self):
        """Hosts without their own `update()` use `install()` as fallback;
        sync should still fire afterward."""
        from evo import host_install
        # Codex has no update() (delegates to install). Verify by patching
        # codex.install and confirming sync runs.
        with patch.object(host_install.codex, "install", return_value=0), \
             patch("evo.host_install._sync_cli_to_plugin_version") as mock_sync:
            host_install.update("codex", self._args(version=None, from_path=None))
        mock_sync.assert_called_once()


if __name__ == "__main__":
    unittest.main()
