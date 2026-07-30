"""Discovery race — run each available candidate on each fixture newsletter,
apply the standard date-window filter, score vs the oracle's window gold, and
build the leaderboard. Answers: which normal-scraping path finds "every post
in the last 60 days" best — the lazy-loaded archive page, the sitemap, or a
SERP?

Speed = p50/p95 wall-clock. Quality = recall/precision/F1 (mean over pubs,
median over runs). Also block rate. Per-candidate try/except so one broken
candidate can't kill the race. Pure stdlib.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass

from .discover import build_candidates
from .fetchers import available_backends
from .filter import FilterCandidate
from .oracle import DEFAULT_PUBS, Oracle


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
    pubs: int
    p50_ms: float
    p95_ms: float
    recall: float
    precision: float
    f1: float
    raw_f1: float          # before the window filter (context)
    found_med: int
    block_rate: float
    ok_rate: float
    note: str = ""
    error: str = ""


def race(pubs: list[str] | None = None, runs: int = 2,
         polite_s: float = 2.0) -> dict:
    pubs = pubs or DEFAULT_PUBS
    oracles = {p: Oracle(p) for p in pubs}
    backends = available_backends()

    # candidate keys are identical across pubs; group by name
    proto = build_candidates(backends, "https://example.com")
    names = [c.name for c in proto if c.available()]
    skipped = [c.name for c in proto if not c.available()]

    per: dict[str, dict] = {n: {"lat": [], "recs": [], "precs": [], "f1s": [],
                                "raw_f1s": [], "founds": [], "blocks": 0,
                                "oks": 0, "n": 0, "err": "", "note": "",
                                "bracket": ""} for n in names}
    for _ in range(runs):
        for pub, o in oracles.items():
            filt = FilterCandidate("date-window", (o.window_start, o.ref_date))
            for c in build_candidates(backends, o.base_url):
                if not c.available():
                    continue
                st = per[c.name]
                st["bracket"] = c.bracket
                st["note"] = (c.discover.__doc__ or c.__doc__ or "").split("\n")[0]
                st["n"] += 1
                try:
                    out = c.discover()
                except Exception as e:   # broken candidate must not kill race
                    st["err"] = f"{type(e).__name__}: {e}"
                    st["lat"].append(0.0)
                    st["recs"].append(0.0); st["precs"].append(0.0)
                    st["f1s"].append(0.0); st["raw_f1s"].append(0.0)
                    st["founds"].append(0)
                    time.sleep(polite_s)
                    continue
                st["lat"].append(out.latency_ms)
                if out.blocked: st["blocks"] += 1
                if out.ok: st["oks"] += 1
                if out.error: st["err"] = out.error
                raw = o.score_posts(set(out.slugs))
                sc = o.score_posts(filt.apply(out))
                st["recs"].append(sc.recall); st["precs"].append(sc.precision)
                st["f1s"].append(sc.f1); st["raw_f1s"].append(raw.f1)
                st["founds"].append(sc.found)
                time.sleep(polite_s)

    results = []
    for n, st in per.items():
        if not st["n"]:
            continue
        results.append(CandResult(
            name=n, bracket=st["bracket"], runs=runs, pubs=len(pubs),
            p50_ms=_pct(st["lat"], .5), p95_ms=_pct(st["lat"], .95),
            recall=round(statistics.mean(st["recs"]), 4),
            precision=round(statistics.mean(st["precs"]), 4),
            f1=round(statistics.mean(st["f1s"]), 4),
            raw_f1=round(statistics.mean(st["raw_f1s"]), 4),
            found_med=int(statistics.median(st["founds"])),
            block_rate=round(st["blocks"] / st["n"], 3),
            ok_rate=round(st["oks"] / st["n"], 3),
            note=st["note"], error=st["err"],
        ))
    ranked = sorted(results, key=lambda r: (-r.f1, r.p50_ms))
    return {
        "pubs": pubs, "runs": runs,
        "gold_window_posts": {p: len(o.gold_slugs) for p, o in oracles.items()},
        "backends_available": [b.name for b in backends],
        "candidates_run": [r.name for r in results],
        "candidates_skipped": skipped,
        "leaderboard": [asdict(r) for r in ranked],
    }


def format_leaderboard(res: dict) -> str:
    L = []
    gold = ", ".join(f"{p}={n}" for p, n in res["gold_window_posts"].items())
    L.append(f"substack discovery race — window gold: {gold} (runs="
             f"{res['runs']}, scored after date-window filter)")
    L.append(f"backends: {', '.join(res['backends_available']) or 'NONE'}")
    L.append("")
    hdr = (f"{'candidate':24} {'brkt':8} {'F1':>6} {'recall':>7} {'prec':>6} "
           f"{'rawF1':>6} {'found':>6} {'p50ms':>8} {'p95ms':>8} {'block':>6}")
    L.append(hdr); L.append("-" * len(hdr))
    for r in res["leaderboard"]:
        L.append(f"{r['name']:24} {r['bracket']:8} {r['f1']:6.3f} "
                 f"{r['recall']:7.3f} {r['precision']:6.3f} {r['raw_f1']:6.3f} "
                 f"{r['found_med']:6d} {r['p50_ms']:8.1f} {r['p95_ms']:8.1f} "
                 f"{r['block_rate']:6.2f}"
                 + (f"  err: {r['error'][:40]}" if r["error"] else ""))
    if res["candidates_skipped"]:
        L.append("")
        L.append(f"skipped (missing backend/infra/risky-flag): "
                 f"{', '.join(res['candidates_skipped'])}")
    return "\n".join(L)
