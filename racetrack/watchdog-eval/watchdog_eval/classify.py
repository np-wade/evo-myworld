"""Classify stage — real change vs cosmetic churn. Shared by every differ (the
race isolates the diff stage; classification is common infrastructure, like the
oracle is on the grader side).

GENERIC heuristics only — nothing here reads the fixture manifest:
  * ad copy        -- "sponsored"/"advertisement" text, ad-* class context
  * reorders       -- moved content whose token multiset is unchanged
  * volatile edits -- a modified block whose changed tokens are ALL volatile:
                      dates, clock times, hex tokens (build/session ids), bare
                      counters (view counts, "N seconds ago", thousands-comma
                      numbers). A price ("$35/mo") or a worded edit never
                      qualifies, so real edits survive.
Trade-off (by design): a page whose ONLY meaningful edit is a bare number with
no unit would be suppressed — that is the signal-vs-noise line this stage
draws. Pure stdlib.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter

from .differs import Detection

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}/\d{1,2}/\d{2,4}$")
_TIME = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
_HEX = re.compile(r"^[0-9a-f]{6,}$")
_INT = re.compile(r"^\d{1,3}(,\d{3})+$|^\d+$")
_EDGE = re.compile(r"^[\W_]+|[\W_]+$")
_AD_CLASS = re.compile(r"(^|[\s_-])ads?([\s_-]|$)|ad-slot|advert", re.I)
_AD_TEXT = re.compile(r"\bsponsored\b|\badvertisement\b", re.I)


def _churn_token(tok: str) -> bool:
    t = _EDGE.sub("", tok.lower())
    if not t:
        return True  # punctuation-only
    if _DATE.match(t) or _TIME.match(t) or _INT.match(t):
        return True
    if _HEX.match(t) and any(c.isdigit() for c in t):
        return True
    return False


def _churn_only_edit(before: str, after: str) -> bool:
    """True when everything that actually changed between the two texts is
    volatile (or is a pure reorder of identical tokens)."""
    bt, at = before.split(), after.split()
    sm = difflib.SequenceMatcher(None, bt, at, autojunk=False)
    rem: list[str] = []
    add: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            rem += bt[i1:i2]
            add += at[j1:j2]
    if not rem and not add:
        return True
    if Counter(rem) == Counter(add):
        return True  # reordered-but-identical
    return all(_churn_token(t) for t in rem + add)


def label(det: Detection) -> str:
    txt = f"{det.before} {det.after}"
    if det.context and _AD_CLASS.search(det.context):
        return "churn"
    if _AD_TEXT.search(txt):
        return "churn"
    if det.change_type == "moved" and \
            Counter(det.before.split()) == Counter(det.after.split()):
        return "churn"
    if det.change_type == "modified" and \
            _churn_only_edit(det.before, det.after):
        return "churn"
    if det.change_type in ("added", "removed"):
        toks = txt.split()
        if toks and all(_churn_token(t) for t in toks):
            return "churn"
    return "real"  # page-changed and everything else: report it


def classify(dets: list[Detection]) -> list[Detection]:
    for d in dets:
        d.label = label(d)
    return dets
