"""Pipeline — the seed task end-to-end, chaining the stage winners.

  "Crawl the internal site completely; build a searchable index; answer the
   query set with the exact pages; deliver a report."

crawl (best available crawler) -> the driver already dedups + respects robots ->
index (best available engine) -> run the query set -> write report + saved pages.
Emits the two-track scorecard: machinery (crawl F1 / js_recall / robots gate /
extract fidelity / search recall) hard-scored; the report prose is advisory.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .build_fixtures import slug
from .crawl import build_candidates, crawl_site
from .index import ALL_INDEXES
from .oracle import Oracle, norm_path
from .site_server import SiteServer

OUT = Path(__file__).parent.parent / "out" / "site1"

# preference order (strongest first) — pipeline uses the best AVAILABLE.
# crawl4ai first: fastest COMPLETE browser (6.1s vs playwright 13s) in the race.
CRAWLER_PREF = ["crawl4ai-crawl", "playwright-crawl", "selenium-crawl",
                "jsdom-crawl", "scrapling-bfs", "curl_cffi-bfs", "stdlib-bfs"]
# qdrant first: the only engine that clears the HARD (semantic+typo) query set.
INDEX_PREF = ["qdrant", "meilisearch", "tantivy", "stdlib-bm25"]


def _pick_crawler(name=None):
    cands = {c.name: c for c in build_candidates() if c.available()}
    if name:
        return cands.get(name)
    for n in CRAWLER_PREF:
        if n in cands:
            return cands[n]
    return None


def _pick_index(name=None):
    avail = {ix.name: ix for ix in ALL_INDEXES if ix.available()}
    if name:
        return avail.get(name)
    for n in INDEX_PREF:
        if n in avail:
            return avail[n]
    return avail.get("stdlib-bm25")


def run_pipeline(crawler=None, index=None, k: int = 3) -> dict:
    o = Oracle()
    srv = SiteServer()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pages").mkdir(exist_ok=True)
    t0 = time.perf_counter()
    try:
        cand = _pick_crawler(crawler)
        if not cand:
            return {"error": "no crawler available"}
        cout = crawl_site(cand, srv.base, srv, max_depth=6)
        # normalize crawled corpus -> {path: {title, body_text}}
        corpus = {}
        for ident, page in cout.pages.items():
            corpus[norm_path(ident)] = page

        ix = _pick_index(index)
        ix.build(corpus)
        answers = {}
        for item in o.queries:
            answers[item["q"]] = ix.search(item["q"], k=k)
        try: ix.close()
        except Exception: pass
    finally:
        wall = time.perf_counter() - t0
        forbidden = srv.forbidden_hits()
        requests = srv.request_count()
        srv.stop()

    # scores
    crawl_sc = o.score_crawl(cout.found, forbidden_hits=forbidden)
    extract_sc = o.score_extract(corpus)
    search_sc = o.score_search(answers, k=k)

    # deliverable
    for path, page in corpus.items():
        (OUT / "pages" / f"{slug(path)}.json").write_text(
            json.dumps({"path": path, **page}, indent=2))
    report = {
        "seed_task": "Crawl the internal site; index it; answer the queries; report.",
        "crawler": cand.name, "crawler_kind": cand.kind,
        "index": ix.name,
        "pages_found": sorted(o.gold_crawl & {norm_path(p) for p in corpus}),
        "answers": {item["q"]: answers[item["q"]] for item in o.queries},
        "requests": requests, "forbidden_hits": forbidden,
        "wall_s": round(wall, 2),
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2))

    return {
        "outdir": str(OUT), "crawler": cand.name, "crawler_kind": cand.kind,
        "index": ix.name, "wall_s": round(wall, 2), "requests": requests,
        "crawl": crawl_sc.__dict__, "extract": extract_sc.__dict__,
        "search": search_sc.__dict__,
    }


def score_pipeline(res: dict) -> dict:
    """Hard-track summary + PASS/FAIL gates."""
    if "error" in res:
        return res
    c, s = res["crawl"], res["search"]
    gates = {
        "report_saved": (OUT / "report.json").exists(),
        "robots_respected": c["robots_violations"] == 0,
        "crawl_recall_ok": c["recall"] >= 0.75,
        "search_recall_ok": s["recall"] >= 0.5,
    }
    return {"outdir": res["outdir"], "crawler": res["crawler"],
            "crawler_kind": res["crawler_kind"], "index": res["index"],
            "wall_s": res["wall_s"], "requests": res["requests"],
            "crawl_f1": c["f1"], "crawl_recall": c["recall"],
            "js_recall": c["js_recall"], "robots_violations": c["robots_violations"],
            "extract_title_acc": res["extract"]["title_acc"],
            "extract_body_f1": res["extract"]["body_f1"],
            "search_recall": s["recall"], "search_mrr": s["mrr"],
            "gates": gates, "all_gates_pass": all(gates.values())}
