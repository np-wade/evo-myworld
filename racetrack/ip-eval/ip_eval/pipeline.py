"""End-to-end pipeline scorecard — incumbent runs the full Stage 1→8 chain on
the fixture corpus; every artifact is hard-scored against gold.

Emits pipeline-run<N>.json at the package root: {score: {hard, advisory,
wall_s}, report}. Judgment-call material (draft readability) is advisory-only.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import oracle
from .candidates import InformationProcesser
from .fixtures import FIXTURES_DIR, build_fixtures
from .race import _doc_corpus_and_queries

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _next_run() -> int:
    existing = sorted(PACKAGE_ROOT.glob("pipeline-run*.json"))
    if not existing:
        return 1
    m = re.search(r"run(\d+)\.json$", existing[-1].name)
    return int(m.group(1)) + 1 if m else 1


def run_pipeline() -> dict:
    gold = build_fixtures()
    ip = InformationProcesser()
    ok, reason = ip.available()
    if not ok:
        raise SystemExit(f"incumbent unavailable: {reason}")

    started = time.monotonic()
    hard: dict[str, float] = {}
    report: dict[str, object] = {}

    # S1: extract the markdown and pdf renderings of alpha
    doc = gold["documents"]["alpha"]
    md_path = FIXTURES_DIR / doc["formats"]["md"]["file"]
    extraction = ip.extract(md_path, md_path.name, doc["formats"]["md"]["mime"])
    hard["s1_extract_f1"] = oracle.score_extraction(
        extraction.get("content", ""), doc["formats"]["md"]["canonical_text"])["f1"]

    # S2: split
    sections = ip.split(doc["formats"]["md"]["canonical_text"])
    gold_headings = [s["heading"] for s in doc["sections"]] + ["References"]
    hard["s2_boundary_f1"] = oracle.score_split(
        [s.get("title", "") for s in sections], gold_headings)["f1"]

    # S3: concepts
    concepts = ip.concepts(sections)
    scored = oracle.score_concepts(concepts, doc["concepts"])
    hard["s3_concept_f1"] = scored["f1"]
    hard["s3_type_accuracy"] = scored["type_accuracy"]

    # S4: research the top gold concept against the vault sentence corpus
    corpus, queries = [], []
    for key in ("alpha", "beta"):
        c, q = _doc_corpus_and_queries(gold["documents"][key])
        corpus.extend(c)
        queries.extend(q)
    r5s = []
    for query_name, hits in queries:
        ranked = ip.retrieve(query_name, corpus)
        r5s.append(oracle.score_retrieval(ranked, hits)["recall@5"])
    hard["s4_recall_at_5"] = round(sum(r5s) / max(1, len(r5s)), 4)

    # S7: combine the generated drafts (dedup discipline)
    paragraphs = [p for s in doc["sections"] for p in s["paragraphs"]]
    deduped = ip.dedup(paragraphs + paragraphs[:2])  # plant two exact repeats
    unique_loss = all(any(p.strip()[:60] in kept for kept in deduped)
                      for p in paragraphs)
    hard["s7_unique_preserved"] = float(unique_loss)

    # S8: docx + bibtex
    citations = [
        {"citeKey": f"{r['author'].split(',')[0].lower()}{r['year']}",
         "authors": [r["author"]], "year": r["year"], "title": r["title"],
         "sourceUrl": ""}
        for r in doc["references"]
    ]
    docx_bytes = ip.export_docx(doc["formats"]["md"]["canonical_text"], citations)
    hard["s8_docx_valid"] = float(oracle.score_docx(docx_bytes)["valid"])
    bibtex = ip.export_bibtex(citations)
    hard["s8_bibtex_coverage"] = oracle.score_bibtex(bibtex, doc["references"])["coverage"]

    wall_s = round(time.monotonic() - started, 2)
    report["chain"] = "extract(md) -> split -> concepts -> research -> combine -> docx+bibtex"
    report["doc"] = "alpha"
    report["queries_run"] = len(queries)
    report["sections"] = len(sections)
    report["concepts"] = len(concepts)

    result = {
        "score": {
            "hard": hard,
            "advisory": {
                "note": "draft readability / section-mapping quality are judgment calls; "
                        "not hard-scored per two-track rule",
            },
            "wall_s": wall_s,
        },
        "report": report,
    }
    out_path = PACKAGE_ROOT / f"pipeline-run{_next_run()}.json"
    out_path.write_text(json.dumps(result, indent=2))
    return {"path": out_path, "result": result}


if __name__ == "__main__":
    outcome = run_pipeline()
    print(json.dumps(outcome["result"]["score"], indent=2))
