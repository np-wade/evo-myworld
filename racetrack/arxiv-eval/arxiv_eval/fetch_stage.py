"""Stage 3 — Fetch: download the abstract page + PDF for chosen papers.

Candidates = the fetch backends themselves (urllib / curl_cffi / scrapling),
racing on the same paper set. Scored against the frozen pool fixtures:

  abs_ok    -- abstract page fetched and contains the paper's title
  pdf_valid -- starts with %PDF and is within 25% of the fixture's byte size
               (arXiv can regenerate PDFs, so exact-hash is a bonus, not a gate)
  pdf_exact -- byte-identical to the fixture (bonus signal)
  block rate + p50/p95 per document

Politeness: serial fetches with a delay; default samples 5 pool papers so a
full 3-backend race stays ~60 requests.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from pathlib import Path

from .discover import DATE
from .fetchers import Backend, available_backends

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _pool_ids(date: str) -> list[str]:
    d = json.loads((FIXTURES / date / "pool.json").read_text())
    return [p["id"] for p in d["pool"]]


def fetch_race(date: str = DATE, sample: int = 5, polite_s: float = 1.5,
               backend: str = "") -> dict:
    ids = _pool_ids(date)[:sample]
    backends = available_backends()
    if backend:
        backends = [b for b in backends if b.name == backend]
    listing = json.loads((FIXTURES / date / "listing.json").read_text())
    titles = {p["id"]: p["title"] for p in listing["papers"]}

    rows = []
    for be in backends:
        lat, abs_ok, pdf_valid, pdf_exact, blocks = [], 0, 0, 0, 0
        err = ""
        for pid in ids:
            gold_pdf = FIXTURES / date / "pdf" / f"{pid}.pdf"
            r = be.get(f"https://arxiv.org/abs/{pid}")
            lat.append(r.latency_ms)
            if r.blocked: blocks += 1
            if r.ok and titles.get(pid, "")[:40].lower() in r.text.lower():
                abs_ok += 1
            elif r.error:
                err = r.error
            time.sleep(polite_s)

            t0 = time.perf_counter()
            rp = be.get(f"https://arxiv.org/pdf/{pid}.pdf", timeout=90)
            lat.append((time.perf_counter() - t0) * 1000)
            if rp.blocked: blocks += 1
            body = rp.content
            if rp.ok and body[:4] == b"%PDF":
                if gold_pdf.exists():
                    gsize = gold_pdf.stat().st_size
                    if abs(len(body) - gsize) <= 0.25 * gsize:
                        pdf_valid += 1
                    if (len(body) == gsize and hashlib.sha256(body).digest()
                            == hashlib.sha256(gold_pdf.read_bytes()).digest()):
                        pdf_exact += 1
                else:
                    pdf_valid += 1
            elif rp.error:
                err = rp.error
            time.sleep(polite_s)
        n = len(ids)
        rows.append({
            "backend": be.name, "papers": n,
            "abs_ok": round(abs_ok / n, 3), "pdf_valid": round(pdf_valid / n, 3),
            "pdf_exact": round(pdf_exact / n, 3),
            "block_rate": round(blocks / (2 * n), 3),
            "p50_ms": round(statistics.median(lat), 1),
            "p95_ms": round(sorted(lat)[max(0, int(len(lat) * .95) - 1)], 1),
            "error": err,
        })
    rows.sort(key=lambda r: (-(r["abs_ok"] + r["pdf_valid"]), r["p50_ms"]))
    return {"date": date, "sample_ids": ids, "leaderboard": rows}


def format_fetch_leaderboard(res: dict) -> str:
    L = [f"stage-3 fetch race — {res['date']}  "
         f"({len(res['sample_ids'])} pool papers, abs+pdf each)", ""]
    hdr = (f"{'backend':12} {'abs-ok':>7} {'pdf-ok':>7} {'exact':>6} "
           f"{'block':>6} {'p50ms':>8} {'p95ms':>9}")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        L.append(f"{r['backend']:12} {r['abs_ok']:7.2f} {r['pdf_valid']:7.2f} "
                 f"{r['pdf_exact']:6.2f} {r['block_rate']:6.2f} "
                 f"{r['p50_ms']:8.1f} {r['p95_ms']:9.1f}"
                 + (f"  err: {r['error'][:50]}" if r["error"] else ""))
    return "\n".join(L)
