"""Evidence-graph schema: the shared vocabulary of the Graphify<->Evo bridge.

This module is pure data — no I/O, no third-party imports — so every other
module in ``evo.graph`` (retrieval, candidate contract, write-back, injection)
and every test can agree on one set of node kinds, edge relations, and failure
classes without importing sqlite or the CLI.

Design sources (graph-first prior art, see world/backend/NOTES.md for the
retrieval-side pulls):

* Node kinds / edge relations come from ``DEVELOPMENT-ROADMAP.md`` "Graph model"
  (repository nodes, experiment nodes, evidence edges).  They are frozen here so
  the roadmap's vocabulary is executable, not just prose.
* The run/job/facet split and the ``PRODUCED_BY``/``DERIVED_FROM`` lineage edges
  mirror the OpenLineage model as implemented in ``apache/airflow``
  (``OpenLineageAdapter`` / ``OperatorLineage`` in providers/openlineage) — a
  run event carries a job identity plus input/output facets, and lineage is an
  explicit edge rather than an inferred join.
* The failure taxonomy's transport/api/backend/database/environment/provider
  axis comes from ``DEVELOPMENT-ROADMAP.md`` "Classify failures as UI state,
  transport, API validation, backend logic, database, environment, or external
  provider", extended with the empirical classes an autoresearch loop actually
  needs to gate on (correctness, timeout, flaky, activation-missing).

Nothing here reaches into the immutable 9.2M-node source index; these constants
describe the *experiment* graph that write-back builds alongside it.
"""
from __future__ import annotations

from typing import Iterable

SCHEMA_VERSION = "evo-graph-schema-1"


# ── Node kinds ───────────────────────────────────────────────────────────────
# Two families share one graph: SOURCE_* nodes are read-only references into the
# Graphify library index (never mutated — they point *at* immutable source), and
# EXPERIMENT_* nodes are the empirical record Evo writes as it runs.

# Source-side (retrieval evidence — points into the frozen library index).
SOURCE_REPO = "source_repo"
SOURCE_SYMBOL = "source_symbol"      # a function/class/file node in index.db
SOURCE_SLICE = "source_slice"        # a topic slice (graphify-out/slices/*.json)

# Experiment-side (empirical evidence — written by write-back).
EXPERIMENT = "experiment"            # one Evo experiment node / run
CANDIDATE = "candidate"              # a proposed approach considered for a need
DIFF = "diff"                        # the code change an experiment applied
AGENT = "agent"                      # the agent/seat that produced a candidate
MODEL = "model"                      # the model behind an agent
ENVIRONMENT = "environment"          # a run environment / EnvironmentSpec
HARNESS = "harness"                  # a test/benchmark harness version
TASK = "task"                        # a benchmark task / cohort item
SCORE = "score"                      # a scalar or vector measurement
GATE = "gate"                        # a correctness/quality gate outcome
TRACE = "trace"                      # an execution trace / span bundle
FAILURE = "failure"                  # a classified failure observation
ARTIFACT = "artifact"               # a content-addressed artifact reference
DECISION = "decision"               # a win/lose/promote/discard decision
MISSION = "mission"                  # a mission-DAG node (intent overlay)

NODE_KINDS: frozenset[str] = frozenset({
    SOURCE_REPO, SOURCE_SYMBOL, SOURCE_SLICE,
    EXPERIMENT, CANDIDATE, DIFF, AGENT, MODEL, ENVIRONMENT, HARNESS, TASK,
    SCORE, GATE, TRACE, FAILURE, ARTIFACT, DECISION, MISSION,
})

SOURCE_KINDS: frozenset[str] = frozenset({SOURCE_REPO, SOURCE_SYMBOL, SOURCE_SLICE})
EXPERIMENT_KINDS: frozenset[str] = NODE_KINDS - SOURCE_KINDS


# ── Edge relations ───────────────────────────────────────────────────────────
# Stored uppercase (the roadmap's convention) so a relation reads as a verb from
# src to dst: (experiment)-[PRODUCED_BY]->(artifact), (b)-[BEAT]->(a).

# Structural / retrieval edges (source side).
IMPLEMENTS = "IMPLEMENTS"
CALLS = "CALLS"
CONTAINS = "CONTAINS"
IMPORTS = "IMPORTS"
COVERS = "COVERS"
CITES = "CITES"                      # experiment/candidate -> source_symbol
RETRIEVED_FROM = "RETRIEVED_FROM"    # candidate -> source_symbol/slice

# Empirical edges (experiment side).
DERIVED_FROM = "DERIVED_FROM"        # experiment -> parent experiment
PROPOSED = "PROPOSED"                # agent -> candidate
APPLIED = "APPLIED"                  # experiment -> diff
EXERCISED_BY = "EXERCISED_BY"        # diff/symbol -> task/harness
RAN_IN = "RAN_IN"                    # experiment -> environment
PRODUCED_BY = "PRODUCED_BY"          # experiment -> artifact
MEASURED = "MEASURED"                # experiment -> score
GATED_BY = "GATED_BY"                # experiment -> gate
FAILED_AT = "FAILED_AT"              # experiment/task -> failure
JUDGED_BY = "JUDGED_BY"              # experiment -> score (LLM-judge origin)
COMPARED_WITH = "COMPARED_WITH"      # experiment <-> experiment (symmetric intent)
BEAT = "BEAT"                        # winner -> loser (directed, gated)
REGRESSED = "REGRESSED"              # experiment -> baseline it regressed
PROMOTED = "PROMOTED"                # decision -> experiment
DECIDED = "DECIDED"                  # decision -> experiment (win/lose/discard)

RELATIONS: frozenset[str] = frozenset({
    IMPLEMENTS, CALLS, CONTAINS, IMPORTS, COVERS, CITES, RETRIEVED_FROM,
    DERIVED_FROM, PROPOSED, APPLIED, EXERCISED_BY, RAN_IN, PRODUCED_BY,
    MEASURED, GATED_BY, FAILED_AT, JUDGED_BY, COMPARED_WITH, BEAT, REGRESSED,
    PROMOTED, DECIDED,
})

# Relations whose meaning is direction-dependent — write-back must never store
# these "backwards" or a lineage query returns the wrong winner.
DIRECTED_RELATIONS: frozenset[str] = frozenset({
    BEAT, REGRESSED, DERIVED_FROM, PROMOTED, PRODUCED_BY, RETRIEVED_FROM,
    CITES, PROPOSED, APPLIED, MEASURED, GATED_BY, FAILED_AT, DECIDED,
})


# ── Failure taxonomy ─────────────────────────────────────────────────────────
# A classified failure is more useful than a retained log: it lets the next
# retrieval cycle avoid a class of approach, and it feeds the selector's
# "penalize environment failure / flakiness" rule.

# Layer axis (where it broke) — from the roadmap's classification list.
FAIL_UI_STATE = "ui_state"
FAIL_TRANSPORT = "transport"
FAIL_API_VALIDATION = "api_validation"
FAIL_BACKEND_LOGIC = "backend_logic"
FAIL_DATABASE = "database"
FAIL_ENVIRONMENT = "environment"
FAIL_EXTERNAL_PROVIDER = "external_provider"

# Outcome axis (how it broke) — what an autoresearch loop gates on.
FAIL_CORRECTNESS = "correctness"        # wrong answer / assertion failed
FAIL_TIMEOUT = "timeout"                # exceeded the per-experiment budget
FAIL_FLAKY = "flaky"                    # non-deterministic across seeds
FAIL_ACTIVATION_MISSING = "activation_missing"  # changed path never ran
FAIL_HARNESS_ERROR = "harness_error"    # the test rig itself broke
FAIL_UNKNOWN = "unknown"

FAILURE_CLASSES: frozenset[str] = frozenset({
    FAIL_UI_STATE, FAIL_TRANSPORT, FAIL_API_VALIDATION, FAIL_BACKEND_LOGIC,
    FAIL_DATABASE, FAIL_ENVIRONMENT, FAIL_EXTERNAL_PROVIDER,
    FAIL_CORRECTNESS, FAIL_TIMEOUT, FAIL_FLAKY, FAIL_ACTIVATION_MISSING,
    FAIL_HARNESS_ERROR, FAIL_UNKNOWN,
})

# Classes the selector must treat as *non-evidence of a bad idea* — an
# environment or harness failure says nothing about the candidate's merit.
NON_MERIT_FAILURES: frozenset[str] = frozenset({
    FAIL_ENVIRONMENT, FAIL_HARNESS_ERROR, FAIL_EXTERNAL_PROVIDER, FAIL_TIMEOUT,
})


# ── Validators (fail fast, with a message that names the vocabulary) ─────────

class SchemaError(ValueError):
    """Raised when a node kind, relation, or failure class is not in the schema."""


def is_node_kind(kind: str) -> bool:
    return kind in NODE_KINDS


def is_relation(relation: str) -> bool:
    return relation in RELATIONS


def is_failure_class(cls: str) -> bool:
    return cls in FAILURE_CLASSES


def normalize_relation(relation: str) -> str:
    """Accept a relation in any case / with dashes and return the canonical form.

    Lets callers write ``derived-from`` or ``beat`` and still land on the frozen
    vocabulary; raises SchemaError if it is not a known relation.
    """
    canon = str(relation).strip().upper().replace("-", "_")
    if canon not in RELATIONS:
        raise SchemaError(
            f"unknown relation {relation!r}; known: {sorted(RELATIONS)}"
        )
    return canon


def require_node_kind(kind: str) -> str:
    if kind not in NODE_KINDS:
        raise SchemaError(
            f"unknown node kind {kind!r}; known: {sorted(NODE_KINDS)}"
        )
    return kind


def require_failure_class(cls: str) -> str:
    if cls not in FAILURE_CLASSES:
        raise SchemaError(
            f"unknown failure class {cls!r}; known: {sorted(FAILURE_CLASSES)}"
        )
    return cls


def validate_relations(relations: Iterable[str]) -> list[str]:
    """Normalize a collection of relations, preserving order and de-duplicating."""
    seen: dict[str, None] = {}
    for r in relations:
        seen[normalize_relation(r)] = None
    return list(seen)
