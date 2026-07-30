"""Experiment evidence graph — fully hermetic (temp SQLite, no library index)."""
import json

import pytest

from evo.graph import schema
from evo.graph.writeback import EvidenceGraph, sha256_bytes
from evo.graph.candidates import CandidateSet, GraphCandidate


@pytest.fixture
def eg(tmp_path):
    g = EvidenceGraph.open_for_workspace(tmp_path)
    yield g
    g.close()


def test_schema_and_meta(eg):
    st = eg.stats()
    assert st["schema_version"] == schema.SCHEMA_VERSION
    assert st["nodes"] == 0 and st["edges"] == 0


def test_upsert_node_is_idempotent_and_merges(eg):
    eg.upsert_node("exp:1", schema.EXPERIMENT, "first", score=0.5)
    eg.upsert_node("exp:1", schema.EXPERIMENT, "first", commit="abc")
    n = eg.get_node("exp:1")
    # both attrs survive the merge; not two rows
    assert n.attrs["score"] == 0.5 and n.attrs["commit"] == "abc"
    assert eg.stats()["nodes"] == 1


def test_upsert_node_rejects_unknown_kind(eg):
    with pytest.raises(schema.SchemaError):
        eg.upsert_node("x", "bogus_kind", "x")


def test_add_edge_normalizes_and_dedups(eg):
    eg.upsert_node("a", schema.EXPERIMENT, "a")
    eg.upsert_node("b", schema.EXPERIMENT, "b")
    eg.add_edge("a", "b", "beat", margin=0.1)
    eg.add_edge("a", "b", "BEAT", margin=0.2)  # same edge, updated attrs
    edges = eg.edges_from("a", relation="BEAT")
    assert len(edges) == 1 and edges[0].attrs["margin"] == 0.2


def test_record_experiment_builds_edges(eg):
    node = {
        "id": "0002", "parent": "0001", "hypothesis": "add bonus",
        "status": "committed", "score": 0.83, "commit": "def",
        "gates": [{"name": "correctness", "passed": True}],
        "judge": {"value": 0.9, "preset": "minimal_change", "reason": "tight"},
    }
    uid = eg.record_experiment(node, agent="claude", model="opus", environment="native")
    assert uid == "exp:0002"
    rels = {e.relation for e in eg.edges_from("exp:0002")}
    assert {"DERIVED_FROM", "MEASURED", "GATED_BY", "JUDGED_BY"} <= rels
    # agent PROPOSED edge points *into* the experiment
    assert any(e.relation == "PROPOSED" for e in eg.edges_into("exp:0002"))


def test_record_experiment_requires_id(eg):
    with pytest.raises(ValueError):
        eg.record_experiment({"hypothesis": "no id"})


def test_lineage_walks_derived_from_and_is_cycle_safe(eg):
    for i in range(4):
        eg.record_experiment({
            "id": f"{i:04d}", "parent": f"{i-1:04d}" if i else "root",
            "hypothesis": f"h{i}", "status": "committed", "score": 0.1 * i,
        })
    chain = eg.lineage("0003")
    assert chain == ["0003", "0002", "0001", "0000"]
    # inject a cycle and confirm it terminates
    eg.add_edge("exp:0000", "exp:0003", schema.DERIVED_FROM)
    assert eg.lineage("0003", max_depth=10)  # does not hang


def test_record_comparison_only_beats_when_gated(eg):
    eg.record_comparison("w1", "l1", gated=False, margin=0.05)
    assert eg.edges_from("exp:w1", relation="BEAT") == []
    assert eg.edges_from("exp:w1", relation="COMPARED_WITH")
    eg.record_comparison("w2", "l2", gated=True, margin=0.2)
    assert eg.beat_chain("w2") == ["l2"]


def test_record_failure_validates_class_and_flags_non_merit(eg):
    eg.record_experiment({"id": "0001", "hypothesis": "h", "status": "failed"})
    fuid = eg.record_failure("0001", failure_class="environment", summary="root-owned venv", task="t3")
    n = eg.get_node(fuid)
    assert n.attrs["non_merit"] is True
    assert eg.failures_for("0001")
    with pytest.raises(schema.SchemaError):
        eg.record_failure("0001", failure_class="oops", summary="x")


def test_content_addressed_artifact_dedups_on_sha(eg):
    sha = sha256_bytes(b"the diff")
    uid1 = eg.register_artifact(sha, size=8, kind="diff")
    uid2 = eg.register_artifact(sha, size=8, kind="diff")
    assert uid1 == uid2 == f"artifact:{sha}"
    assert eg.stats()["artifacts"] == 1


def test_register_artifact_file(eg, tmp_path):
    p = tmp_path / "patch.diff"
    p.write_bytes(b"diff --git a b\n")
    uid = eg.register_artifact_file(p, kind="diff")
    assert uid.startswith("artifact:")
    assert eg.get_node(uid).attrs["size"] == 15


def test_record_candidates_cites_source(eg):
    cs = CandidateSet(need="ranking", queries=["ranking"])
    cs.add(GraphCandidate(
        need="ranking", query="ranking", repo_id="repo__x",
        label="rank()", node_id="n1", kind="function",
        source_file="rank.py", source_location="rank.py:10", degree=7,
    ))
    uids = eg.record_candidates("0002", cs)
    assert len(uids) == 1
    cites = eg.citations_for("0002")
    assert cites and cites[0].attrs["repo_id"] == "repo__x"
    # both CITES and RETRIEVED_FROM edges exist
    rels = {e.relation for e in eg.edges_from("exp:0002")}
    assert {"CITES", "RETRIEVED_FROM"} <= rels


def test_export_graph_roundtrips(eg):
    eg.record_experiment({"id": "0001", "hypothesis": "h", "status": "committed", "score": 0.5})
    g = eg.export_graph()
    assert g["schema_version"] == schema.SCHEMA_VERSION
    assert any(n["uid"] == "exp:0001" for n in g["nodes"])
    # every edge endpoint that is an experiment resolves to a node uid
    uids = {n["uid"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["src"] in uids
