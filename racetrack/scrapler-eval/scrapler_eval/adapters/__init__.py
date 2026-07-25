"""Candidate adapters. Each module exposes Candidate subclasses; the registry
below maps a stable name -> class so brackets can reference tools by name.

Heavy adapters import their deps lazily inside methods (or guard in available())
so importing this package never fails when a scraper dep is absent.
"""

from __future__ import annotations

from ..interface import Candidate
from .baseline import BASELINE_CANDIDATES

# name -> Candidate class. Heavy adapters register themselves here as they land.
REGISTRY: dict[str, type[Candidate]] = {}


def register(cls: type[Candidate]) -> type[Candidate]:
    REGISTRY[cls.name] = cls
    return cls


for _c in BASELINE_CANDIDATES:
    REGISTRY[_c.name] = _c


def build(names: list[str]) -> list[Candidate]:
    """Instantiate candidates by name, skipping unknowns (logged by caller)."""
    return [REGISTRY[n]() for n in names if n in REGISTRY]


def all_candidates() -> list[Candidate]:
    return [cls() for cls in REGISTRY.values()]
