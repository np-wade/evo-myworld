"""Tests for the `gitdir` execution backend.

The backend's contract: isolate each experiment like the worktree backend, but
never create any path named `.git` (files or dirs) in the experiment workspace,
so it runs in sandboxes that forbid `.git` creation. These tests use real git
subprocesses -- no mocks -- and assert the `.git`-free invariant directly.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from evo.backends import GitDirBackend, load_backend, _construct_backend
from evo.backends.gitdir import git_env, gitdir_for
from evo.backends.protocol import AllocateCtx, DiscardCtx


def _init_base_repo(root: Path) -> str:
    """A normal git repo with one commit. Returns the commit hash."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@evo"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)
    (root / "README.md").write_text("base\n")
    (root / "code.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True,
        capture_output=True, text=True,
    )
    return out.stdout.strip()


def _setup_workspace(root: Path, run_id: str = "run_0000") -> None:
    """Minimal `.evo` layout so core.workspace_path()/worktrees_path() resolve."""
    evo = root / ".evo"
    evo.mkdir(exist_ok=True)
    (evo / "meta.json").write_text(json.dumps({"active": run_id}))
    (evo / run_id).mkdir(exist_ok=True)


def _ctx(root: Path, exp_id: str, parent_commit: str) -> AllocateCtx:
    return AllocateCtx(
        root=root,
        exp_id=exp_id,
        parent_node=None,
        parent_commit=parent_commit,
        parent_ref=parent_commit,
        branch=f"evo/run_0000/{exp_id}",
        hypothesis="test hypothesis",
    )


def _no_dotgit_anywhere(path: Path) -> list[str]:
    """Return any paths literally named `.git` under `path` (should be empty)."""
    return [str(p) for p in path.rglob(".git")]


class TestGitDirRegistration(unittest.TestCase):
    def test_construct_and_load(self):
        self.assertIsInstance(_construct_backend("gitdir", {}), GitDirBackend)
        self.assertEqual(GitDirBackend().name, "gitdir")

    def test_cli_arg_resolution_accepts_gitdir(self):
        from evo.cli import _resolve_backend_cli_args
        with tempfile.TemporaryDirectory() as d:
            name, cfg = _resolve_backend_cli_args(
                root=Path(d), backend="gitdir", workspaces_raw=None,
                provider=None, provider_config_raw=None, remote=None,
                require_backend=True,
            )
            self.assertEqual((name, cfg), ("gitdir", {}))


class TestGitDirAllocate(unittest.TestCase):
    def test_allocate_is_git_free_and_at_parent_commit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            parent = _init_base_repo(root)
            _setup_workspace(root)

            res = GitDirBackend().allocate(_ctx(root, "exp_0001", parent))

            # Working tree materialized from the parent commit's tree.
            self.assertTrue(res.worktree.exists())
            self.assertEqual((res.worktree / "README.md").read_text(), "base\n")
            self.assertEqual((res.worktree / "code.py").read_text(), "x = 1\n")
            self.assertEqual(res.commit, parent)
            self.assertEqual(res.branch, "evo/run_0000/exp_0001")

            # The core invariant: NO `.git` path in the experiment workspace.
            self.assertEqual(_no_dotgit_anywhere(res.worktree), [])
            self.assertFalse((res.worktree / ".git").exists())

            # The relocated git dir exists (under an allowed name, not `.git`).
            gd = gitdir_for(root, "exp_0001")
            self.assertTrue(gd.is_dir())
            self.assertNotEqual(gd.name, ".git")

    def test_objects_are_shared_via_alternates_not_copied(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            parent = _init_base_repo(root)
            _setup_workspace(root)
            GitDirBackend().allocate(_ctx(root, "exp_0001", parent))

            gd = gitdir_for(root, "exp_0001")
            alternates = gd / "objects" / "info" / "alternates"
            self.assertTrue(alternates.is_file())
            self.assertIn(".git/objects", alternates.read_text())
            # The parent commit resolves in the exp repo purely via the shared
            # store -- the exp git dir did not duplicate the base pack.
            env = git_env(gd, root / ".evo" / "run_0000" / "worktrees" / "exp_0001")
            r = subprocess.run(
                ["git", "cat-file", "-e", f"{parent}^{{commit}}"],
                cwd=str(root), env={**os.environ, **env}, capture_output=True,
            )
            self.assertEqual(r.returncode, 0)

    def test_missing_parent_commit_raises(self):
        from evo.backends.protocol import BackendError
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _init_base_repo(root)
            _setup_workspace(root)
            bogus = "0" * 40
            with self.assertRaises(BackendError):
                GitDirBackend().allocate(_ctx(root, "exp_0009", bogus))


class TestGitDirCommitPath(unittest.TestCase):
    """The `evo run` commit strategy routes git through the executor from
    workspace_executor_for; for gitdir that injects the relocated GIT_DIR."""

    def test_commit_via_executor_makes_real_commit_no_dotgit(self):
        from evo.core import maybe_commit_worktree
        from evo.workspace_executor import workspace_executor_for

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            parent = _init_base_repo(root)
            _setup_workspace(root)
            res = GitDirBackend().allocate(_ctx(root, "exp_0001", parent))

            # The inner agent edits the worktree.
            (res.worktree / "code.py").write_text("x = 2  # improved\n")

            node = {"id": "exp_0001", "worktree": str(res.worktree),
                    "branch": res.branch}
            backend = GitDirBackend()
            with workspace_executor_for(backend, root, node) as executor:
                new_commit = maybe_commit_worktree(
                    node, "improve code", commit_strategy="all", executor=executor,
                )

            self.assertIsNotNone(new_commit)
            self.assertNotEqual(new_commit, parent)
            # Still no `.git` anywhere in the workspace after committing.
            self.assertEqual(_no_dotgit_anywhere(res.worktree), [])
            # The new commit is real and carries the edit.
            env = git_env(gitdir_for(root, "exp_0001"), res.worktree)
            show = subprocess.run(
                ["git", "show", "--stat", new_commit],
                cwd=str(root), env={**os.environ, **env},
                capture_output=True, text=True,
            )
            self.assertEqual(show.returncode, 0)
            self.assertIn("code.py", show.stdout)

    def test_no_op_commit_returns_head(self):
        from evo.core import maybe_commit_worktree
        from evo.workspace_executor import workspace_executor_for
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            parent = _init_base_repo(root)
            _setup_workspace(root)
            res = GitDirBackend().allocate(_ctx(root, "exp_0001", parent))
            node = {"id": "exp_0001", "worktree": str(res.worktree), "branch": res.branch}
            with workspace_executor_for(GitDirBackend(), root, node) as executor:
                head = maybe_commit_worktree(node, "noop", executor=executor)
            self.assertEqual(head, parent)  # no edits -> HEAD unchanged


class TestGitDirIsolationAndTeardown(unittest.TestCase):
    def test_two_experiments_are_independent(self):
        from evo.core import maybe_commit_worktree
        from evo.workspace_executor import workspace_executor_for
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            parent = _init_base_repo(root)
            _setup_workspace(root)
            backend = GitDirBackend()

            r1 = backend.allocate(_ctx(root, "exp_0001", parent))
            r2 = backend.allocate(_ctx(root, "exp_0002", parent))

            (r1.worktree / "code.py").write_text("x = 11\n")
            (r2.worktree / "code.py").write_text("x = 22\n")
            n1 = {"id": "exp_0001", "worktree": str(r1.worktree), "branch": r1.branch}
            n2 = {"id": "exp_0002", "worktree": str(r2.worktree), "branch": r2.branch}
            with workspace_executor_for(backend, root, n1) as ex1:
                c1 = maybe_commit_worktree(n1, "a", executor=ex1)
            with workspace_executor_for(backend, root, n2) as ex2:
                c2 = maybe_commit_worktree(n2, "b", executor=ex2)

            self.assertNotEqual(c1, c2)
            self.assertEqual((r1.worktree / "code.py").read_text(), "x = 11\n")
            self.assertEqual((r2.worktree / "code.py").read_text(), "x = 22\n")
            self.assertEqual(_no_dotgit_anywhere(r1.worktree), [])
            self.assertEqual(_no_dotgit_anywhere(r2.worktree), [])

    def test_discard_removes_worktree_and_gitdir(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            parent = _init_base_repo(root)
            _setup_workspace(root)
            backend = GitDirBackend()
            res = backend.allocate(_ctx(root, "exp_0001", parent))
            gd = gitdir_for(root, "exp_0001")
            self.assertTrue(res.worktree.exists() and gd.exists())

            backend.discard(DiscardCtx(root=root, node={
                "id": "exp_0001", "worktree": str(res.worktree), "branch": res.branch,
            }))
            self.assertFalse(res.worktree.exists())
            self.assertFalse(gd.exists())

    def test_sweep_orphans_reclaims_unknown_experiments(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            parent = _init_base_repo(root)
            _setup_workspace(root)
            backend = GitDirBackend()
            backend.allocate(_ctx(root, "exp_0001", parent))
            backend.allocate(_ctx(root, "exp_0002", parent))

            removed = backend.sweep_orphans(root, live_exp_ids={"exp_0001"})
            # exp_0002's worktree and gitdir are reclaimed; exp_0001 survives.
            self.assertTrue(any("exp_0002" in r for r in removed))
            self.assertFalse(gitdir_for(root, "exp_0002").exists())
            self.assertTrue(gitdir_for(root, "exp_0001").exists())


if __name__ == "__main__":
    unittest.main()
