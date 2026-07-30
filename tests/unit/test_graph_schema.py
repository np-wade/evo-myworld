"""Schema vocabulary + validators — pure, no DB, no I/O."""
import pytest

from evo.graph import schema


def test_node_kind_partition():
    # source and experiment kinds are disjoint and cover the whole set
    assert schema.SOURCE_KINDS & schema.EXPERIMENT_KINDS == frozenset()
    assert schema.SOURCE_KINDS | schema.EXPERIMENT_KINDS == schema.NODE_KINDS


def test_directed_relations_are_relations():
    assert schema.DIRECTED_RELATIONS <= schema.RELATIONS


def test_non_merit_failures_are_failure_classes():
    assert schema.NON_MERIT_FAILURES <= schema.FAILURE_CLASSES


@pytest.mark.parametrize("raw,canon", [
    ("beat", "BEAT"),
    ("derived-from", "DERIVED_FROM"),
    ("  Retrieved_From ", "RETRIEVED_FROM"),
    ("PROMOTED", "PROMOTED"),
])
def test_normalize_relation(raw, canon):
    assert schema.normalize_relation(raw) == canon


def test_normalize_relation_rejects_unknown():
    with pytest.raises(schema.SchemaError):
        schema.normalize_relation("frobnicate")


def test_require_node_kind_roundtrips_and_rejects():
    assert schema.require_node_kind(schema.EXPERIMENT) == schema.EXPERIMENT
    with pytest.raises(schema.SchemaError):
        schema.require_node_kind("not_a_kind")


def test_require_failure_class_rejects_typo():
    assert schema.require_failure_class(schema.FAIL_TIMEOUT) == "timeout"
    with pytest.raises(schema.SchemaError):
        schema.require_failure_class("tmieout")


def test_validate_relations_dedups_and_normalizes():
    out = schema.validate_relations(["beat", "BEAT", "derived-from"])
    assert out == ["BEAT", "DERIVED_FROM"]


def test_predicates():
    assert schema.is_node_kind(schema.GATE)
    assert not schema.is_node_kind("gate_x")
    assert schema.is_relation("BEAT")
    assert not schema.is_relation("beat")  # predicates want canonical form
    assert schema.is_failure_class("flaky")
