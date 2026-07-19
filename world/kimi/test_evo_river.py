"""Tests for world/kimi/evo_river.py.

Run with:
    uv run --project plugins/evo --with pytest python -m pytest world/kimi/test_evo_river.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evo_river import (
    _default_graph_fixture,
    _find_best_spine,
    _find_frontier,
    _layout,
    render_river,
)


@pytest.fixture
def graph():
    return _default_graph_fixture()


def test_layout_finds_root_and_levels(graph):
    layout = _layout(graph)
    assert "root" in layout
    assert layout["root"]["level"] == 0
    assert layout["exp_0000"]["level"] == 1
    assert layout["exp_0002"]["level"] == 2


def test_frontier_is_committed_leaf(graph):
    frontier = _find_frontier(graph)
    assert frontier == {"exp_0002"}


def test_best_spine_respects_metric_direction(graph):
    # max -> exp_0000 (score 5.1) is the best committed node
    assert _find_best_spine(graph, "max") == {"root", "exp_0000"}
    # min -> exp_0002 (score 0.01) is the best committed node
    assert _find_best_spine(graph, "min") == {"root", "exp_0000", "exp_0002"}


def test_render_contains_nodes_and_markers(graph):
    out = render_river(graph, metric="min", width=80, use_color=False)
    assert "evo-river" in out
    assert "exp_0000" in out
    assert "exp_0002" in out
    assert "*" in out  # frontier marker
    assert "▲" in out  # spine marker


def test_render_no_color_has_no_ansi_escape(graph):
    out = render_river(graph, use_color=False)
    assert "\033[" not in out


def test_render_with_color_has_ansi_escape(graph):
    out = render_river(graph, use_color=True)
    assert "\033[" in out


def test_fixture_file_loads():
    fixture = Path(__file__).parent / "fixtures" / "demo-graph.json"
    assert fixture.exists()
    data = json.loads(fixture.read_text())
    out = render_river(data, metric="min", use_color=False)
    assert "exp_0004" in out
