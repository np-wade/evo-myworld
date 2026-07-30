"""Oracle — the grader's answer key, loaded from the injection manifest that
fixtures_gen authored (privileged truth: the app only ever sees the HTML pairs).

Scores a candidate's reported change set:
  precision / recall / F1 over the injected REAL changes (change-level: a
      page-level "something changed" wildcard earns no recall),
  false-alarm rate over the CHURN TRAPS (THE headline metric — a good watcher
      ignores churn),
  localization (did a matching detection point at the right element id),
Pure stdlib. Detections are plain dicts:
  {page, change_type, element_id, before, after, label}
where label is the candidate's real-vs-churn verdict; churn-labeled detections
are suppressed (never scored as reports, never false alarms).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"

_WS = re.compile(r"\s+")


def _n(s: str) -> str:
    return _WS.sub(" ", s or "").strip().lower()


@dataclass
class WatchScore:
    real_total: int
    real_hit: int
    precision: float
    recall: float
    f1: float
    churn_total: int
    churn_flagged: int
    false_alarm_rate: float
    localization: float
    n_reported: int          # real-labeled detections
    n_suppressed: int        # churn-labeled detections (classifier verdicts)
    missed: list = field(default_factory=list)
    flagged: list = field(default_factory=list)


class Oracle:
    def __init__(self, set_key: str = "set1"):
        self.set_key = set_key
        m = json.loads((FIXTURES / set_key / "manifest.json").read_text())
        self.pages: list[dict] = m["pages"]
        self.changes: list[dict] = m["changes"]
        self.real = [c for c in self.changes if c["kind"] == "real"]
        self.churn = [c for c in self.changes if c["kind"] == "churn"]
        self.real_pages = {c["page"] for c in self.real}

    @staticmethod
    def _match(det: dict, ch: dict) -> bool:
        """Change-level match: right element id, or the injected snippet is in
        the detection's before/after text. Never called for wildcards."""
        if det.get("page") != ch["page"]:
            return False
        if ch["element_id"] and det.get("element_id") == ch["element_id"]:
            return True
        b, a = _n(det.get("before", "")), _n(det.get("after", ""))
        v1, v2 = _n(ch.get("v1_text", "")), _n(ch.get("v2_text", ""))
        if v2 and v2 in a:
            return True
        if v1 and v1 in b:
            return True
        # alt snippets (e.g. a deleted section's heading) count on either side
        for alt in ch.get("alt_texts", []):
            na = _n(alt)
            if na and (na in b or na in a):
                return True
        return False

    def score_detections(self, dets: list[dict]) -> WatchScore:
        reported = [d for d in dets if d.get("label", "real") == "real"]
        suppressed = len(dets) - len(reported)
        wild = [d for d in reported if d.get("change_type") == "page-changed"]
        point = [d for d in reported if d.get("change_type") != "page-changed"]

        hit, loc, missed = 0, 0, []
        for ch in self.real:
            ms = [d for d in point if self._match(d, ch)]
            if ms:
                hit += 1
                if any(d.get("element_id") == ch["element_id"] for d in ms):
                    loc += 1
            else:
                missed.append(ch["change_id"])

        tp = sum(1 for d in point
                 if any(self._match(d, ch) for ch in self.real))
        # a page-level wildcard on a page with real changes is a fair alarm
        # (excluded from precision); on a churn-only page it is a false positive.
        fp = (len(point) - tp) + sum(1 for d in wild
                                     if d["page"] not in self.real_pages)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = hit / len(self.real) if self.real else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0

        flagged = []
        for t in self.churn:
            f = any(self._match(d, t) for d in point) or any(
                d["page"] == t["page"] and t["page"] not in self.real_pages
                for d in wild)
            if f:
                flagged.append(t["change_id"])
        far = len(flagged) / len(self.churn) if self.churn else 0.0

        return WatchScore(
            real_total=len(self.real), real_hit=hit,
            precision=round(prec, 4), recall=round(rec, 4), f1=round(f1, 4),
            churn_total=len(self.churn), churn_flagged=len(flagged),
            false_alarm_rate=round(far, 4),
            localization=round(loc / hit, 4) if hit else 0.0,
            n_reported=len(reported), n_suppressed=suppressed,
            missed=missed, flagged=flagged,
        )
