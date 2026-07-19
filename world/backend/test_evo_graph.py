"""Tests for evo_graph.py against the REAL graphify index.db (read-only).

Skips cleanly when the graphify data dir is absent (e.g. CI, other boxes).
Run: python3 -m pytest world/backend/test_evo_graph.py -q
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evo_graph  # noqa: E402

DATA = evo_graph.data_root()
DB = os.path.join(DATA, "index.db")
GRAPHS = os.path.join(DATA, "graphs")

needs_db = pytest.mark.skipif(
    not os.path.exists(DB), reason=f"index.db not present at {DB}"
)
needs_slices = pytest.mark.skipif(
    not os.path.isdir(GRAPHS), reason=f"graphs dir not present at {GRAPHS}"
)


# ── unit-ish helpers (no DB needed) ──────────────────────────────────

def test_query_terms_drops_stopwords():
    assert evo_graph._query_terms("how does the dedup cache work?") == [
        "dedup", "cache", "work"
    ]


def test_query_terms_all_stopword_fallback():
    # all stopwords -> fall back to unfiltered terms, never empty
    assert evo_graph._query_terms("what is the") != []


def test_fts_query_neutralizes_operators():
    q = evo_graph._fts_query(['near', 'a"b'])
    assert q == '"near" AND "a""b"'


# ── find, against real index.db ──────────────────────────────────────

@needs_db
def test_find_returns_hits(capsys):
    rc = evo_graph.main(["find", "dedup", "--limit", "5"])
    out = capsys.readouterr().out.strip().splitlines()
    assert rc == 0
    assert 1 <= len(out) <= 5
    assert "dedup" in out[0].lower()


@needs_db
def test_find_repo_filter(capsys):
    rc = evo_graph.main(
        ["find", "gateway", "--repo", "tencentdb", "--limit", "5"]
    )
    out = capsys.readouterr().out.strip().splitlines()
    assert rc == 0
    assert out and all("tencentdb" in line for line in out)


@needs_db
def test_find_punctuation_does_not_crash(capsys):
    rc = evo_graph.main(["find", 'evict(NEAR)"lru*', "--limit", "3"])
    assert rc == 0  # hits or the graceful "no hits" message — never a crash


@needs_db
def test_find_limit_respected(capsys):
    rc = evo_graph.main(["find", "cache", "--limit", "2"])
    out = capsys.readouterr().out.strip().splitlines()
    assert rc == 0
    assert len(out) == 2


@needs_db
def test_db_opened_read_only():
    con = evo_graph._connect(DB)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("CREATE TABLE _evo_scratch(x)")
    con.close()


# ── slice, against real data/graphs ──────────────────────────────────

@needs_slices
def test_slice_lookup_with_topic(capsys):
    rc = evo_graph.main(["slice", "tencentdb-agent-memory", "--topic", "fts"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "topic_terms" in out and ".json" in out


@needs_slices
def test_slice_unknown_repo_fails_gracefully(capsys):
    rc = evo_graph.main(["slice", "no-such-repo-zzz"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "no graph dir matching" in err


# ── graceful failure when data root is wrong ─────────────────────────

def test_missing_db_exits_2(monkeypatch, capsys):
    monkeypatch.setenv("GRAPHIFY_DATA", "/nonexistent-evo-graph-test")
    rc = evo_graph.main(["find", "dedup"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "index.db not found" in err


def test_missing_graphs_dir_exits_2(monkeypatch, capsys):
    monkeypatch.setenv("GRAPHIFY_DATA", "/nonexistent-evo-graph-test")
    rc = evo_graph.main(["slice", "graphify"])
    assert rc == 2
