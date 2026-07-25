"""Scrapler Eval Harness — the shared contract every module builds against.

Pure stdlib, Python 3.10+ (runs on the 3.12 spider-den venv and the host).
Heavy scraper deps live ONLY in adapters, never here. This file is the single
source of truth for the types that flow between fixtures → candidates →
metrics → gates → leaderboard → store. Do not add third-party imports here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Tier(str, Enum):
    """Difficulty ladder. Frozen tiers are deterministic (answer_key present);
    live tiers are scored by an external oracle (detector) with no answer_key."""
    STATIC = "tier0_static"      # frozen HTML, no JS needed
    DYNAMIC = "tier1_dynamic"    # frozen HAR, JS-rendered content
    LAZY = "tier2_lazy"          # frozen, lazy-load / scroll content
    ANTIBOT = "tier3_antibot"    # live, Cloudflare/anti-bot
    DETECTOR = "tier4_detector"  # live, bot-detector oracle (sannysoft/CreepJS)
    REAL = "tierR_real"          # Nicholas's real targets


class WeightClass(int, Enum):
    FETCHER = 1     # no-JS fetchers
    BROWSER = 2     # stealth browsers
    ENGINE = 3      # full engines/orchestrators
    EXTRACTOR = 4   # HTML -> structured content
    SEARCH = 5      # search/discovery/index layers


@dataclass
class Task:
    """One ladder item: a page to scrape or a query to run."""
    id: str
    tier: Tier
    url: str                                        # http(s) live, or file:// frozen fixture
    answer_key: dict[str, Any] = field(default_factory=dict)   # expected content/fields (frozen tiers)
    schema: dict[str, Any] = field(default_factory=dict)       # extraction schema, if any
    query: str = ""                                 # for SEARCH-class tasks
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    ok: bool
    html: str = ""
    text: str = ""
    status: int = 0
    blocked: bool = False           # detected a challenge/block page
    latency_ms: float = 0.0
    peak_rss_mb: float = 0.0
    bytes_down: int = 0
    llm_tokens: int = 0
    error: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)  # screenshots, detector scores, XHR captures


@dataclass
class ExtractResult:
    fields: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    ok: bool = True
    error: str = ""


@dataclass
class AxisScores:
    """Every axis is 0..1. Scraping axes + search axes coexist; unused stay 0."""
    # scraping
    retrieval: float = 0.0        # real content vs block/empty
    completeness: float = 0.0     # captured / expected
    evasion: float = 0.0          # detector pass fraction
    latency_norm: float = 0.0     # inverted, normalized vs field
    cost_norm: float = 0.0        # inverted footprint (bytes+tokens+rss)
    robustness: float = 0.0       # 1 - success stddev over retries
    field_accuracy: float = 0.0   # extractor field match vs answer_key
    # search
    relevance: float = 0.0        # precision@k
    recall: float = 0.0           # recall of known-good
    freshness: float = 0.0
    selfhost: float = 0.0         # 1 = zero-key self-hosted
    extra: dict[str, float] = field(default_factory=dict)


@dataclass
class RunRecord:
    """One candidate's result on one task — the atom the whole harness records."""
    candidate: str
    task_id: str
    tier: str
    axes: AxisScores
    quality: float = 0.0          # per-item 0..1 blend (metrics.item_quality)
    gate_passed: bool = True
    fetch: Optional[FetchResult] = None
    extract: Optional[ExtractResult] = None
    error: str = ""
    ts: float = 0.0               # epoch seconds (caller stamps; harness never calls time itself in tests)


@dataclass
class LeaderRow:
    candidate: str
    weight_class: int
    coverage_total: float = 0.0   # sum of per-item quality
    normalized: float = 0.0       # 100 * coverage_total / n_tasks
    leaderboard: float = 0.0      # blended axes score
    elo: float = 1000.0           # head-to-head rating
    gate_pass_rate: float = 0.0
    n_tasks: int = 0
    axis_means: dict[str, float] = field(default_factory=dict)
    scratched: bool = False
    scratch_reason: str = ""


class Candidate(ABC):
    """A scraper/extractor/search tool wrapped to a uniform interface.

    Adapters subclass this. The harness only ever touches: name, weight_class,
    available(), and run()/fetch()/extract(). An adapter whose deps are missing
    returns available()==False and is skipped (recorded, not crashed)."""
    name: str = "unnamed"
    weight_class: int = WeightClass.FETCHER
    requires: list[str] = []      # pip extras / external bins this adapter needs

    @abstractmethod
    def available(self) -> bool:
        """True iff this adapter can actually run on this box right now."""
        raise NotImplementedError

    def fetch(self, task: Task) -> FetchResult:
        raise NotImplementedError(f"{self.name} has no fetch()")

    def extract(self, html: str, task: Task) -> ExtractResult:
        raise NotImplementedError(f"{self.name} has no extract()")

    def search(self, task: Task) -> list[dict[str, Any]]:
        raise NotImplementedError(f"{self.name} has no search()")


# ---- Protocol seams the other modules implement (documented, not enforced) ----
# metrics.py:     score(record_inputs, task) -> AxisScores ; item_quality(AxisScores, weight_class) -> float
# gates.py:       Gate.check(RunRecord) -> (passed: bool, reason: str)
# leaderboard.py: rank(list[RunRecord]) -> list[LeaderRow] ; arena_elo(pairwise) -> dict[str,float]
# harness.py:     run_bracket(candidates, ladder, gates, store) -> list[LeaderRow]
# store.py:       Store.record(RunRecord) ; Store.cache_get/put(key) ; Store.history(candidate)
# failure.py:     cluster(list[RunRecord]) -> list[FailureCluster]
# provenance.py:  stamp() -> dict ; Heartbeat.beat(msg)

__all__ = [
    "Tier", "WeightClass", "Task", "FetchResult", "ExtractResult",
    "AxisScores", "RunRecord", "LeaderRow", "Candidate",
]
