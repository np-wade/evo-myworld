"""video-eval CLI.

  python3 -m video_eval list          # sources + strategies + candidates available
  python3 -m video_eval selftest      # OFFLINE: oracle loads + WER/CER/drift math
  python3 -m video_eval stealth-race  # LIVE: fetch-strategy stealth sub-leaderboard
  python3 -m video_eval asr-race      # OFFLINE: ASR candidates on frozen audio
  python3 -m video_eval transcript-race  # LIVE: scrape transcript, NO media download
  python3 -m video_eval pipeline --url <media URL>   # END-TO-END seed task
  python3 -m video_eval fetch-fixtures               # GRADER-ONLY gold freeze
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import media, sources
from .asr import build_asr_candidates
from .fetchers import ALL_BACKENDS, available_backends
from .oracle import Transcript, cer, timestamp_drift, wer
from .transcript import Cue, parse_vtt


def cmd_list(_):
    avail_be = {b.name for b in available_backends()}
    print("HTTP backends (arbitrary-site scrape / stealth axis):")
    for b in ALL_BACKENDS:
        print(f"  [{'x' if b.name in avail_be else ' '}] {b.name}")
    print("\nmedia/stealth strategies:")
    for s in media.ALL_STRATEGIES:
        print(f"  [{'x' if s.available() else ' '}] {s.name}")
    print("\nASR / transcription candidates:")
    for c in build_asr_candidates():
        print(f"  [{'x' if c.available() else ' '}] {c.key:24} kind={c.kind}")
    from .transcript_race import build_scrapers
    print("\nlive transcript scrapers (no media download):")
    for s in build_scrapers():
        print(f"  [{'x' if s.available() else ' '}] {s.name}")
    print("\nsources (seed pool):")
    for src in ("youtube", "twitch", "arbitrary"):
        entries = sources.by_source(src)
        frozen = sum(1 for e in entries
                     if (sources.FIXTURES / e.source / e.vid / "meta.json").exists())
        print(f"  {src:10} {len(entries)} seed, {frozen} frozen")
    print("\n[x]=runnable now  [ ]=skipped (missing dep/infra)")


def cmd_selftest(_):
    # --- WER math ---
    assert wer("hello world foo", "hello world foo") == 0.0, "identical WER != 0"
    # one substitution out of three words -> 1/3
    w = wer("the cat sat on the mat", "the cat sat on the hat")
    assert abs(w - 1 / 6) < 1e-9, f"1-sub WER wrong: {w}"
    # one deletion (5 ref words, hyp drops one) -> 1/5
    w2 = wer("a b c d e", "a b c e")
    assert abs(w2 - 1 / 5) < 1e-9, f"1-del WER wrong: {w2}"
    # empty hypothesis -> WER 1.0
    assert wer("some words here", "") == 1.0, "empty-hyp WER != 1.0"
    # empty ref, empty hyp -> 0.0
    assert wer("", "") == 0.0, "empty/empty WER != 0"

    # --- CER math ---
    assert cer("abc", "abc") == 0.0
    c1 = cer("abcd", "abxd")   # 1 sub / 4 chars
    assert abs(c1 - 0.25) < 1e-9, f"CER wrong: {c1}"
    assert cer("abc", "") == 1.0

    # --- timestamp drift math ---
    ref = Transcript([Cue(0.0, 1.0, "alpha"), Cue(10.0, 11.0, "bravo"),
                      Cue(20.0, 21.0, "charlie")])
    hyp = Transcript([Cue(0.5, 1.5, "alpha"), Cue(11.0, 12.0, "bravo"),
                      Cue(19.0, 20.0, "charlie")])
    d, n = timestamp_drift(ref, hyp)   # deltas: 0.5, 1.0, 1.0 -> median 1.0
    assert n == 3 and abs(d - 1.0) < 1e-9, f"drift wrong: {d}, n={n}"

    # --- VTT parse + dedupe ---
    vtt = ("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello there\n\n"
           "00:00:02.000 --> 00:00:04.000\nHello there world\n\n"
           "00:00:04.000 --> 00:00:06.000\ngeneral kenobi\n")
    t = parse_vtt(vtt)
    assert t.cues, "vtt parse produced no cues"
    assert "general kenobi" in t.full_text.lower()

    # --- Oracle loads a frozen gold fixture (offline) ---
    frozen = sources.frozen_entries()
    gold_loaded = 0
    for e in frozen:
        from .oracle import Oracle
        oc = Oracle(e.source, e.vid)
        if oc.has_gold and oc.gold is not None:
            # perfect self-score: gold vs itself -> WER 0
            sc = oc.score(oc.gold)
            assert sc.wer == 0.0, f"gold self-WER != 0 for {e.vid}: {sc.wer}"
            gold_loaded += 1

    print("selftest OK — WER (identical=0, 1-sub=1/6, 1-del=1/5, empty=1.0), "
          "CER, timestamp-drift, VTT parse verified; "
          f"{len(frozen)} frozen fixtures ({gold_loaded} with gold, self-WER=0).")


def cmd_stealth_race(a):
    from .stealth_race import format_stealth, stealth_race
    srcs = a.sources.split(",") if a.sources else None
    res = stealth_race(source_list=srcs, retries=a.retries, limit=a.limit)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(format_stealth(res))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=2))
        print(f"\nsaved -> {a.out}")


def cmd_asr_race(a):
    from .asr_race import asr_race, format_asr
    res = asr_race(sample=a.sample)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(format_asr(res))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=2))
        print(f"\nsaved -> {a.out}")


def cmd_transcript_race(a):
    from .transcript_race import format_transcript_race, transcript_race
    res = transcript_race(limit=a.limit, sleep_s=a.sleep)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(format_transcript_race(res))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=2))
        print(f"\nsaved -> {a.out}")


def cmd_pipeline(a):
    from .pipeline import run_pipeline, score_pipeline
    res = run_pipeline(url=a.url, source=a.source, vid=a.vid,
                       strategy=a.strategy, allow_asr=not a.no_asr,
                       allow_download=not a.no_download)
    score = score_pipeline(res)
    print(json.dumps(score, indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps(
            {"score": score, "report": res["report"]}, indent=2))
        print(f"\nsaved -> {a.out}")


def cmd_fetch_fixtures(a):
    from .fetch_fixtures import fetch_fixtures
    fetch_fixtures(sources_arg=a.sources, limit=a.limit,
                   max_secs=a.max_secs)


def main(argv=None):
    p = argparse.ArgumentParser(prog="video_eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)

    sr = sub.add_parser("stealth-race")
    sr.add_argument("--sources", default="", help="comma list; default all")
    sr.add_argument("--retries", type=int, default=2)
    sr.add_argument("--limit", type=int, default=3)
    sr.add_argument("--json", action="store_true")
    sr.add_argument("--out", default="")
    sr.set_defaults(fn=cmd_stealth_race)

    ar = sub.add_parser("asr-race")
    ar.add_argument("--sample", type=int, default=0)
    ar.add_argument("--json", action="store_true")
    ar.add_argument("--out", default="")
    ar.set_defaults(fn=cmd_asr_race)

    tr = sub.add_parser("transcript-race")
    tr.add_argument("--limit", type=int, default=3)
    tr.add_argument("--sleep", type=float, default=1.0)
    tr.add_argument("--json", action="store_true")
    tr.add_argument("--out", default="")
    tr.set_defaults(fn=cmd_transcript_race)

    pl = sub.add_parser("pipeline")
    pl.add_argument("--url", default="")
    pl.add_argument("--source", default="")
    pl.add_argument("--vid", default="")
    pl.add_argument("--strategy", default="ytdlp-impersonate")
    pl.add_argument("--no-asr", action="store_true")
    pl.add_argument("--no-download", action="store_true")
    pl.add_argument("--out", default="")
    pl.set_defaults(fn=cmd_pipeline)

    ff = sub.add_parser("fetch-fixtures")
    ff.add_argument("--sources", default="")
    ff.add_argument("--limit", type=int, default=6)
    ff.add_argument("--max-secs", type=int, default=420)
    ff.set_defaults(fn=cmd_fetch_fixtures)

    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
