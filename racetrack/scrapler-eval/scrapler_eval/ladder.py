"""Ladder loader — turns fixtures/ladder.json into Task objects.

Pure stdlib. Resolves file:// fixture URLs relative to the fixtures dir so the
frozen tiers are re-runnable with zero network. Live tasks (no answer_key) are
carried through with an absolute/real url; the harness decides whether to run
them based on connectivity.
"""

from __future__ import annotations

import json
from pathlib import Path

from .interface import Task, Tier

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_LADDER = FIXTURES_DIR / "ladder.json"


def _resolve_url(url: str, base: Path) -> str:
    """file://pages/foo.html -> absolute file:// path under the fixtures dir."""
    if url.startswith("file://"):
        rel = url[len("file://"):]
        return "file://" + str((base / rel).resolve())
    return url


def load_ladder(path: str | Path = DEFAULT_LADDER) -> list[Task]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    tasks: list[Task] = []
    for t in data.get("tasks", []):
        tasks.append(Task(
            id=t["id"],
            tier=Tier(t["tier"]),
            url=_resolve_url(t["url"], base),
            answer_key=t.get("answer_key", {}),
            schema=t.get("schema", {}),
            query=t.get("query", ""),
            meta=t.get("meta", {}),
        ))
    return tasks


def load_config(path: str | Path = DEFAULT_LADDER) -> dict:
    """field_stats + weights that go alongside the tasks."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "field_stats": data.get("field_stats", {}),
        "weights": data.get("weights", {}),
    }


def read_fixture_html(task: Task) -> str:
    """Read the frozen HTML for a file:// task. Raises for live tasks."""
    if not task.url.startswith("file://"):
        raise ValueError(f"{task.id} is a live task, not a frozen fixture")
    p = Path(task.url[len("file://"):])
    return p.read_text(encoding="utf-8")
