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


def _autodiscover() -> None:
    """Import every adapter module in this package so it can self-register via
    `register(...)` at import time. Each import is guarded: an adapter whose
    heavy dep is missing must still import (deps are loaded lazily inside
    methods / available()), but if one genuinely can't import we skip it rather
    than break the whole registry."""
    import importlib
    import pkgutil

    for mod in pkgutil.iter_modules(__path__):
        if mod.name in ("baseline",) or mod.name.startswith("_"):
            continue
        try:
            m = importlib.import_module(f"{__name__}.{mod.name}")
        except Exception:  # a broken/absent-dep adapter must not sink the registry
            continue
        # modules that expose a CANDIDATES list get bulk-registered
        for cls in getattr(m, "CANDIDATES", []):
            REGISTRY[cls.name] = cls


_autodiscover()


def build(names: list[str]) -> list[Candidate]:
    """Instantiate candidates by name, skipping unknowns (logged by caller)."""
    return [REGISTRY[n]() for n in names if n in REGISTRY]


def all_candidates() -> list[Candidate]:
    return [cls() for cls in REGISTRY.values()]
