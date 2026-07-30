"""Discovery race — run each available candidate N times, score vs the oracle,
build the leaderboard. Answers: which normal-scraping path pulls the full
2026-07-14 arXiv set fastest and most completely?

Speed = p50/p95 wall-clock. Quality = recall/precision/F1 vs oracle gold.
Also: block rate + run-to-run variance (robustness). Pure stdlib.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field

from .discover import Candidate, build_candidates
from .fetchers import available_backends
from .oracle import Oracle


def _pct(xs: list[float], p: float) -> float:
    if not xs: return 0.0
    xs = sorted(xs); k = (len(xs) - 1) * p
    lo = int(k); hi = min(lo + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


@dataclass
class CandResult:
    name: str
    bracket: str
    runs: int
    p50_ms: float
    p95_ms: float
    recall: float
    precision: float
    f1: float
    found_med: int
    block_rate: float
    ok_rate: float
    note: str = ""
    error: str = ""


def race(date: str = "2026-07-14", runs: int = 5,
         polite_s: float = 2.0) -> dict:
    oracle = Oracle(date)
    backends = available_backends()
    cands = [c for c in build_candidates(backends) if c.available()]
    skipped = [c.name for c in build_candidates(backends) if not c.available()]

    results: list[CandResult] = []
    for c in cands:
        lat, recs, precs, f1s, founds, blocks, oks, last_err = \
            [], [], [], [], [], 0, 0, ""
        for _ in range(runs):
            try:
                out = c.discover()
            except Exception as e:  # a broken candidate must not kill the race
                last_err = f"{type(e).__name__}: {e}"
                lat.append(0.0)
                recs.append(0.0); precs.append(0.0); f1s.append(0.0)
                founds.append(0)
                time.sleep(polite_s)
                continue
            lat.append(out.latency_ms)
            if out.blocked: blocks += 1
            if out.ok: oks += 1
            if out.error: last_err = out.error
            sc = oracle.score_discovery(out.ids)
            recs.append(sc.recall); precs.append(sc.precision)
            f1s.append(sc.f1); founds.append(sc.found)
            time.sleep(polite_s)
        results.append(CandResult(
            name=c.name, bracket=c.bracket, runs=runs,
            p50_ms=_pct(lat, .5), p95_ms=_pct(lat, .95),
            recall=round(statistics.median(recs), 4),
            precision=round(statistics.median(precs), 4),
            f1=round(statistics.median(f1s), 4),
            found_med=int(statistics.median(founds)),
            block_rate=round(blocks / runs, 3),
            ok_rate=round(oks / runs, 3),
            note=c.discover.__doc__ or "", error=last_err,
        ))

    # rank: F1 desc, then p50 asc (fast tie-break)
    for b in ("listing", "serp"):
        pass
    ranked = sorted(results, key=lambda r: (-r.f1, r.p50_ms))
    return {
        "date": date, "runs": runs, "gold_papers": len(oracle.gold_ids),
        "backends_available": [b.name for b in backends],
        "candidates_run": [r.name for r in results],
        "candidates_skipped": skipped,
        "leaderboard": [asdict(r) for r in ranked],
    }


def format_leaderboard(res: dict) -> str:
    L = []
    L.append(f"arXiv discovery race — {res['date']}  "
             f"(gold={res['gold_papers']} papers, runs={res['runs']})")
    L.append(f"backends: {', '.join(res['backends_available']) or 'NONE'}")
    L.append("")
    hdr = f"{'candidate':28} {'brkt':7} {'F1':>6} {'recall':>7} {'prec':>6} " \
          f"{'found':>6} {'p50ms':>8} {'p95ms':>8} {'block':>6}"
    L.append(hdr); L.append("-" * len(hdr))
    for r in res["leaderboard"]:
        L.append(f"{r['name']:28} {r['bracket']:7} {r['f1']:6.3f} "
                 f"{r['recall']:7.3f} {r['precision']:6.3f} {r['found_med']:6d} "
                 f"{r['p50_ms']:8.1f} {r['p95_ms']:8.1f} {r['block_rate']:6.2f}")
    if res["candidates_skipped"]:
        L.append("")
        L.append(f"skipped (missing backend/infra): "
                 f"{', '.join(res['candidates_skipped'])}")
    return "\n".join(L)
