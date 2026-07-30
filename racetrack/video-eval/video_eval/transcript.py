"""Shared transcript parsing + normalization — pure stdlib, used by BOTH the app
path (its own scraped/ASR transcript) and the grader (gold captions).

A transcript is a list of Cue(start, end, text) in seconds. We parse WebVTT and
SRT (the two caption formats yt-dlp emits), and normalize text for WER/CER:
lowercase, strip punctuation, collapse whitespace, drop caption artifacts
([Music], >>, speaker tags).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_INLINE_TS = re.compile(r"<\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}>")  # word-level timing
_TAG = re.compile(r"<[^>]+>")                     # <c>, <00:00:01.000> inline tags
_BRACKET = re.compile(r"\[[^\]]*\]|\([^)]*\)")    # [Music], (applause)
_SPEAKER = re.compile(r"^\s*(>>+|-\s|[A-Z][A-Z .']{1,20}:)\s*")
_PUNCT = re.compile(r"[^a-z0-9' ]+")
_WS = re.compile(r"\s+")
_NUMWORD = {  # light number normalization so "2024" vs "twenty twenty four" don't tank WER
}


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    cues: list[Cue] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return " ".join(c.text for c in self.cues if c.text.strip())

    def norm_tokens(self) -> list[str]:
        return normalize(self.full_text).split()


def _parse_ts(s: str) -> float | None:
    m = _TS.search(s)
    if not m:
        return None
    hh = int(m.group(1) or 0)
    mm = int(m.group(2))
    ss = int(m.group(3))
    frac = m.group(4)
    ms = int(frac) / (10 ** len(frac))
    return hh * 3600 + mm * 60 + ss + ms


def clean_caption_text(s: str) -> str:
    """Strip inline tags / brackets / speaker labels but KEEP the words + case."""
    s = _TAG.sub("", s)
    s = _BRACKET.sub(" ", s)
    s = _SPEAKER.sub("", s)
    return _WS.sub(" ", s).strip()


def parse_vtt(data: str) -> Transcript:
    """Parse WebVTT. Also tolerates SRT (--> lines with , millis)."""
    cues: list[Cue] = []
    blocks = re.split(r"\n\s*\n", data.replace("\r\n", "\n").replace("\r", "\n"))
    for blk in blocks:
        lines = [l for l in blk.split("\n") if l.strip()]
        if not lines:
            continue
        # find the timing line (contains -->)
        ti = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if ti is None:
            continue
        left, _, right = lines[ti].partition("-->")
        start = _parse_ts(left)
        end = _parse_ts(right)
        if start is None:
            continue
        content = lines[ti + 1:]
        # rolling-style YouTube streams: an untagged line in a block that ALSO
        # has word-timed lines is the rolled-over previous caption — drop it
        tagged = [l for l in content if _INLINE_TS.search(l)]
        if tagged:
            content = tagged
        text = clean_caption_text(" ".join(content))
        if text:
            cues.append(Cue(start, end if end is not None else start, text))
    return _dedupe(Transcript(cues))


def _dedupe(t: Transcript) -> Transcript:
    """YouTube auto-caption VTT repeats text as a rolling window — a cue often
    carries the previous line PLUS the new words, and the next cue repeats the
    new line verbatim. Drop the repeated prefix at token level so full_text
    counts every word once (raw timedtext streams need this; yt-dlp-written
    files are already clean and pass through unchanged)."""
    out: list[Cue] = []
    prev_toks: list[str] = []
    for c in t.cues:
        raw_toks = c.text.split()
        toks_n = [w for w in (normalize(w) for w in raw_toks) if w]
        if not toks_n:
            continue
        # longest suffix of prev matching a prefix of this cue = rolled-over text
        k = 0
        for j in range(min(len(prev_toks), len(toks_n)), 0, -1):
            if prev_toks[-j:] == toks_n[:j]:
                k = j
                break
        if k == len(toks_n):          # cue is a pure repeat of the tail
            prev_toks = toks_n
            continue
        if k:                          # strip the rolled-over raw tokens
            cnt = idx = 0
            for idx, w in enumerate(raw_toks):
                if normalize(w):
                    cnt += 1
                if cnt == k:
                    idx += 1
                    break
            raw_toks = raw_toks[idx:]
        text = " ".join(raw_toks).strip()
        if text:
            out.append(Cue(c.start, c.end, text))
        prev_toks = toks_n
    return Transcript(out)


def normalize(s: str) -> str:
    """Aggressive normalization for WER/CER token comparison."""
    s = s.lower()
    s = _BRACKET.sub(" ", s)
    s = s.replace("’", "'").replace("‘", "'")
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()
