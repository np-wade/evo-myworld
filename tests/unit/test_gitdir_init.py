"""Tests for gitdir-mode workspace init, the claude-science host adapter, and
the base-repo git-env hook.

Covers the pieces that make `evo` runnable where `.git` creation is forbidden:
`evo init --backend gitdir` / `--host claude-science` relocates the base repo
off `.git`; `maybe_apply_gitdir_env` re-applies the base GIT_DIR on later
commands; `evo install claude-science` sets the machine default. Real git, no
mocks.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from evo import core
from evo.backends.gitdir import base_gitdir, base_git_env
from evo.core import find_workspace_root, init_workspace, maybe_apply_gitdir_env


def _no_dotgit(root: Path) -> list[str]:
    return [str(p) for p in root.rglob(".git")]


class _EnvIsolation(unittest.TestCase):
    """Snapshot/restore os.environ so git-env mutations don't leak between tests."""

    def setUp(self):
        self._env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)


class TestFindWorkspaceRoot(unittest.TestCase):
    def test_walks_up_to_evo(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root / ".evo").mkdir()
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            self.assertEqual(find_workspace_root(nested), root)

    def test_none_outside_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(find_workspace_root(Path(d)))


class TestGitDirInit(_EnvIsolation):
    def test_init_backend_gitdir_is_git_free_with_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root / "code.py").write_text("x = 1\n")

            run_id = init_workspace(
                root, target="code.py", benchmark="true", metric="max",
                gate=None, host="generic", backend="gitdir",
            )
            self.assertTrue(run_id)

            cfg = json.loads((core.config_path(root)).read_text())
            self.assertEqual(cfg["execution_backend"], "gitdir")

            # Base repo relocated off `.git`, with a baseline commit.
            gd = base_gitdir(root)
            self.assertTrue(gd.is_dir())
            self.assertEqual(_no_dotgit(root), [])   # nothing named `.git` anywhere
            env = {**os.environ, **base_git_env(root)}
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                                  env=env, capture_output=True, text=True)
            self.assertEqual(head.returncode, 0)
            # The target file is tracked; evo's own state is not.
            tracked = subprocess.run(["git", "ls-files"], cwd=str(root), env=env,
                                     capture_output=True, text=True).stdout
            self.assertIn("code.py", tracked)
            self.assertNotIn(".evo/", tracked)

    def test_host_claude_science_relocates_even_without_gitdir_flag(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            init_workspace(root, target=".", benchmark="true", metric="max",
                           gate=None, host="claude-science", backend="gitdir")
            self.assertTrue(base_gitdir(root).is_dir())
            self.assertEqual(_no_dotgit(root), [])

    def test_worktree_init_does_not_relocate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            init_workspace(root, target=".", benchmark="true", metric="max",
                           gate=None, host="generic", backend="worktree")
            cfg = json.loads((core.config_path(root)).read_text())
            self.assertEqual(cfg["execution_backend"], "worktree")
            self.assertFalse(base_gitdir(root).exists())  # no relocation


class TestGitDirEnvHook(_EnvIsolation):
    def test_applies_base_env_for_relocated_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            init_workspace(root, target=".", benchmark="true", metric="max",
                           gate=None, host="generic", backend="gitdir")
            os.environ.pop("GIT_DIR", None)
            os.environ.pop("GIT_WORK_TREE", None)

            applied = maybe_apply_gitdir_env(root)
            self.assertTrue(applied)
            self.assertEqual(os.environ["GIT_DIR"], str(base_gitdir(root)))
            self.assertEqual(os.environ["GIT_WORK_TREE"], str(root))

    def test_noop_for_normal_dir(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ.pop("GIT_DIR", None)
            self.assertFalse(maybe_apply_gitdir_env(Path(d)))
            self.assertNotIn("GIT_DIR", os.environ)


class TestClaudeScienceHostAdapter(_EnvIsolation):
    def test_install_sets_gitdir_default_doctor_uninstall(self):
        from evo.host_install import ADAPTERS, SUPPORTED_HOSTS
        from evo import user_defaults

        self.assertIn("claude-science", SUPPORTED_HOSTS)
        self.assertIn("claude-science", core.SUPPORTED_HOSTS)
        adapter = ADAPTERS["claude-science"]

        with tempfile.TemporaryDirectory() as home:
            os.environ["EVO_HOME"] = home  # isolate user defaults
            ns = argparse.Namespace()

            self.assertEqual(adapter.install(ns), 0)
            self.assertEqual(
                user_defaults.get_user_default_str("execution_backend"), "gitdir")
            self.assertEqual(adapter.doctor(ns), 0)

            self.assertEqual(adapter.uninstall(ns), 0)
            self.assertIsNone(
                user_defaults.get_user_default_str("execution_backend"))
            self.assertEqual(adapter.doctor(ns), 1)  # no longer configured


if __name__ == "__main__":
    unittest.main()
