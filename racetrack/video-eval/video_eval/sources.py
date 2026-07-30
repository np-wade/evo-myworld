"""Source adapters — the THREE media source types Nicholas asked for, each
available()-gated. A source knows how to (a) name a media URL from an id,
(b) declare whether a trustworthy gold transcript is expected to exist (so the
oracle scores WER vs consistency-only), and (c) locate an on-page transcript
for the arbitrary case.

  YOUTUBE   -- talks/lectures WITH creator-uploaded (manual) captions = gold.
               App must produce its OWN transcript (scrape auto-captions or ASR).
  TWITCH    -- VODs, pulled via yt-dlp. Rarely has clean captions -> ASR path,
               leans on stealth (Twitch is aggressive about bot detection).
               has_gold=False -> consistency/latency scored, not WER.
  ARBITRARY -- a generic page embedding a video/audio + an on-page transcript
               (podcast/conference page). Tests "find the media + find/produce
               the transcript". On-page transcript = gold (grader-side).

The SEED registry lists the frozen fixture pool. fetch_fixtures.py resolves each
entry grader-side once; meta.json records the outcome (has_gold, media file,
duration). Live entries beyond the pool can be driven ad-hoc via `pipeline
--url`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"


@dataclass
class SourceEntry:
    source: str
    vid: str
    url: str
    expect_gold: bool
    title: str = ""
    note: str = ""


# --- SEED POOL ---------------------------------------------------------------
# YouTube: talks that historically carry creator-uploaded (manual, en) captions.
# Twitch: public VOD ids (leans on ASR + stealth). Arbitrary: pages with an
# on-page transcript. fetch_fixtures.py verifies + freezes; entries that turn
# out not to match their expectation are recorded truthfully in meta.json.
SEED: list[SourceEntry] = [
    # ---- YouTube (expect creator captions = gold) ----
    SourceEntry("youtube", "UF8uR6Z6KLc", "https://www.youtube.com/watch?v=UF8uR6Z6KLc",
                True, "Steve Jobs Stanford Commencement 2005",
                "widely-captioned short talk"),
    SourceEntry("youtube", "8jPQjjsBbIc", "https://www.youtube.com/watch?v=8jPQjjsBbIc",
                True, "3Blue1Brown-style lecture (manual captions)"),
    SourceEntry("youtube", "aircAruvnKk", "https://www.youtube.com/watch?v=aircAruvnKk",
                True, "3Blue1Brown — But what is a neural network"),
    SourceEntry("youtube", "kCc8FmEb1nY", "https://www.youtube.com/watch?v=kCc8FmEb1nY",
                True, "Karpathy — Let's build GPT"),
    SourceEntry("youtube", "zjkBMFhNj_g", "https://www.youtube.com/watch?v=zjkBMFhNj_g",
                True, "Intro to Large Language Models (Karpathy)"),
    SourceEntry("youtube", "rEDzUT3ymw4", "https://www.youtube.com/watch?v=rEDzUT3ymw4",
                True, "conference talk w/ manual captions"),
    # ---- Twitch (VOD; ASR + stealth; usually no gold) ----
    # NOTE: Twitch VOD ids rotate/expire; refresh via `pipeline --url` or by
    # re-grabbing a channel's latest VOD. This one was live 2026-07-26.
    SourceEntry("twitch", "twitch-demo",
                "https://www.twitch.tv/videos/2829622205",
                False, "Twitch VOD (GamesDoneQuick) — live 2026-07-26",
                "has_gold=False: ASR-only, consistency+latency scored"),
    # ---- Arbitrary site (media + on-page transcript = gold) ----
    SourceEntry("arbitrary", "self-hosted-demo",
                "file://SELF_HOSTED", True,
                "self-authored page: <audio> + on-page <transcript> (gold)",
                "frozen locally; app scrapes the page, grader owns the truth"),
]


def by_source(source: str) -> list[SourceEntry]:
    return [e for e in SEED if e.source == source]


def get(source: str, vid: str) -> SourceEntry | None:
    for e in SEED:
        if e.source == source and e.vid == vid:
            return e
    return None


# --- URL parsing for ad-hoc `pipeline --url` ---------------------------------
_YT = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)"
                 r"([A-Za-z0-9_-]{11})")
_TW = re.compile(r"twitch\.tv/videos/(\d+)")


def classify(url: str) -> SourceEntry:
    """Map an arbitrary URL to a (source, vid) for ad-hoc pipeline runs."""
    m = _YT.search(url)
    if m:
        return SourceEntry("youtube", m.group(1), url, True)
    m = _TW.search(url)
    if m:
        return SourceEntry("twitch", m.group(1), url, False)
    # generic page
    slug = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")[:40] or "page"
    return SourceEntry("arbitrary", slug, url, True)


def frozen_entries() -> list[SourceEntry]:
    """Entries that actually have a frozen fixture on disk (meta.json present)."""
    out = []
    for e in SEED:
        if (FIXTURES / e.source / e.vid / "meta.json").exists():
            out.append(e)
    return out
