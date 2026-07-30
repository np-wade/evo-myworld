"""Stage 4 — Parse: PDF -> text, scored against the LaTeX-derived gold. OFFLINE
(runs on the frozen fixture PDFs; no network).

Baseline candidates are pure-Python extractors (available()-gated):

  pymupdf   -- fitz text extraction
  pdfminer  -- pdfminer.six high-level extract_text
  pypdf     -- pypdf page.extract_text

The heavy OCR contenders from the corpus (olmocr, MinerU, rust-paddle-ocr) are
docker/GPU-scale — they slot in later behind the same Candidate interface.

Score per paper: section-heading recall vs gold_from_latex.section_headings
(math stripped, whitespace collapsed, containment match) + extraction latency.
Equation/table-count deltas need structure-aware parsers, so they start with
the OCR contenders, not these text baselines.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from pathlib import Path

from .discover import DATE

FIXTURES = Path(__file__).parent.parent / "fixtures"

_MATH = re.compile(r"\$[^$]*\$|\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?")
_WS = re.compile(r"[^a-z0-9]+")


def _norm(s: str) -> str:
    return _WS.sub(" ", _MATH.sub(" ", s).lower()).strip()


def heading_recall(text: str, headings: list[str]) -> float:
    if not headings:
        return 0.0
    hay = _norm(text)
    hit = 0
    for h in headings:
        n = _norm(h)
        if len(n) >= 6 and (n in hay or n[:40].strip() in hay):
            hit += 1
    return hit / len(headings)


class Parser:
    key = "?"
    def available(self) -> bool: return False
    def extract(self, pdf: Path) -> str: ...


class PyMuPDF(Parser):
    key = "pymupdf"
    def available(self) -> bool:
        try: import fitz; return True  # noqa
        except Exception: return False
    def extract(self, pdf: Path) -> str:
        import fitz
        with fitz.open(pdf) as doc:
            return "\n".join(p.get_text() for p in doc)


class PdfMiner(Parser):
    key = "pdfminer"
    def available(self) -> bool:
        try: import pdfminer; return True  # noqa
        except Exception: return False
    def extract(self, pdf: Path) -> str:
        from pdfminer.high_level import extract_text
        return extract_text(str(pdf))


class PyPdf(Parser):
    key = "pypdf"
    def available(self) -> bool:
        try: import pypdf; return True  # noqa
        except Exception: return False
    def extract(self, pdf: Path) -> str:
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "")
                         for p in PdfReader(str(pdf)).pages)


ALL_PARSERS = [PyMuPDF(), PdfMiner(), PyPdf()]


def parse_race(date: str = DATE, sample: int = 0) -> dict:
    gold_dir = FIXTURES / date / "gold"
    pdf_dir = FIXTURES / date / "pdf"
    papers = []
    for gp in sorted(gold_dir.glob("*.json")):
        g = json.loads(gp.read_text())
        pdf = pdf_dir / f"{g['id']}.pdf"
        heads = g.get("gold_from_latex", {}).get("section_headings", [])
        if pdf.exists() and heads:
            papers.append((g["id"], pdf, heads))
    if sample:
        papers = papers[:sample]

    rows, skipped = [], []
    for p in ALL_PARSERS:
        if not p.available():
            skipped.append(p.key)
            continue
        recs, lat, err, fails = [], [], "", 0
        for pid, pdf, heads in papers:
            t0 = time.perf_counter()
            try:
                text = p.extract(pdf)
            except Exception as e:
                fails += 1; err = f"{pid}: {type(e).__name__}: {e}"
                recs.append(0.0); lat.append((time.perf_counter()-t0)*1000)
                continue
            lat.append((time.perf_counter() - t0) * 1000)
            recs.append(heading_recall(text, heads))
        rows.append({
            "parser": p.key, "papers": len(papers), "fails": fails,
            "heading_recall": round(statistics.mean(recs), 4) if recs else 0.0,
            "recall_med": round(statistics.median(recs), 4) if recs else 0.0,
            "p50_ms": round(statistics.median(lat), 1) if lat else 0.0,
            "error": err,
        })
    rows.sort(key=lambda r: (-r["heading_recall"], r["p50_ms"]))
    return {"date": date, "papers": len(papers),
            "parsers_skipped": skipped, "leaderboard": rows}


def format_parse_leaderboard(res: dict) -> str:
    L = [f"stage-4 parse race — {res['date']}  ({res['papers']} fixture PDFs, "
         f"scored on gold section-heading recall)", ""]
    hdr = (f"{'parser':10} {'head-rec':>9} {'median':>7} {'p50ms':>8} "
           f"{'fails':>6}")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        L.append(f"{r['parser']:10} {r['heading_recall']:9.3f} "
                 f"{r['recall_med']:7.3f} {r['p50_ms']:8.1f} {r['fails']:6d}"
                 + (f"  err: {r['error'][:60]}" if r["error"] else ""))
    if res["parsers_skipped"]:
        L.append(f"skipped: {', '.join(res['parsers_skipped'])}")
    return "\n".join(L)
