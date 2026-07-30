"""End-to-end pipeline — the seed task, ONE prompt -> report, normal scraping
only, chained from each stage's current race winner:

  1 Discover  list-month (paginated month listing scrape)
  2 Filter    abs-bisect (submission-day ID band via /abs/ binary search)
  3 Pick-5    keyword-relevance heuristic over titles (ADVISORY judgment half)
  4 Fetch     the 5 PDFs via the chosen backend
  5 Parse     pymupdf text extraction of the saved PDFs
  6 Report    out/<date>/report.{json,md} + pdf/ + md/ + manifest w/ sha256

Then scores the run against the oracle: discovery+filter F1, table-field
accuracy, save/deliver integrity (hard track) and pick-5 pool overlap
(advisory track). The arXiv API is never touched here.
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics
import time
from pathlib import Path

from .discover import DATE, ListingScrape
from .fetchers import available_backends
from .filter import AbsBisect
from .oracle import Oracle

FIXTURES = Path(__file__).parent.parent / "fixtures"

# advisory pick-5 heuristic: terms that signal "useful for a local AI system"
LOCAL_AI_TERMS = [
    "local", "on-device", "edge", "quantiz", "efficient", "inference",
    "small model", "small language model", "distill", "compress", "kv cache",
    "serving", "latency", "low-resource", "offline", "cpu", "spars",
    "prun", "memory", "lightweight", "billion", "1b", "3b", "7b",
]


def _relevance(title: str) -> int:
    t = title.lower()
    return sum(1 for k in LOCAL_AI_TERMS if k in t)


def _norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def run_pipeline(date: str = DATE, backend: str = "curl_cffi",
                 outdir: str = "", polite_s: float = 1.5) -> dict:
    t_start = time.perf_counter()
    out = Path(outdir) if outdir else Path(__file__).parent.parent / "out" / date
    (out / "pdf").mkdir(parents=True, exist_ok=True)
    (out / "md").mkdir(parents=True, exist_ok=True)
    names = [b.name for b in available_backends()]
    be = next(b for b in available_backends()
              if b.name == (backend if backend in names else names[0]))

    # 1 discover + 2 filter
    dout = ListingScrape(be).discover()
    bis = AbsBisect(be, date, polite_s=polite_s)
    day_ids = sorted(bis.apply(dout))

    # table rows from listing metadata (no extra fetches)
    rows = [{"id": i,
             "title": dout.id_meta.get(i, {}).get("title", ""),
             "authors": dout.id_meta.get(i, {}).get("authors", [])}
            for i in day_ids]

    # 3 pick-5 (advisory)
    picks = sorted(rows, key=lambda r: -_relevance(r["title"]))[:5]
    pick_ids = [p["id"] for p in picks]

    # 4 fetch + save the 5 PDFs; 5 parse them
    manifest = []
    for pid in pick_ids:
        time.sleep(polite_s)
        r = be.get(f"https://arxiv.org/pdf/{pid}.pdf", timeout=90)
        ok = r.ok and r.content[:4] == b"%PDF"
        pdf_path = out / "pdf" / f"{pid}.pdf"
        if ok:
            pdf_path.write_bytes(r.content)
        md_chars = 0
        try:
            import fitz
            with fitz.open(pdf_path) as doc:
                text = "\n".join(p.get_text() for p in doc)
            (out / "md" / f"{pid}.md").write_text(text)
            md_chars = len(text)
        except Exception:
            pass
        manifest.append({
            "id": pid, "pdf": str(pdf_path), "ok": ok,
            "bytes": len(r.content) if ok else 0,
            "sha256": hashlib.sha256(r.content).hexdigest() if ok else "",
            "md_chars": md_chars, "blocked": r.blocked,
        })

    report = {
        "prompt": f"List all arXiv papers published on {date}; pick the 5 most "
                  f"beneficial to building a local AI system; save the PDFs.",
        "date": date, "backend": be.name,
        "n_papers": len(rows), "papers": rows,
        "picks": picks, "manifest": manifest,
        "requests": dout.requests + bis.fetches + len(pick_ids),
        "wall_s": round(time.perf_counter() - t_start, 1),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    md = [f"# arXiv report — {date}", "",
          f"{len(rows)} papers found. Picks for local-AI relevance:", ""]
    md += [f"- **{p['id']}** {p['title']}" for p in picks]
    md += ["", "| id | title | authors |", "|---|---|---|"]
    md += [f"| {r['id']} | {r['title'][:80]} | {len(r['authors'])} |"
           for r in rows]
    (out / "report.md").write_text("\n".join(md))

    return {"report": report, "outdir": str(out)}


def score_pipeline(res: dict, date: str = DATE) -> dict:
    """Hard-score the machinery vs gold; advisory-score the pick-5."""
    oracle = Oracle(date)
    report = res["report"]
    ids = {r["id"] for r in report["papers"]}
    disc = oracle.score_discovery(ids)

    # table fields: title accuracy over the rows that are true gold papers
    tmatch, ttot = 0, 0
    for r in report["papers"]:
        g = oracle.papers.get(r["id"])
        if not g:
            continue
        ttot += 1
        if _norm_title(r["title"]) == _norm_title(g["title"]):
            tmatch += 1

    man = report["manifest"]
    saved_ok = sum(1 for m in man if m["ok"] and m["bytes"] > 10_000)
    parsed_ok = sum(1 for m in man if m["md_chars"] > 5_000)

    pool = {p["id"] for p in json.loads(
        (FIXTURES / date / "pool.json").read_text())["pool"]}
    picks = {p["id"] for p in report["picks"]}

    hard = {
        "discovery_f1": disc.f1, "recall": disc.recall,
        "precision": disc.precision, "found": disc.found, "gold": disc.gold,
        "title_acc": round(tmatch / ttot, 4) if ttot else 0.0,
        "save_ok": f"{saved_ok}/{len(man)}",
        "parse_ok": f"{parsed_ok}/{len(man)}",
        "requests": report["requests"], "wall_s": report["wall_s"],
    }
    advisory = {"pick5_pool_overlap": f"{len(picks & pool)}/{len(picks)}"}
    return {"hard": hard, "advisory": advisory}
