"""Stage 2 — Filter: narrow discovered IDs to the prompt's date criteria.

Gold is submittedDate=2026-07-14. The month listing page (new arXiv UI) has NO
per-day grouping, so dates must be recovered another way — still normal
scraping only. Candidates:

  passthrough  -- no-op baseline (stage-1 output as-is)
  annc-d0/d1/d1d2 -- announcement-day set-ops over DiscoverOut.id_dates, IF the
                  discovery source exposed day headings (the new month UI does
                  not; kept for sources that do)
  abs-bisect   -- NETWORK: arXiv IDs are assigned sequentially by submission
                  time, so the target day is a contiguous ID band within the
                  month. Binary-search the sorted in-month IDs, reading the
                  "[Submitted on ...]" line from /abs/ pages, to find the
                  band's edges in ~2*log2(N) fetches (~26 for a 6k month).

Offline filters share one stage-1 fetch per run; abs-bisect adds its own
(politeness-limited) abs-page fetches and is timed separately.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass

from .discover import DATE, MONTH, DiscoverOut
from .fetchers import Backend


def _next_biz(d: dt.date) -> dt.date:
    d += dt.timedelta(days=1)
    while d.weekday() >= 5:  # Sat/Sun
        d += dt.timedelta(days=1)
    return d


def announce_days(date: str, n: int) -> list[str]:
    """The n business days after `date` (candidate announcement days)."""
    d, out = dt.date.fromisoformat(date), []
    for _ in range(n):
        d = _next_biz(d)
        out.append(d.isoformat())
    return out


@dataclass
class FilterCandidate:
    key: str
    days: list[str] | None  # None = passthrough

    def apply(self, dout: DiscoverOut) -> set[str]:
        if self.days is None:
            return set(dout.ids)
        if not dout.id_dates:
            return set(dout.ids)  # no date info -> can't narrow (SERP path)
        keep = set(self.days)
        return {i for i in dout.ids if dout.id_dates.get(i) in keep}


_SUBMITTED = re.compile(r"\[Submitted on (\d{1,2}) ([A-Z][a-z]{2})[a-z]* (\d{4})")
_MON = {m: i + 1 for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}


class AbsBisect:
    """Recover the target day's contiguous ID band by binary-searching sorted
    in-month IDs against the '[Submitted on ...]' line of /abs/ pages."""
    key = "abs-bisect"
    days = None

    def __init__(self, backend: Backend, date: str = DATE,
                 polite_s: float = 1.5):
        self.backend, self.date, self.polite_s = backend, date, polite_s
        self._cache: dict[str, str | None] = {}
        self.fetches = 0
        self.elapsed_ms = 0.0

    def _date_of(self, arxiv_id: str) -> str | None:
        if arxiv_id in self._cache:
            return self._cache[arxiv_id]
        t0 = time.perf_counter()
        r = self.backend.get(f"https://arxiv.org/abs/{arxiv_id}")
        self.fetches += 1
        self.elapsed_ms += (time.perf_counter() - t0) * 1000
        m = _SUBMITTED.search(r.text)
        iso = (f"{m.group(3)}-{_MON[m.group(2)]:02d}-{int(m.group(1)):02d}"
               if m else None)
        self._cache[arxiv_id] = iso
        time.sleep(self.polite_s)
        return iso

    def _probe(self, ids: list[str], i: int) -> str | None:
        # walk right past unparseable pages (withdrawn/blocked) so the
        # bisect always gets a date
        for j in range(i, min(i + 4, len(ids))):
            d = self._date_of(ids[j])
            if d:
                return d
        return None

    def apply(self, dout: DiscoverOut) -> set[str]:
        y, mo = self.date[2:4], self.date[5:7]
        pre = f"{y}{mo}."          # 2026-07 -> "2607."
        ids = sorted((i for i in dout.ids if i.startswith(pre)),
                     key=lambda i: int(i.split(".")[1]))
        if not ids:
            return set()

        def first_idx(pred) -> int:
            lo, hi = 0, len(ids)   # first index where pred(date) is True
            while lo < hi:
                mid = (lo + hi) // 2
                d = self._probe(ids, mid)
                if d is None or pred(d):
                    hi = mid
                else:
                    lo = mid + 1
            return lo

        start = first_idx(lambda d: d >= self.date)
        end = first_idx(lambda d: d > self.date)
        return set(ids[start:end])


def build_filters(date: str = DATE,
                  backend: Backend | None = None) -> list[FilterCandidate]:
    d1, d2 = announce_days(date, 2)
    out = [
        FilterCandidate("passthrough", None),
        FilterCandidate("annc-d0", [date]),
        FilterCandidate("annc-d1", [d1]),
        FilterCandidate("annc-d1d2", [d1, d2]),
    ]
    if backend is not None:
        out.append(AbsBisect(backend, date))
    return out


def filter_race(date: str = DATE, runs: int = 3, backend: str = "",
                polite_s: float = 2.0) -> dict:
    """Stage 1+2 combo race: one listing fetch per run, every filter applied
    to it offline, scored vs the oracle. Filters cost ~0ms, so p50 = fetch."""
    import statistics
    import time

    from .discover import ListingScrape
    from .fetchers import available_backends
    from .oracle import Oracle

    oracle = Oracle(date)
    backends = available_backends()
    names = [b.name for b in backends]
    pick = backend or ("curl_cffi" if "curl_cffi" in names else names[0])
    be = next(b for b in backends if b.name == pick)
    cand = ListingScrape(be)

    filters = build_filters(date, backend=be)
    per = {f.key: {"recs": [], "precs": [], "f1s": [], "founds": []}
           for f in filters}
    lat, dated_frac = [], []
    for i in range(runs):
        dout = cand.discover()
        lat.append(dout.latency_ms)
        dated_frac.append(len(dout.id_dates) / len(dout.ids) if dout.ids else 0)
        for f in filters:
            sc = oracle.score_discovery(f.apply(dout))
            p = per[f.key]
            p["recs"].append(sc.recall); p["precs"].append(sc.precision)
            p["f1s"].append(sc.f1); p["founds"].append(sc.found)
        if i < runs - 1:
            time.sleep(polite_s)

    rows = [{
        "filter": f.key, "days": f.days,
        "recall": round(statistics.median(per[f.key]["recs"]), 4),
        "precision": round(statistics.median(per[f.key]["precs"]), 4),
        "f1": round(statistics.median(per[f.key]["f1s"]), 4),
        "found_med": int(statistics.median(per[f.key]["founds"])),
        "net_fetches": getattr(f, "fetches", 0),
        "net_ms": round(getattr(f, "elapsed_ms", 0.0), 1),
    } for f in filters]
    rows.sort(key=lambda r: -r["f1"])
    return {
        "date": date, "runs": runs, "stage1": f"list-month/{pick}",
        "gold_papers": len(oracle.gold_ids),
        "fetch_p50_ms": round(statistics.median(lat), 1),
        "dated_id_frac": round(statistics.median(dated_frac), 3),
        "leaderboard": rows,
    }


def format_filter_leaderboard(res: dict) -> str:
    L = [f"stage-2 filter race — {res['date']}  (gold={res['gold_papers']}, "
         f"runs={res['runs']}, stage1={res['stage1']}, "
         f"fetch p50={res['fetch_p50_ms']}ms, "
         f"dated-id frac={res['dated_id_frac']})", ""]
    hdr = (f"{'filter':14} {'F1':>6} {'recall':>7} {'prec':>6} {'found':>6} "
           f"{'net-req':>7} {'net-ms':>8}  days")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        L.append(f"{r['filter']:14} {r['f1']:6.3f} {r['recall']:7.3f} "
                 f"{r['precision']:6.3f} {r['found_med']:6d} "
                 f"{r['net_fetches']:7d} {r['net_ms']:8.1f}  "
                 f"{','.join(r['days'] or ['-'])}")
    return "\n".join(L)
