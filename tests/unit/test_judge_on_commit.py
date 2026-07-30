"""Tests for the opt-in on-commit LLM-as-judge hook (no real model calls)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evo import cli, judges
from evo.core import experiments_path


def _write_diff(root: Path, exp_id: str, attempt: int, text: str) -> None:
    d = experiments_path(root) / exp_id / "attempts" / f"{attempt:03d}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "diff.patch").write_text(text, encoding="utf-8")


DIFF = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@\n+print('hi')\n"


def test_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("EVO_JUDGE_ON_COMMIT", raising=False)
    _write_diff(tmp_path, "exp_0001", 1, DIFF)
    assert cli._maybe_judge_commit(tmp_path, "exp_0001", {}, {}, 1) is None


def test_enabled_via_env_scores_diff(tmp_path, monkeypatch):
    monkeypatch.setenv("EVO_JUDGE_ON_COMMIT", "minimal_change")
    monkeypatch.setattr(judges, "claude_call",
                        lambda *a, **k: '{"score": 9, "reason": "tight"}')
    _write_diff(tmp_path, "exp_0001", 1, DIFF)
    out = cli._maybe_judge_commit(tmp_path, "exp_0001", {"hypothesis": "add greeting"}, {}, 1)
    assert out is not None
    assert out["name"] == "g_eval_minimal_change"
    assert out["value"] == pytest.approx(0.9)


def test_enabled_via_config(tmp_path, monkeypatch):
    monkeypatch.delenv("EVO_JUDGE_ON_COMMIT", raising=False)
    monkeypatch.setattr(judges, "claude_call",
                        lambda *a, **k: '{"score": 4, "reason": "meh"}')
    _write_diff(tmp_path, "exp_0001", 1, DIFF)
    out = cli._maybe_judge_commit(tmp_path, "exp_0001", {}, {"judge_on_commit": "diff_matches_brief"}, 1)
    assert out["name"] == "g_eval_diff_matches_brief"
    assert out["value"] == pytest.approx(0.4)


def test_missing_diff_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("EVO_JUDGE_ON_COMMIT", "minimal_change")
    assert cli._maybe_judge_commit(tmp_path, "exp_0001", {}, {}, 1) is None


def test_judge_failure_is_swallowed(tmp_path, monkeypatch):
    monkeypatch.setenv("EVO_JUDGE_ON_COMMIT", "minimal_change")
    def _boom(*a, **k):
        raise judges.JudgeError("model exploded")
    monkeypatch.setattr(judges, "claude_call", _boom)
    _write_diff(tmp_path, "exp_0001", 1, DIFF)
    # Best-effort: a judge failure must never propagate out of a commit.
    assert cli._maybe_judge_commit(tmp_path, "exp_0001", {}, {}, 1) is None
