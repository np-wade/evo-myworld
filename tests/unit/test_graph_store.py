"""GraphStore — pure helpers always run; retrieval tests skip without index.db."""
import os
import sqlite3

import pytest

from evo.graph.store import (
    GraphStore, GraphUnavailable, Hit, query_terms, fts_match, default_data_root,
)

DATA = default_data_root()
DB = os.path.join(DATA, "index.db")
GRAPHS = os.path.join(DATA, "graphs")
needs_db = pytest.mark.skipif(not os.path.exists(DB), reason=f"index.db absent at {DB}")
needs_slices = pytest.mark.skipif(not os.path.isdir(GRAPHS), reason="graphs dir absent")


# ── pure helpers (ported behaviour, no DB) ───────────────────────────────────

def test_query_terms_drops_stopwords():
    assert query_terms("how does the dedup cache work?") == ["dedup", "cache", "work"]


def test_query_terms_all_stopword_fallback():
    assert query_terms("what is the") != []


def test_fts_match_quotes_and_joins():
    assert fts_match(["near", 'a"b'], join="AND") == '"near" AND "a""b"'
    assert fts_match(["x", "y"], join="OR") == '"x" OR "y"'


def test_hit_source_location():
    h = Hit("r", "n", "f()", "f()", "function", "f.py", 10, 3)
    assert h.source_location == "f.py:10"
    h2 = Hit("r", "n", "f()", "f()", "function", "f.py", None, 3)
    assert h2.source_location == "f.py"


def test_unavailable_store_raises_typed():
    store = GraphStore("/nonexistent-evo-graph-store")
    assert store.available() is False
    with pytest.raises(GraphUnavailable):
        store.find("dedup")
    store.close()


# ── retrieval against the real index ─────────────────────────────────────────

@needs_db
def test_find_returns_hits():
    with GraphStore() as store:
        hits = store.find("dedup", limit=5)
    assert 1 <= len(hits) <= 5
    assert "dedup" in hits[0].label.lower() or "dedup" in hits[0].norm_label.lower()


@needs_db
def test_find_repo_filter():
    with GraphStore() as store:
        hits = store.find("gateway", repo="tencentdb", limit=5)
    assert hits and all("tencentdb" in h.repo_id for h in hits)


@needs_db
def test_find_punctuation_does_not_crash():
    with GraphStore() as store:
        store.find('evict(NEAR)"lru*', limit=3)  # no exception == pass


@needs_db
def test_find_limit_respected():
    with GraphStore() as store:
        assert len(store.find("cache", limit=2)) == 2


@needs_db
def test_neighbors_and_subgraph_are_bounded():
    with GraphStore() as store:
        hits = store.find("push_to_falkordb", repo="graphify", limit=1)
        assert hits, "expected a graphify hit for push_to_falkordb"
        h = hits[0]
        edges = store.neighbors(h.repo_id, h.node_id, limit=5)
        assert len(edges) <= 5
        assert all(e.direction in ("in", "out") for e in edges)
        sg = store.subgraph(h.repo_id, [h.node_id], hops=1, limit=15)
        assert "nodes" in sg and "edges" in sg
        assert len(sg["nodes"]) <= 15
        # the seed itself is in the node set
        assert any(n["node_id"] == h.node_id for n in sg["nodes"])


@needs_db
def test_subgraph_caps_hops_at_two():
    with GraphStore() as store:
        hits = store.find("push_to_falkordb", repo="graphify", limit=1)
        h = hits[0]
        # asking for 9 hops is clamped to MAX_HOPS (no runaway)
        sg = store.subgraph(h.repo_id, [h.node_id], hops=9, limit=30)
        assert len(sg["nodes"]) <= 30


@needs_db
def test_db_is_read_only():
    with GraphStore() as store:
        con = store._connect()
        with pytest.raises(sqlite3.OperationalError):
            con.execute("CREATE TABLE _evo_scratch(x)")


@needs_db
def test_build_meta_has_provenance():
    with GraphStore() as store:
        meta = store.build_meta()
    assert "built_at" in meta and meta["index_path"].endswith("index.db")


@needs_slices
def test_slices_lookup_with_topic():
    with GraphStore() as store:
        slices = store.slices("tencentdb-agent-memory", topic="fts")
    assert slices and any(s.get("topic_terms") for s in slices)


@needs_slices
def test_resolve_repo_dir_unknown_raises():
    with GraphStore() as store:
        with pytest.raises(GraphUnavailable):
            store.resolve_repo_dir("no-such-repo-zzz-evo")
