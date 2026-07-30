"""Oracle — the grader's answer key. The gold transcript (creator captions on
YouTube; on-page transcript for the arbitrary site) is a PRIVILEGED channel
frozen by fetch_fixtures.py. The app never loads it.

Scoring is pure stdlib, deterministic, offline-rerunnable:
  WER  -- word error rate = Levenshtein(hyp_words, ref_words) / len(ref_words)
  CER  -- char error rate = Levenshtein(hyp_chars, ref_chars) / len(ref_chars)
  drift-- median |Δstart| over time-aligned segments (segment = matched word run)

Twitch (usually no clean captions) is flagged has_gold=False: its ASR output is
scored for internal consistency + latency/cost, NOT WER.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .transcript import Transcript, normalize, parse_vtt

FIXTURES = Path(__file__).parent.parent / "fixtures"


def levenshtein(a: list, b: list) -> int:
    """Edit distance (S+D+I) between two token sequences. O(len(a)*len(b)) DP
    with a rolling row so long transcripts stay cheap on memory."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,        # deletion
                cur[j - 1] + 1,     # insertion
                prev[j - 1] + (ca != cb),  # substitution
            ))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> float:
    r = normalize(ref).split()
    h = normalize(hyp).split()
    if not r:
        return 0.0 if not h else 1.0
    return levenshtein(r, h) / len(r)


def cer(ref: str, hyp: str) -> float:
    r = list(normalize(ref).replace(" ", ""))
    h = list(normalize(hyp).replace(" ", ""))
    if not r:
        return 0.0 if not h else 1.0
    return levenshtein(r, h) / len(r)


def timestamp_drift(ref: Transcript, hyp: Transcript) -> tuple[float, int]:
    """Median absolute start-time delta over aligned anchor words.

    Anchor = a normalized word that appears exactly once in BOTH transcripts;
    we map it to the start time of the cue that contains it and measure |Δ|.
    Returns (median_drift_seconds, n_anchors). Robust to insert/delete noise.
    """
    def word_times(t: Transcript) -> dict[str, list[float]]:
        d: dict[str, list[float]] = {}
        for c in t.cues:
            for w in normalize(c.text).split():
                d.setdefault(w, []).append(c.start)
        return d

    rt, ht = word_times(ref), word_times(hyp)
    deltas = []
    for w, rs in rt.items():
        hs = ht.get(w)
        if len(rs) == 1 and hs and len(hs) == 1:
            deltas.append(abs(rs[0] - hs[0]))
    if not deltas:
        return (-1.0, 0)
    deltas.sort()
    n = len(deltas)
    med = deltas[n // 2] if n % 2 else (deltas[n // 2 - 1] + deltas[n // 2]) / 2
    return (round(med, 3), n)


@dataclass
class TranscriptScore:
    has_gold: bool
    wer: float
    cer: float
    drift_s: float
    drift_anchors: int
    ref_words: int
    hyp_words: int
    note: str = ""


class Oracle:
    """Loads the frozen gold for one (source, id) and scores a hypothesis
    transcript. For sources without gold, scores consistency-only."""

    def __init__(self, source: str, vid: str):
        self.source = source
        self.vid = vid
        self.dir = FIXTURES / source / vid
        self.meta = json.loads((self.dir / "meta.json").read_text())
        self.has_gold = self.meta.get("has_gold", False)
        self.gold: Transcript | None = None
        gv = self.dir / "gold.vtt"
        if self.has_gold and gv.exists():
            self.gold = parse_vtt(gv.read_text())

    def score(self, hyp: Transcript) -> TranscriptScore:
        hyp_words = len(hyp.norm_tokens())
        if not self.has_gold or self.gold is None:
            # consistency-only: is the ASR output non-trivial + not degenerate?
            uniq = len(set(hyp.norm_tokens()))
            note = ("no-gold source (Twitch/ASR-only): scored for consistency "
                    "+ latency/cost, NOT WER")
            return TranscriptScore(
                has_gold=False, wer=-1.0, cer=-1.0, drift_s=-1.0,
                drift_anchors=0, ref_words=0, hyp_words=hyp_words,
                note=f"{note}; unique_words={uniq}")
        # Gold fixtures are trimmed to a window; a live app transcript may cover
        # the WHOLE video. Score over the gold's covered time span: clip the
        # hypothesis to [0, gold_end + margin] so extra out-of-window speech
        # isn't counted as insertions. (No-op when gold spans the full media.)
        gold_end = max((c.end for c in self.gold.cues), default=0.0)
        margin = 5.0
        hyp_clip = Transcript([c for c in hyp.cues if c.start <= gold_end + margin])
        if not hyp_clip.cues:                 # hyp had no timestamps in-window
            hyp_clip = hyp
        ref_text = self.gold.full_text
        hyp_text = hyp_clip.full_text
        d, anch = timestamp_drift(self.gold, hyp_clip)
        return TranscriptScore(
            has_gold=True,
            wer=round(wer(ref_text, hyp_text), 4),
            cer=round(cer(ref_text, hyp_text), 4),
            drift_s=d, drift_anchors=anch,
            ref_words=len(self.gold.norm_tokens()),
            hyp_words=len(hyp_clip.norm_tokens()),
        )


def load_meta(source: str, vid: str) -> dict:
    return json.loads((FIXTURES / source / vid / "meta.json").read_text())


def to_dict(s: TranscriptScore) -> dict:
    return asdict(s)
