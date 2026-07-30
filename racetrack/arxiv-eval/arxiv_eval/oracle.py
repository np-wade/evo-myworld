"""Oracle — the grader's answer key, built from the arXiv API (privileged truth).

The app never calls this. It loads the frozen gold listing for a date and scores
a candidate's discovered ID set with precision / recall / F1. Pure stdlib.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"


@dataclass
class DiscoveryScore:
    found: int
    gold: int
    true_pos: int
    precision: float
    recall: float
    f1: float
    extra: int  # returned IDs not in the day's gold set


class Oracle:
    def __init__(self, date: str = "2026-07-14"):
        self.date = date
        d = json.loads((FIXTURES / date / "listing.json").read_text())
        self.gold_ids: set[str] = {p["id"] for p in d["papers"]}
        self.papers: dict[str, dict] = {p["id"]: p for p in d["papers"]}

    def score_discovery(self, found_ids: set[str]) -> DiscoveryScore:
        found_ids = {i.strip() for i in found_ids if i.strip()}
        tp = len(found_ids & self.gold_ids)
        prec = tp / len(found_ids) if found_ids else 0.0
        rec = tp / len(self.gold_ids) if self.gold_ids else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        return DiscoveryScore(
            found=len(found_ids), gold=len(self.gold_ids), true_pos=tp,
            precision=round(prec, 4), recall=round(rec, 4), f1=round(f1, 4),
            extra=len(found_ids - self.gold_ids),
        )

    def gold_fields(self, arxiv_id: str) -> dict:
        p = FIXTURES / self.date / "gold" / f"{arxiv_id}.json"
        return json.loads(p.read_text()) if p.exists() else {}
