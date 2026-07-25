"""store.py — run store (JSONL), content-addressed result cache, score history.

Pure stdlib. Ports two donor PATTERNS (ideas, not SDKs):

  * facebookresearch_exca (exca/cachedict/core.py, exca/confdict.py::UidMaker) —
    a content-addressed on-disk cache keyed by a hash of the *config*. exca
    canonicalizes a config then `hashlib.md5(...).hexdigest()` to get a stable
    uid and dumps each value to its own file under a cache folder. We port the
    IDEA with pure stdlib: sha256 over a canonical JSON of (candidate, task_id,
    sorted cfg) -> one <key>.json file under root/cache/.

  * comet-ml_opik (sdks/python/.../experiment/experiment.py) — an experiment
    has an id, params and a stream of items each carrying scores. We port the
    IDEA of an append-only run log (one JSON object per line) rather than its
    networked streamer/REST SDK.

Determinism rule (harness anti-cheat): nothing here calls time.time(). Callers
stamp `ts` and pass it in, so tests are reproducible.

Anti-cheat rule (CONTRACT.md #3): a cache short-circuit MUST be detectable.
`ResultCache.get` marks every hit with {"_cache": "hit"} so downstream logging
records reuse as reuse, never as a fresh run.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any, Optional

from .interface import (
    AxisScores,
    ExtractResult,
    FetchResult,
    RunRecord,
)

__all__ = [
    "RunStore",
    "ResultCache",
    "ScoreHistory",
    "record_to_dict",
    "dict_to_record",
    "canonical_json",
]


# --------------------------------------------------------------------------- #
# Canonical serialization (exca UidMaker idea: stable string -> hash)
# --------------------------------------------------------------------------- #
def canonical_json(obj: Any) -> str:
    """Deterministic JSON: keys sorted, compact separators, ascii-safe.

    This is the single choke point that makes cache keys and stored records
    reproducible regardless of dict insertion order (exca canonicalizes its
    config the same way before hashing)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# --------------------------------------------------------------------------- #
# RunRecord <-> dict round-trip (handles nested dataclasses)
# --------------------------------------------------------------------------- #
def record_to_dict(rec: RunRecord) -> dict[str, Any]:
    """Flatten a RunRecord (and its nested AxisScores/FetchResult/ExtractResult)
    to a plain JSON-serializable dict. `dataclasses.asdict` recurses into nested
    dataclasses, so nested axes/fetch/extract survive as sub-dicts."""
    if not is_dataclass(rec):
        raise TypeError(f"record_to_dict expects a RunRecord, got {type(rec)!r}")
    return asdict(rec)


def _build_dataclass(cls: type, data: Optional[dict[str, Any]]) -> Any:
    """Rebuild a dataclass instance from a dict, ignoring unknown keys and
    letting missing keys fall back to the dataclass default."""
    if data is None:
        return None
    known = {f.name for f in fields(cls)}
    kwargs = {k: v for k, v in data.items() if k in known}
    return cls(**kwargs)


def dict_to_record(data: dict[str, Any]) -> RunRecord:
    """Inverse of record_to_dict: rebuild a RunRecord with its nested
    dataclasses reconstructed (AxisScores always; FetchResult/ExtractResult
    only when present)."""
    d = dict(data)
    # strip any bookkeeping fields (e.g. the _cache reuse marker) before rebuild
    d.pop("_cache", None)
    axes = _build_dataclass(AxisScores, d.get("axes")) or AxisScores()
    fetch = _build_dataclass(FetchResult, d.get("fetch"))
    extract = _build_dataclass(ExtractResult, d.get("extract"))

    known = {f.name for f in fields(RunRecord)}
    kwargs = {k: v for k, v in d.items() if k in known}
    kwargs["axes"] = axes
    kwargs["fetch"] = fetch
    kwargs["extract"] = extract
    return RunRecord(**kwargs)


# --------------------------------------------------------------------------- #
# RunStore — append-only JSONL run log (opik experiment idea)
# --------------------------------------------------------------------------- #
class RunStore:
    """Append-only run log. Each RunRecord becomes one JSON line in
    root/runs.jsonl — a kairosdb-style time series of results, but as JSONL so
    it stays pure stdlib and human-greppable. Reads filter by candidate to give
    a per-candidate score history over time."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "runs.jsonl"

    def record(self, rec: RunRecord) -> None:
        """Append one RunRecord as a JSON line. Opened in append mode so
        concurrent lanes never truncate each other's history."""
        line = canonical_json(record_to_dict(rec))
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def all_records(self) -> list[dict[str, Any]]:
        """Every recorded run, in write order. Blank/whitespace lines are
        skipped (tolerates exca-style in-place blanking of deleted entries)."""
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                out.append(json.loads(line))
        return out

    def history(self, candidate: str) -> list[dict[str, Any]]:
        """All runs for one candidate, in chronological (write) order."""
        return [r for r in self.all_records() if r.get("candidate") == candidate]


# --------------------------------------------------------------------------- #
# ResultCache — content-addressed cache keyed by config hash (exca idea)
# --------------------------------------------------------------------------- #
class ResultCache:
    """A content-addressed cache: key = sha256(canonical(candidate, task_id,
    cfg)). Each record dumps to its own root/cache/<key>.json file (exca dumps
    one file per value). hit/miss counts are tracked on the instance.

    Anti-cheat: get() stamps every hit with {"_cache": "hit"} so a reused
    result is always detectable downstream and can never be logged as fresh."""

    def __init__(self, root: str | Path, reused_flag_field: str = "_cache"):
        self.root = Path(root)
        self.dir = self.root / "cache"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.reused_flag_field = reused_flag_field
        self._hits = 0
        self._misses = 0

    def key(self, candidate: str, task_id: str, cfg: dict[str, Any]) -> str:
        """Stable, config-sensitive key. cfg ordering does not matter (canonical
        json sorts keys); any change to candidate/task/cfg changes the digest."""
        payload = canonical_json(
            {"candidate": candidate, "task_id": task_id, "cfg": cfg}
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str) -> Optional[dict[str, Any]]:
        """Return the cached record marked as reuse, or None on a miss.
        Increments the instance hit/miss counters."""
        path = self._path(key)
        if not path.exists():
            self._misses += 1
            return None
        with path.open("r", encoding="utf-8") as f:
            rec = json.load(f)
        self._hits += 1
        rec[self.reused_flag_field] = "hit"  # anti-cheat: mark reuse
        return rec

    def put(
        self,
        key: str,
        record_dict: dict[str, Any],
        reused_flag_field: Optional[str] = None,
    ) -> None:
        """Store a fresh record under <key>.json. The reuse marker is stripped
        before writing so a cache file always represents a fresh computation;
        the marker is (re)applied only on get()."""
        flag = reused_flag_field or self.reused_flag_field
        to_store = {k: v for k, v in record_dict.items() if k != flag}
        tmp = self._path(key).with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.write(canonical_json(to_store))
        os.replace(tmp, self._path(key))  # atomic publish

    def stats(self) -> dict[str, int]:
        """{"hits": n, "misses": n} accumulated over this instance's lifetime."""
        return {"hits": self._hits, "misses": self._misses}


# --------------------------------------------------------------------------- #
# ScoreHistory — kairosdb-lite metric time series as JSONL
# --------------------------------------------------------------------------- #
class ScoreHistory:
    """Per-(candidate, metric) numeric time series. Each append writes one JSONL
    row {candidate, metric, value, ts}; series() reads the ordered (ts, value)
    points and latest() returns the most-recent value. kairosdb's idea (a
    tagged time series) reduced to an append-only JSONL file."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "scores.jsonl"

    def append(self, candidate: str, metric: str, value: float, ts: float) -> None:
        """Append one time-series point. ts is caller-stamped (never time.time())
        so ordering is deterministic under test."""
        row = {"candidate": candidate, "metric": metric, "value": value, "ts": ts}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(canonical_json(row) + "\n")

    def _rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def series(self, candidate: str, metric: str) -> list[tuple[float, float]]:
        """All (ts, value) points for one candidate+metric, sorted by ts
        ascending — a clean chronological curve regardless of write order."""
        pts = [
            (r["ts"], r["value"])
            for r in self._rows()
            if r.get("candidate") == candidate and r.get("metric") == metric
        ]
        pts.sort(key=lambda p: p[0])
        return pts

    def latest(self, candidate: str, metric: str) -> Optional[float]:
        """Value at the largest ts, or None if the series is empty."""
        pts = self.series(candidate, metric)
        if not pts:
            return None
        return pts[-1][1]
