"""Races — crawl / extract / index. Each runs available()-gated candidates,
scores vs the oracle, and builds a leaderboard. Per-candidate try/except so a
broken entrant never kills the race (scrapler-eval convention).

  crawl_race  : which crawler reaches the full site — and does a browser earn its
                cost over a static fetcher on the JS-nav wall? (robots gate hard.)
  extract_race: page HTML -> title/body fidelity vs gold.
  index_race  : which search engine answers the query set best over the corpus?
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .build_fixtures import slug
from .crawl import build_candidates, crawl_site
from .extract import ALL_EXTRACTORS, available_extractors
from .index import ALL_INDEXES
from .oracle import Oracle
from .site_server import SiteServer

FIX = Path(__file__).parent.parent / "fixtures" / "site1"


def _pct(xs, p):
    if not xs: return 0.0
    xs = sorted(xs); k = (len(xs) - 1) * p
    lo = int(k); hi = min(lo + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def _corpus_html() -> dict:
    """path -> raw HTML for every real page (extract/index races)."""
    o = Oracle()
    out = {}
    for path in o.page_gold:
        f = FIX / "pages" / f"{slug(path)}.html"
        if f.exists():
            out[path] = f.read_text()
    return out


def _gold_corpus() -> dict:
    """path -> {title, body_text} straight from gold (index race, isolates
    search quality from extract/crawl noise)."""
    o = Oracle()
    return {p: {"title": g["title"], "body_text": g["body_text"]}
            for p, g in o.page_gold.items()}


# ---------------- crawl race ----------------
@dataclass
class CrawlRow:
    name: str
    kind: str
    runs: int
    f1: float
    recall: float
    precision: float
    js_recall: float
    depth_ok: bool
    extra: int
    robots_violations: int
    requests: int
    p50_ms: float
    ok_rate: float
    note: str = ""
    error: str = ""


def crawl_race(runs: int = 1, max_depth: int = 6) -> dict:
    o = Oracle()
    srv = SiteServer()
    all_c = build_candidates()
    cands = [c for c in all_c if c.available()]
    skipped = [c.name for c in all_c if not c.available()]
    rows: list[CrawlRow] = []
    try:
        for c in cands:
            f1s, recs, precs, jss, extras, viols, reqs, lats = \
                [], [], [], [], [], [], [], []
            depth_ok = False; oks = 0; err = ""
            for _ in range(runs):
                try:
                    out = crawl_site(c, srv.base, srv, max_depth=max_depth)
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"
                    continue
                if out.error and not out.found:
                    err = out.error
                sc = o.score_crawl(out.found, forbidden_hits=out.forbidden_hits)
                f1s.append(sc.f1); recs.append(sc.recall); precs.append(sc.precision)
                jss.append(sc.js_recall); extras.append(sc.extra)
                viols.append(sc.robots_violations); reqs.append(out.requests)
                lats.append(out.latency_ms)
                depth_ok = depth_ok or sc.depth_ok
                if out.found: oks += 1
            if not f1s:
                rows.append(CrawlRow(c.name, c.kind, runs, 0, 0, 0, 0, False,
                                     0, 0, 0, 0.0, 0.0, error=err))
                continue
            rows.append(CrawlRow(
                name=c.name, kind=c.kind, runs=runs,
                f1=round(statistics.median(f1s), 4),
                recall=round(statistics.median(recs), 4),
                precision=round(statistics.median(precs), 4),
                js_recall=round(statistics.median(jss), 4),
                depth_ok=depth_ok, extra=int(statistics.median(extras)),
                robots_violations=int(statistics.median(viols)),
                requests=int(statistics.median(reqs)),
                p50_ms=_pct(lats, .5), ok_rate=round(oks / runs, 3), error=err))
    finally:
        srv.stop()
    # rank: politeness first (violators sink), then F1, js_recall, speed
    ranked = sorted(rows, key=lambda r: (r.robots_violations > 0, -r.f1,
                                         -r.js_recall, r.p50_ms))
    return {"stage": "crawl", "runs": runs, "gold_pages": len(o.gold_crawl),
            "js_only_pages": len(o.js_only),
            "candidates_run": [r.name for r in rows],
            "candidates_skipped": skipped,
            "leaderboard": [asdict(r) for r in ranked]}


def format_crawl(res: dict) -> str:
    L = [f"crawl race — internal site (gold={res['gold_pages']} pages, "
         f"{res['js_only_pages']} JS-only, runs={res['runs']})", ""]
    hdr = (f"{'candidate':18} {'kind':7} {'F1':>6} {'rec':>6} {'prec':>6} "
           f"{'jsRec':>6} {'dpth':>4} {'xtra':>4} {'robV':>4} {'reqs':>5} "
           f"{'p50ms':>8}")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        flag = "  ⚠robots" if r["robots_violations"] else ""
        L.append(f"{r['name']:18} {r['kind']:7} {r['f1']:6.3f} {r['recall']:6.3f} "
                 f"{r['precision']:6.3f} {r['js_recall']:6.3f} "
                 f"{('Y' if r['depth_ok'] else 'n'):>4} {r['extra']:4d} "
                 f"{r['robots_violations']:4d} {r['requests']:5d} "
                 f"{r['p50_ms']:8.1f}{flag}")
    if res["candidates_skipped"]:
        L += ["", f"skipped (missing dep/infra): {', '.join(res['candidates_skipped'])}"]
    return "\n".join(L)


# ---------------- endurance race ----------------
def endurance_race(seconds: float = 12.0, max_pages: int = 200_000) -> dict:
    """Stress test: how long can each engine 'crawl and crawl and crawl'?
    Point it at the endless maze with a wall-time budget and count the TURNS
    (successful page-fetches) it sustains, plus throughput, depth reached, and
    whether it stayed stable. No gold — this is reach/stamina, not accuracy."""
    srv = SiteServer()
    all_c = build_candidates()
    cands = [c for c in all_c if c.available()]
    skipped = [c.name for c in all_c if not c.available()]
    rows = []
    try:
        for c in cands:
            try:
                out = crawl_site(c, srv.base, srv, max_depth=10**9,
                                 max_pages=max_pages, seed="/maze",
                                 max_seconds=seconds)
                secs = out.latency_ms / 1000 or 1e-9
                rows.append({
                    "name": c.name, "kind": c.kind,
                    "turns": out.pages_crawled,
                    "pages_per_s": round(out.pages_crawled / secs, 1),
                    "depth": out.depth_reached, "requests": out.requests,
                    "wall_s": round(out.latency_ms / 1000, 1),
                    "stop": out.stop_reason,
                    "stable": out.stop_reason in ("timeout", "exhausted", "budget")
                    and (out.pages_crawled > 0),
                    "error": out.error[:120]})
            except Exception as e:
                rows.append({"name": c.name, "kind": c.kind, "turns": 0,
                             "pages_per_s": 0.0, "depth": 0, "requests": 0,
                             "wall_s": 0.0, "stop": "error", "stable": False,
                             "error": f"{type(e).__name__}: {e}"})
    finally:
        srv.stop()
    ranked = sorted(rows, key=lambda r: -r["turns"])
    return {"stage": "endurance", "budget_s": seconds, "max_pages": max_pages,
            "leaderboard": ranked, "candidates_skipped": skipped}


def format_endurance(res: dict) -> str:
    L = [f"endurance race — endless maze, budget={res['budget_s']}s "
         f"(turns = pages sustained before stop)", ""]
    hdr = (f"{'candidate':18} {'kind':7} {'turns':>7} {'pg/s':>8} {'depth':>6} "
           f"{'wall_s':>7} {'stop':>9} {'stable':>7}")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        L.append(f"{r['name']:18} {r['kind']:7} {r['turns']:7d} "
                 f"{r['pages_per_s']:8.1f} {r['depth']:6d} {r['wall_s']:7.1f} "
                 f"{r['stop']:>9} {('yes' if r['stable'] else 'NO'):>7}"
                 + ("  " + r["error"] if r["error"] else ""))
    if res["candidates_skipped"]:
        L += ["", f"skipped: {', '.join(res['candidates_skipped'])}"]
    return "\n".join(L)


# ---------------- extract race ----------------
def extract_race() -> dict:
    o = Oracle()
    corpus = _corpus_html()
    rows = []
    for e in available_extractors():
        pages, t0 = {}, time.perf_counter()
        try:
            for path, html in corpus.items():
                pages[path] = e.extract(html)
            dt = (time.perf_counter() - t0) * 1000
            sc = o.score_extract(pages)
            rows.append({"name": e.name, "pages": sc.pages_scored,
                         "title_acc": sc.title_acc, "body_f1": sc.body_f1,
                         "ms": round(dt, 1), "error": ""})
        except Exception as ex:
            rows.append({"name": e.name, "pages": 0, "title_acc": 0.0,
                         "body_f1": 0.0, "ms": 0.0,
                         "error": f"{type(ex).__name__}: {ex}"})
    ranked = sorted(rows, key=lambda r: (-r["body_f1"], -r["title_acc"], r["ms"]))
    skipped = [e.name for e in ALL_EXTRACTORS if not e.available()]
    return {"stage": "extract", "corpus_pages": len(corpus),
            "leaderboard": ranked, "candidates_skipped": skipped}


def format_extract(res: dict) -> str:
    L = [f"extract race — {res['corpus_pages']} pages", ""]
    hdr = f"{'extractor':14} {'pages':>6} {'title_acc':>10} {'body_f1':>8} {'ms':>8}"
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        L.append(f"{r['name']:14} {r['pages']:6d} {r['title_acc']:10.3f} "
                 f"{r['body_f1']:8.3f} {r['ms']:8.1f}"
                 + ("  ERR" if r["error"] else ""))
    if res["candidates_skipped"]:
        L += ["", f"skipped: {', '.join(res['candidates_skipped'])}"]
    return "\n".join(L)


# ---------------- index race ----------------
def index_race(k: int = 3, corpus: dict | None = None) -> dict:
    o = Oracle()
    corpus = corpus if corpus is not None else _gold_corpus()
    rows = []
    for ix in ALL_INDEXES:
        if not ix.available():
            continue
        try:
            t0 = time.perf_counter()
            ix.build(corpus)
            build_ms = (time.perf_counter() - t0) * 1000
            results, t1 = {}, time.perf_counter()
            for item in o.queries:
                results[item["q"]] = ix.search(item["q"], k=k)
            q_ms = (time.perf_counter() - t1) * 1000
            sc = o.score_search(results, k=k)
            rows.append({"name": ix.name, "recall": sc.recall,
                         "p_at_k": sc.precision_at_k, "mrr": sc.mrr,
                         "by_tier": sc.by_tier,
                         "build_ms": round(build_ms, 1),
                         "q_ms": round(q_ms, 1), "error": ""})
        except Exception as ex:
            rows.append({"name": ix.name, "recall": 0.0, "p_at_k": 0.0,
                         "mrr": 0.0, "by_tier": {}, "build_ms": 0.0, "q_ms": 0.0,
                         "error": f"{type(ex).__name__}: {ex}"})
        finally:
            try: ix.close()
            except Exception: pass
    ranked = sorted(rows, key=lambda r: (-r["recall"], -r["mrr"], r["q_ms"]))
    skipped = [ix.name for ix in ALL_INDEXES if not ix.available()]
    return {"stage": "index", "k": k, "corpus_pages": len(corpus),
            "queries": len(o.queries), "leaderboard": ranked,
            "candidates_skipped": skipped}


def format_index(res: dict) -> str:
    L = [f"index race — {res['corpus_pages']} docs, {res['queries']} queries, "
         f"k={res['k']}", ""]
    hdr = (f"{'engine':14} {'recall':>7} {'lex':>5} {'sem':>5} {'typo':>5} "
           f"{'prec':>5} {'mrr':>6} {'build_ms':>9} {'q_ms':>7}")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        t = r.get("by_tier", {})
        L.append(f"{r['name']:14} {r['recall']:7.3f} "
                 f"{t.get('lexical',0):5.2f} {t.get('semantic',0):5.2f} "
                 f"{t.get('typo',0):5.2f} {t.get('precision',0):5.2f} "
                 f"{r['mrr']:6.3f} {r['build_ms']:9.1f} {r['q_ms']:7.1f}"
                 + ("  ERR" if r["error"] else ""))
    if res["candidates_skipped"]:
        L += ["", f"skipped (missing dep/container): {', '.join(res['candidates_skipped'])}"]
    return "\n".join(L)
