"""Graph-candidates contract — mostly pure; one live builder test (skips w/o DB)."""
import os

import pytest

from evo.graph.candidates import (
    CandidateSet, GraphCandidate, build_candidates, LICENSE_UNVERIFIED,
)
from evo.graph.store import GraphStore, Hit, default_data_root

DB = os.path.join(default_data_root(), "index.db")
needs_db = pytest.mark.skipif(not os.path.exists(DB), reason=f"index.db absent at {DB}")


def _hit(repo="repo__a", label="f()", node="n1", degree=5):
    return Hit(repo_id=repo, node_id=node, label=label, norm_label=label.lower(),
               kind="function", source_file="f.py", loc=10, degree=degree)


def test_candidate_from_hit_defaults_license_unverified():
    c = GraphCandidate.from_hit(_hit(), need="cache", query="cache")
    assert c.license == LICENSE_UNVERIFIED
    assert c.source_location == "f.py:10"
    assert c.repo_id == "repo__a"


def test_candidate_json_roundtrip():
    c = GraphCandidate.from_hit(_hit(), need="cache", query="cache",
                                expected_benefit="reuse", suggested_test="race it")
    c2 = GraphCandidate.from_dict(c.to_dict())
    assert c2 == c


def test_candidate_from_dict_ignores_unknown_keys():
    c = GraphCandidate.from_dict({"need": "n", "query": "q", "repo_id": "r",
                                  "label": "l", "bogus": 123})
    assert c.repo_id == "r" and not hasattr(c, "bogus")


def test_candidateset_dedups_same_symbol():
    cs = CandidateSet(need="cache")
    assert cs.add(GraphCandidate(need="cache", query="c", repo_id="r", label="f", node_id="n1"))
    # same repo+node -> rejected
    assert not cs.add(GraphCandidate(need="cache", query="c", repo_id="r", label="f", node_id="n1"))
    assert len(cs) == 1


def test_rerank_interleaves_repos_for_diversity():
    cs = CandidateSet(need="cache")
    for i in range(3):
        cs.add(GraphCandidate(need="cache", query="c", repo_id="repoA", label=f"a{i}", node_id=f"a{i}", degree=100 - i))
    cs.add(GraphCandidate(need="cache", query="c", repo_id="repoB", label="b0", node_id="b0", degree=1))
    cs.rerank(prefer_repo_diversity=True)
    # repoB (low degree) is lifted to 2nd slot by interleaving, not buried last
    assert cs.candidates[0].repo_id == "repoA"
    assert cs.candidates[1].repo_id == "repoB"
    assert [c.rank for c in cs.candidates] == [0, 1, 2, 3]


def test_candidateset_json_roundtrip():
    cs = CandidateSet(need="cache", queries=["cache"])
    cs.add(GraphCandidate(need="cache", query="cache", repo_id="r", label="f", node_id="n"))
    cs2 = CandidateSet.from_json(cs.to_json())
    assert cs2.need == cs.need and len(cs2) == 1 and cs2.candidates[0].label == "f"


def test_markdown_notes_when_empty():
    cs = CandidateSet(need="nothing")
    assert "No graph candidates" in cs.to_markdown()


def test_markdown_lists_license_warning():
    cs = CandidateSet(need="cache")
    cs.add(GraphCandidate(need="cache", query="c", repo_id="r", label="f", node_id="n"))
    md = cs.to_markdown()
    assert "verify before vendoring" in md


# ── live builder against the real index ──────────────────────────────────────

@needs_db
def test_build_candidates_live_returns_provenance():
    store = GraphStore()
    cs = build_candidates(store, "dedup cache", per_query=4, total=6)
    store.close()
    assert cs.index_built_at  # provenance stamp from meta
    if cs.candidates:  # FTS may legitimately miss; if it hits, invariants hold
        assert all(c.license == LICENSE_UNVERIFIED for c in cs)
        assert all(c.retrieved_at for c in cs)
        # ranks are contiguous from 0
        assert [c.rank for c in cs.candidates] == list(range(len(cs)))


def test_build_candidates_unavailable_is_soft(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_DATA", "/nonexistent-evo-graph")
    store = GraphStore()
    cs = build_candidates(store, "anything")
    store.close()
    assert len(cs) == 0 and "unavailable" in cs.note
