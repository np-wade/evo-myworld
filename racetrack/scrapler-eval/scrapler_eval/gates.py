"""Scrapler Eval Harness — executable pass/fail gates (the "rails").

Pure stdlib. No third-party imports (evo anti-cheat rule 6).

A *gate* is a declarative, executable rail: given a `RunRecord` it returns
``(passed, reason)``. A `GateSet` is a list of gates that all must pass for a
candidate's run on a task to survive; a failing gate scratches the run. Each
race declares its gates *declaratively* in the bracket yaml, and `from_spec`
compiles that spec dict into live gate objects.

Donor lineage — NVIDIA-NeMo_Guardrails
  (filing-cabinet/library-base/repos/NVIDIA-NeMo_Guardrails/code):
  - `nemoguardrails/guardrails/rail_action.py::RailAction` — an ABC whose
    subclasses implement a single check step; its public `run()` returns a
    `RailResult(is_safe: bool, reason: str | None)`. We port that IDEA: `Gate`
    is an ABC with `check(record) -> (passed, reason)` — the same
    pass/block-plus-reason contract, minus the LLM/prompt machinery.
  - `nemoguardrails/guardrails/engine_registry.py::EngineRegistry` — a dict
    keyed by name that builds concrete engine instances from config. We port
    that as `GATE_TYPES` + `GateSet.from_spec`, so a bracket declares its rails
    declaratively (like a NeMo `RailsConfig`) and we compile them to objects.

We port the PATTERN (declarative executable rails, name→class registry,
config→objects compilation), NOT NeMo's LLM guardrail internals.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .interface import RunRecord


class Gate(ABC):
    """One executable rail. Subclasses set ``name`` and implement ``check``.

    ``check`` returns ``(passed, reason)``. On pass, ``reason`` is a short
    empty-ish confirmation; on fail, ``reason`` explains WHY (so the steward
    can log exactly why a candidate was scratched on this task).
    """

    name: str = "gate"

    @abstractmethod
    def check(self, record: RunRecord) -> tuple[bool, str]:
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<{type(self).__name__} name={self.name!r}>"


def _fetch_text(record: RunRecord) -> str:
    """Best available retrieved text: prefer fetch.text, fall back to html."""
    if record.fetch is None:
        return ""
    if record.fetch.text:
        return record.fetch.text
    return record.fetch.html or ""


class RetrievedContentGate(Gate):
    """Tier-0 rail: a candidate must retrieve real content or be scratched.

    Passes iff there is a fetch, it is ok, it is not blocked, and the retrieved
    text has at least ``min_chars`` characters.
    """

    name = "retrieved_content"

    def __init__(self, min_chars: int = 200) -> None:
        self.min_chars = min_chars

    def check(self, record: RunRecord) -> tuple[bool, str]:
        if record.fetch is None:
            return False, "no fetch result (nothing retrieved)"
        if not record.fetch.ok:
            err = record.fetch.error or "fetch not ok"
            return False, f"fetch failed: {err}"
        if record.fetch.blocked:
            return False, "fetch was blocked (challenge/block page)"
        text = _fetch_text(record)
        n = len(text)
        if n < self.min_chars:
            return False, f"retrieved {n} chars < min {self.min_chars}"
        return True, f"retrieved {n} chars"


class NotBlockedGate(Gate):
    """Rail: fails if the fetch tripped a block/challenge page."""

    name = "not_blocked"

    def check(self, record: RunRecord) -> tuple[bool, str]:
        if record.fetch is None:
            return False, "no fetch result to evaluate block status"
        if record.fetch.blocked:
            return False, "fetch was blocked (challenge/block page)"
        return True, "not blocked"


class MinQualityGate(Gate):
    """Rail: the per-item blended quality must meet ``threshold``."""

    name = "min_quality"

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def check(self, record: RunRecord) -> tuple[bool, str]:
        if record.quality < self.threshold:
            return False, f"quality {record.quality:.3f} < threshold {self.threshold:.3f}"
        return True, f"quality {record.quality:.3f} >= {self.threshold:.3f}"


class BudgetGate(Gate):
    """Rail: fails if the fetch blows the latency or RSS budget.

    WSL is memory-capped, so an over-budget fetch is a real failure, not a
    warning. Either limit may be ``None`` to disable that half of the check.
    """

    name = "budget"

    def __init__(self, max_latency_ms: float | None = None,
                 max_rss_mb: float | None = None) -> None:
        self.max_latency_ms = max_latency_ms
        self.max_rss_mb = max_rss_mb

    def check(self, record: RunRecord) -> tuple[bool, str]:
        if record.fetch is None:
            return False, "no fetch result to evaluate budget"
        f = record.fetch
        if self.max_latency_ms is not None and f.latency_ms > self.max_latency_ms:
            return False, (f"latency {f.latency_ms:.0f}ms > "
                           f"budget {self.max_latency_ms:.0f}ms")
        if self.max_rss_mb is not None and f.peak_rss_mb > self.max_rss_mb:
            return False, (f"peak_rss {f.peak_rss_mb:.0f}MB > "
                           f"budget {self.max_rss_mb:.0f}MB")
        return True, "within budget"


class FieldPresenceGate(Gate):
    """Extractor rail: passes iff every required field is present (non-None).

    Reads ``record.extract.fields``. A missing extract result, or any required
    key absent / mapped to ``None``, fails the gate.
    """

    name = "field_presence"

    def __init__(self, required_fields: list[str]) -> None:
        self.required_fields = list(required_fields)

    def check(self, record: RunRecord) -> tuple[bool, str]:
        if record.extract is None:
            return False, "no extract result (no fields extracted)"
        fields = record.extract.fields or {}
        missing = [k for k in self.required_fields
                   if k not in fields or fields[k] is None]
        if missing:
            return False, f"missing required fields: {', '.join(missing)}"
        return True, f"all {len(self.required_fields)} required fields present"


class SearchRelevanceGate(Gate):
    """Search rail: passes iff the run has at least ``min_hits`` relevant hits.

    Hit count is read from, in priority order:
      1. ``record.fetch.artifacts['hits']`` (an int count), if present;
      2. otherwise inferred from ``record.axes.relevance`` — a relevance > 0
         counts as at least one relevant hit.
    """

    name = "search_relevance"

    def __init__(self, min_hits: int = 1) -> None:
        self.min_hits = min_hits

    def _hit_count(self, record: RunRecord) -> int:
        if record.fetch is not None:
            arts = record.fetch.artifacts or {}
            if "hits" in arts:
                try:
                    return int(arts["hits"])
                except (TypeError, ValueError):
                    return 0
        # Fall back to the relevance axis: any positive relevance => >=1 hit.
        return 1 if record.axes.relevance > 0 else 0

    def check(self, record: RunRecord) -> tuple[bool, str]:
        hits = self._hit_count(record)
        if hits < self.min_hits:
            return False, f"{hits} relevant hit(s) < min {self.min_hits}"
        return True, f"{hits} relevant hit(s) >= {self.min_hits}"


# ---- Registry: spec key -> gate class (NeMo EngineRegistry idea) ------------
# `from_spec` looks up each spec key here and builds the gate from its kwargs.
GATE_TYPES: dict[str, type[Gate]] = {
    "retrieved_content": RetrievedContentGate,
    "not_blocked": NotBlockedGate,
    "min_quality": MinQualityGate,
    "budget": BudgetGate,
    "field_presence": FieldPresenceGate,
    "search_relevance": SearchRelevanceGate,
}


class GateSet:
    """An ordered collection of gates; all must pass for the run to survive.

    This is the declarative rail bundle a bracket attaches to a race — the
    scrapler analogue of a NeMo ``RailsConfig`` (a set of flows compiled from
    config).
    """

    def __init__(self, gates: list[Gate] | None = None) -> None:
        self.gates: list[Gate] = list(gates) if gates else []

    def add(self, gate: Gate) -> "GateSet":
        self.gates.append(gate)
        return self

    def check_all(self, record: RunRecord) -> tuple[bool, list[str]]:
        """Run every gate. Returns ``(all_passed, failing_reasons)``.

        ``failing_reasons`` lists a ``"<gate.name>: <reason>"`` string for each
        gate that failed, in gate order. Empty list iff everything passed.
        """
        reasons: list[str] = []
        for gate in self.gates:
            passed, reason = gate.check(record)
            if not passed:
                reasons.append(f"{gate.name}: {reason}")
        return (len(reasons) == 0), reasons

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> "GateSet":
        """Compile a yaml-ish spec dict into a live ``GateSet``.

        Example spec::

            {
              "retrieved_content": {"min_chars": 200},
              "budget": {"max_latency_ms": 30000, "max_rss_mb": 4000},
              "not_blocked": {},          # no kwargs -> bare gate
              "not_blocked": True,        # truthy scalar also means "on"
            }

        Each key is a `GATE_TYPES` name; its value is a kwargs dict passed to
        the gate constructor. A non-dict truthy value (e.g. ``True``) enables
        the gate with defaults; a falsy value (``False``/``None``) skips it.
        Unknown keys raise ``KeyError`` (fail loud on a bad bracket).
        """
        gates: list[Gate] = []
        for key, cfg in spec.items():
            if key not in GATE_TYPES:
                raise KeyError(
                    f"unknown gate type {key!r}; known: {sorted(GATE_TYPES)}"
                )
            if cfg is None or cfg is False:
                continue
            kwargs = cfg if isinstance(cfg, dict) else {}
            gates.append(GATE_TYPES[key](**kwargs))
        return cls(gates)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self.gates)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        names = ", ".join(g.name for g in self.gates)
        return f"<GateSet [{names}]>"


__all__ = [
    "Gate",
    "RetrievedContentGate",
    "NotBlockedGate",
    "MinQualityGate",
    "BudgetGate",
    "FieldPresenceGate",
    "SearchRelevanceGate",
    "GateSet",
    "GATE_TYPES",
]
