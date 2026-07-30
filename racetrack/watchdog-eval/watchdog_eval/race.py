"""Diff race — every (differ x normalizer) combo runs the full fixture set,
detections are classified (shared real-vs-churn stage), then scored against the
injection manifest. Answers: which diff strategy reports every real change
while IGNORING the churn traps?

Rank: score = F1 x (1 - false-alarm-rate), then FAR asc, localization desc,
p50 asc. Per-candidate AND per-page try/except so one broken differ (or one
weird page) can't kill the race. 100% offline. Pure stdlib.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass

from .classify import classify
from .differs import ALL_DIFFERS, Detection, Differ
from .oracle import FIXTURES, Oracle
from .snapshot import ALL_NORMALIZERS, Normalizer


def _pct(xs: list[float], p: float) -> float:
    if not xs: return 0.0
    xs = sorted(xs); k = (len(xs) - 1) * p
    lo = int(k); hi = min(lo + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 2)


def page_files(set_key: str = "set1") -> list[str]:
    root = FIXTURES / set_key
    return sorted(p.stem for p in (root / "v1").glob("*.html"))


def run_combo(differ: Differ, norm: Normalizer, set_key: str = "set1"
              ) -> tuple[list[Detection], list[float], list[str]]:
    """Diff every fixture page pair through one candidate combo.
    Returns (classified detections, per-page latencies ms, per-page errors)."""
    root = FIXTURES / set_key
    dets: list[Detection] = []
    lat: list[float] = []
    errors: list[str] = []
    for page in page_files(set_key):
        v1 = (root / "v1" / f"{page}.html").read_text()
        v2 = (root / "v2" / f"{page}.html").read_text()
        t0 = time.perf_counter()
        try:
            d = differ.diff(page, norm.normalize(v1), norm.normalize(v2))
            classify(d)
        except Exception as e:  # a weird page must not kill the candidate
            errors.append(f"{page}: {type(e).__name__}: {e}")
            lat.append((time.perf_counter() - t0) * 1000)
            continue
        lat.append((time.perf_counter() - t0) * 1000)
        dets.extend(d)
    return dets, lat, errors


@dataclass
class CandResult:
    name: str
    score: float             # f1 * (1 - false_alarm_rate)
    f1: float
    recall: float
    precision: float
    false_alarm_rate: float
    localization: float
    real_hit: str            # "10/10"
    churn_flagged: str       # "0/23"
    n_reported: int
    n_suppressed: int
    p50_ms: float
    p95_ms: float
    note: str = ""
    error: str = ""


def diff_race(set_key: str = "set1", runs: int = 3) -> dict:
    oracle = Oracle(set_key)
    results: list[CandResult] = []
    skipped: list[str] = []
    for norm in ALL_NORMALIZERS:
        for differ in ALL_DIFFERS:
            name = f"{differ.key}/{norm.key}"
            if not (differ.available() and norm.available()):
                skipped.append(name)
                continue
            try:
                lat_all: list[float] = []
                dets: list[Detection] = []
                errors: list[str] = []
                for r in range(max(1, runs)):
                    d, lat, errs = run_combo(differ, norm, set_key)
                    lat_all += lat
                    if r == 0:  # deterministic — detections identical per run
                        dets, errors = d, errs
                sc = oracle.score_detections([asdict(x) for x in dets])
                results.append(CandResult(
                    name=name,
                    score=round(sc.f1 * (1 - sc.false_alarm_rate), 4),
                    f1=sc.f1, recall=sc.recall, precision=sc.precision,
                    false_alarm_rate=sc.false_alarm_rate,
                    localization=sc.localization,
                    real_hit=f"{sc.real_hit}/{sc.real_total}",
                    churn_flagged=f"{sc.churn_flagged}/{sc.churn_total}",
                    n_reported=sc.n_reported, n_suppressed=sc.n_suppressed,
                    p50_ms=_pct(lat_all, .5), p95_ms=_pct(lat_all, .95),
                    note=(differ.diff.__doc__ or "").strip(),
                    error="; ".join(errors)[:200],
                ))
            except Exception as e:  # a broken candidate must not kill the race
                results.append(CandResult(
                    name=name, score=0.0, f1=0.0, recall=0.0, precision=0.0,
                    false_alarm_rate=0.0, localization=0.0, real_hit="0/0",
                    churn_flagged="0/0", n_reported=0, n_suppressed=0,
                    p50_ms=0.0, p95_ms=0.0,
                    error=f"{type(e).__name__}: {e}"))
    ranked = sorted(results, key=lambda r: (-r.score, r.false_alarm_rate,
                                            -r.localization, r.p50_ms))
    return {
        "set": set_key, "runs": runs,
        "pages": len(page_files(set_key)),
        "real_changes": len(oracle.real), "churn_traps": len(oracle.churn),
        "candidates_run": [r.name for r in results],
        "candidates_skipped": skipped,
        "leaderboard": [asdict(r) for r in ranked],
    }


def format_leaderboard(res: dict) -> str:
    L = [f"watchdog diff race — {res['set']}  ({res['pages']} page pairs, "
         f"{res['real_changes']} real changes, {res['churn_traps']} churn "
         f"traps, runs={res['runs']})", ""]
    hdr = (f"{'candidate':20} {'score':>6} {'F1':>6} {'recall':>7} {'prec':>6} "
           f"{'FAR':>6} {'loc':>6} {'hit':>6} {'flag':>6} {'supp':>5} "
           f"{'p50ms':>7}")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        L.append(f"{r['name']:20} {r['score']:6.3f} {r['f1']:6.3f} "
                 f"{r['recall']:7.3f} {r['precision']:6.3f} "
                 f"{r['false_alarm_rate']:6.3f} {r['localization']:6.3f} "
                 f"{r['real_hit']:>6} {r['churn_flagged']:>6} "
                 f"{r['n_suppressed']:5d} {r['p50_ms']:7.2f}"
                 + (f"  err: {r['error'][:50]}" if r["error"] else ""))
    if res["candidates_skipped"]:
        L += ["", f"skipped (missing dep): "
                  f"{', '.join(res['candidates_skipped'])}"]
    L += ["", "score = F1 x (1 - false-alarm-rate); FAR = churn traps reported "
              "as real changes (lower is better)."]
    return "\n".join(L)
