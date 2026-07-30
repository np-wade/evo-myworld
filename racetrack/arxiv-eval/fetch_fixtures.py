#!/usr/bin/env python3
"""Build the frozen arXiv fixture set for the prompt->report benchmark.

Seed task (Nicholas): "list all arXiv papers published on 2026-07-14, pick the 5
best for building a local AI system, save the PDFs, deliver them."

Scope: cs.LG + cs.AI + cs.CL for 2026-07-14 (submittedDate).

Produces, under fixtures/2026-07-14/ :
  listing.json                 -- discovery GOLD: every paper that day (metadata)
  pool.json                    -- ~N local-AI-relevant candidates (heuristic pick)
  pdf/<id>.pdf                 -- real PDF for each pool paper (save/parse target)
  source/<id>.tex              -- concatenated LaTeX e-print (field GOLD source)
  gold/<id>.json               -- derived per-paper gold fields

Pure stdlib. Polite to arXiv (sleeps between calls). Re-runnable: skips files
already downloaded.
"""
from __future__ import annotations

import io
import json
import re
import sys
import tarfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

DATE = "2026-07-14"
CATS = ["cs.LG", "cs.AI", "cs.CL"]
WINDOW = "[202607140000 TO 202607142359]"
FIX = Path(__file__).parent / "fixtures" / DATE
API = "http://export.arxiv.org/api/query?"
ATOM = "{http://www.w3.org/2005/Atom}"
ARX = "{http://arxiv.org/schemas/atom}"
UA = {"User-Agent": "arxiv-eval-fixture-builder/1.0 (lab benchmark; polite)"}

# Relevance rubric for "building a local AI system" -- weighted keyword proxy.
# This drives ONLY the candidate-pool pick + the advisory relevance score; it is
# never part of the deterministic gold.
KW = {
    3: ["on-device", "on device", "edge device", "quantization", "quantized",
        "int4", "int8", "gguf", "llama.cpp", "local inference", "local llm",
        "kv cache", "kv-cache", "speculative decoding", "distillation",
        "small language model", "slm", "1-bit", "4-bit", "8-bit"],
    2: ["efficient inference", "low-rank", "lora", "qlora", "pruning", "sparsity",
        "mixture of experts", "moe", "retrieval-augmented", "rag", "memory-efficient",
        "latency", "throughput", "compression", "flash attention", "vllm",
        "edge", "mobile", "cpu inference", "offline"],
    1: ["fine-tuning", "fine tuning", "parameter-efficient", "peft", "adapter",
        "inference", "serving", "embedding", "tokenizer", "long context",
        "attention", "transformer", "open-weight", "open source"],
}


def get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


def base_id(entry_id: str) -> str:
    # http://arxiv.org/abs/2607.12345v1 -> 2607.12345
    m = re.search(r"abs/([^v]+)(v\d+)?$", entry_id)
    return m.group(1) if m else entry_id.rsplit("/", 1)[-1]


def parse_entries(xml: str) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for e in root.findall(f"{ATOM}entry"):
        eid = e.findtext(f"{ATOM}id", "")
        cats = [c.get("term") for c in e.findall(f"{ATOM}category")]
        prim = e.find(f"{ARX}primary_category")
        out.append({
            "id": base_id(eid),
            "title": " ".join((e.findtext(f"{ATOM}title", "") or "").split()),
            "authors": [a.findtext(f"{ATOM}name", "")
                        for a in e.findall(f"{ATOM}author")],
            "abstract": " ".join((e.findtext(f"{ATOM}summary", "") or "").split()),
            "published": e.findtext(f"{ATOM}published", ""),
            "categories": cats,
            "primary_category": prim.get("term") if prim is not None else
                                (cats[0] if cats else ""),
        })
    return out


def fetch_listing() -> dict[str, dict]:
    """All papers that day across the 3 cats, deduped by base id."""
    papers: dict[str, dict] = {}
    for cat in CATS:
        start, page = 0, 100
        while True:
            url = API + urllib.parse.urlencode({
                "search_query": f"cat:{cat} AND submittedDate:{WINDOW}",
                "start": start, "max_results": page,
                "sortBy": "submittedDate", "sortOrder": "ascending",
            })
            entries = parse_entries(get(url).decode())
            if not entries:
                break
            for p in entries:
                papers.setdefault(p["id"], p)
            print(f"  {cat}: +{len(entries)} (start={start}) total={len(papers)}")
            start += page
            time.sleep(3)
            if len(entries) < page:
                break
    return papers


def relevance(p: dict) -> tuple[int, list[str]]:
    hay = (p["title"] + " " + p["abstract"]).lower()
    score, hits = 0, []
    for w, words in KW.items():
        for kw in words:
            if kw in hay:
                score += w
                hits.append(kw)
    return score, hits


def download_pool_assets(pool: list[dict]) -> None:
    (FIX / "pdf").mkdir(parents=True, exist_ok=True)
    (FIX / "source").mkdir(parents=True, exist_ok=True)
    (FIX / "gold").mkdir(parents=True, exist_ok=True)
    for p in pool:
        pid = p["id"]
        pdf_p = FIX / "pdf" / f"{pid}.pdf"
        tex_p = FIX / "source" / f"{pid}.tex"
        gold_p = FIX / "gold" / f"{pid}.json"
        # PDF
        if not pdf_p.exists():
            try:
                pdf_p.write_bytes(get(f"https://arxiv.org/pdf/{pid}.pdf"))
                print(f"  pdf  {pid} ({pdf_p.stat().st_size//1024} KB)")
            except Exception as ex:
                print(f"  pdf  {pid} FAIL {ex}")
            time.sleep(3)
        # e-print source
        tex = ""
        if not tex_p.exists():
            try:
                raw = get(f"https://arxiv.org/e-print/{pid}")
                tex = extract_tex(raw)
                tex_p.write_text(tex, encoding="utf-8", errors="replace")
                print(f"  tex  {pid} ({len(tex)} chars)")
            except Exception as ex:
                print(f"  tex  {pid} FAIL {ex}")
            time.sleep(3)
        else:
            tex = tex_p.read_text(encoding="utf-8", errors="replace")
        # gold fields
        gold_p.write_text(json.dumps(gold_fields(p, tex), indent=2), encoding="utf-8")


def extract_tex(raw: bytes) -> str:
    """e-print is usually a gzipped tar of .tex/.sty/figures, sometimes a bare
    gzipped .tex. Concatenate all .tex files."""
    try:
        tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:*")
    except tarfile.TarError:
        # bare gzip of a single tex
        import gzip
        try:
            return gzip.decompress(raw).decode("utf-8", "replace")
        except Exception:
            return raw.decode("utf-8", "replace")
    parts = []
    for m in tf.getmembers():
        if m.isfile() and m.name.lower().endswith(".tex"):
            f = tf.extractfile(m)
            if f:
                parts.append(f.read().decode("utf-8", "replace"))
    return "\n".join(parts)


def gold_fields(p: dict, tex: str) -> dict:
    sections = re.findall(r"\\section\*?\{([^}]*)\}", tex)
    eq = len(re.findall(r"\\begin\{(equation|align|gather|multline)\*?\}", tex))
    eq += tex.count(r"\[")  # display math
    tbl = len(re.findall(r"\\begin\{(table|tabular)\*?\}", tex))
    return {
        "id": p["id"],
        "title": p["title"],
        "authors": p["authors"],
        "published": p["published"],
        "primary_category": p["primary_category"],
        "categories": p["categories"],
        "abstract": p["abstract"],
        "gold_from_latex": {
            "section_headings": [" ".join(s.split()) for s in sections],
            "n_sections": len(sections),
            "n_equations": eq,
            "n_tables": tbl,
            "has_source": bool(tex.strip()),
        },
    }


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    print(f"[1/3] listing {DATE} across {CATS} ...")
    papers = fetch_listing()
    ranked = sorted(papers.values(),
                    key=lambda p: relevance(p)[0], reverse=True)
    for p in papers.values():
        p["relevance_score"], p["relevance_hits"] = relevance(p)
    (FIX / "listing.json").write_text(json.dumps({
        "date": DATE, "categories": CATS, "n_papers": len(papers),
        "papers": list(papers.values()),
    }, indent=2), encoding="utf-8")
    print(f"      wrote listing.json ({len(papers)} papers)")

    n_pool = int(sys.argv[1]) if len(sys.argv) > 1 else 18
    pool = [p for p in ranked if relevance(p)[0] > 0][:n_pool]
    (FIX / "pool.json").write_text(json.dumps({
        "note": "heuristic local-AI relevance pool; drives pick-5, NOT gold",
        "n": len(pool),
        "pool": [{"id": p["id"], "title": p["title"],
                  "relevance_score": relevance(p)[0],
                  "hits": relevance(p)[1]} for p in pool],
    }, indent=2), encoding="utf-8")
    print(f"[2/3] pool = {len(pool)} papers")
    print(f"[3/3] downloading PDFs + e-print sources ...")
    download_pool_assets(pool)
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
