"""End-to-end pipeline — the seed task, ONE media URL -> ONE report:
"Get me the transcript of <URL>; produce a clean timestamped transcript + a
table of sections/topics; save transcript.md."

Chained from each stage's winner (normal scraping only; gold channel grader-only):

  1 RESOLVE  stealth winner (default ytdlp-impersonate) resolves the media +
             checks captions. Records the stealth scorecard for THIS pull.
  2 TRANSFORM  transcribe race, best-effort in order:
       (a) caption-scrape   auto-captions via yt-dlp (cheap; app path)
       (b) local ASR        faster-whisper tiny on downloaded audio
       (c) page-transcript  arbitrary site: scrape the on-page transcript
       Falls back to a FROZEN audio fixture if the live download is blocked, so
       the pipeline still emits a scorecard.
  3 SEGMENT  clean timestamped transcript + advisory section/topic table.
  4 REPORT   out/<source>/<id>/ (transcript.md, report.json, manifest w/ sha256)

Then scores: HARD (WER/CER/drift vs gold when has_gold; save mechanics) +
ADVISORY (section table) + STEALTH scorecard for the pull.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from . import media, sources
from .asr import CaptionScrape, FasterWhisper
from .oracle import Oracle, to_dict
from .transcript import Cue, Transcript, normalize, parse_vtt

FIXTURES = Path(__file__).parent.parent / "fixtures"
OUT = Path(__file__).parent.parent / "out"


def _section_table(t: Transcript, n: int = 8) -> list[dict]:
    """ADVISORY: naive uniform time segmentation with a keyword-ish label from
    the most frequent content words in each chunk. Not hard-scored."""
    if not t.cues:
        return []
    total = t.cues[-1].end or t.cues[-1].start
    if total <= 0:
        return []
    stops = set("the a an and or of to in is it that this for on with as be are "
                "was were you i we they he she at by from so we're it's".split())
    step = total / n
    rows = []
    for k in range(n):
        lo, hi = k * step, (k + 1) * step
        words: dict[str, int] = {}
        for c in t.cues:
            if lo <= c.start < hi:
                for w in normalize(c.text).split():
                    if len(w) > 3 and w not in stops:
                        words[w] = words.get(w, 0) + 1
        top = sorted(words, key=lambda w: -words[w])[:4]
        rows.append({"start_s": round(lo, 1), "end_s": round(hi, 1),
                     "topic": ", ".join(top) or "(quiet)"})
    return rows


def _write_transcript_md(path: Path, t: Transcript, sections: list[dict],
                         header: str):
    def hms(s: float) -> str:
        s = int(s); return f"{s//3600:02d}:{s%3600//60:02d}:{s%60:02d}"
    L = [f"# {header}", "", "## Sections / topics", "",
         "| start | end | topic |", "|---|---|---|"]
    L += [f"| {hms(r['start_s'])} | {hms(r['end_s'])} | {r['topic']} |"
          for r in sections]
    L += ["", "## Transcript", ""]
    for c in t.cues:
        if c.text.strip():
            L.append(f"[{hms(c.start)}] {c.text}")
    path.write_text("\n".join(L))


def _resolve_stealth(url: str, source: str, strategy: str) -> dict:
    strat = None
    for s in media.strategies_for(source):
        if s.name == strategy:
            strat = s
            break
    if strat is None:
        avail = media.strategies_for(source)
        strat = avail[0] if avail else None
    if strat is None:
        return {"strategy": "none", "ok": False, "blocked": False,
                "note": "no media strategy available"}
    r = strat.resolve(url)
    return {"strategy": strat.name, "ok": r.ok, "blocked": r.blocked,
            "latency_ms": round(r.latency_ms, 1), "n_formats": r.n_formats,
            "has_manual_caps": r.has_manual_caps, "has_auto_caps": r.has_auto_caps,
            "caption_langs": r.caption_langs, "error": r.error, "note": r.note}


def run_pipeline(url: str = "", source: str = "", vid: str = "",
                 strategy: str = "ytdlp-impersonate",
                 allow_asr: bool = True, allow_download: bool = True) -> dict:
    t_start = time.perf_counter()
    if url:
        e = sources.classify(url)
        source, vid, url = e.source, e.vid, e.url
    elif source and vid:
        se = sources.get(source, vid)
        url = se.url if se else url
    else:
        raise SystemExit("pipeline needs --url OR --source/--vid")

    out = OUT / source / vid
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    # 1 RESOLVE (stealth) — network; degrades gracefully
    stealth = {"strategy": "skipped", "ok": False, "blocked": False}
    if url and not url.startswith("file://SELF_HOSTED"):
        try:
            stealth = _resolve_stealth(url, source, strategy)
        except Exception as e:
            stealth = {"strategy": strategy, "ok": False, "blocked": False,
                       "error": str(e)[:160]}

    # 2 TRANSFORM — caption-scrape -> ASR -> page-transcript; fixture fallback
    transcript = Transcript([])
    method = "none"
    method_detail = ""

    # (a) LIVE caption-scrape — in-memory, NO download of any kind (the
    # transcript-race winners, in leaderboard order)
    if not transcript.cues and url and source in ("youtube",):
        from .transcript_race import build_scrapers
        for s in build_scrapers():
            if not s.available():
                continue
            try:
                so = s.scrape(url)
            except Exception as e:
                method_detail = f"{s.name} err: {e}"[:120]
                continue
            if so.ok and so.transcript is not None and so.transcript.cues:
                transcript = so.transcript
                method, method_detail = "caption-scrape-live", s.name
                break
            elif so.error:
                method_detail = f"{s.name}: {so.error}"[:120]

    # (a2) fallback: yt-dlp writes the caption FILE (still no media download)
    if not transcript.cues and url and source in ("youtube",) and allow_download:
        try:
            vtt = media.download_auto_captions(url, work)
            if vtt:
                transcript = parse_vtt(vtt.read_text())
                method, method_detail = "caption-scrape", vtt.name
        except Exception as e:
            method_detail = f"caption-scrape err: {e}"[:120]

    # (b) local ASR on downloaded (or frozen) audio
    audio_path = None
    if not transcript.cues and allow_asr:
        if url and allow_download and not url.startswith("file://"):
            try:
                audio_path = media.download_audio(url, work)
            except Exception:
                audio_path = None
        # fixture fallback: frozen audio if live pull failed
        if audio_path is None:
            meta_p = FIXTURES / source / vid / "meta.json"
            if meta_p.exists():
                m = json.loads(meta_p.read_text())
                af = m.get("audio_file")
                if af and (FIXTURES / source / vid / af).exists():
                    audio_path = FIXTURES / source / vid / af
                    method_detail = "used FROZEN audio fixture (live pull unavailable)"
        if audio_path is not None:
            fw = FasterWhisper("tiny")
            if fw.available():
                res = fw.transcribe(Path(audio_path))
                if res.ok:
                    transcript = res.transcript
                    method = "asr:faster-whisper-tiny"

    # (c) page-transcript scrape for arbitrary self-hosted fixture
    if not transcript.cues and source == "arbitrary":
        pf = FIXTURES / source / vid / "page.html"
        tf = FIXTURES / source / vid / "app_transcript.vtt"
        if tf.exists():
            transcript = parse_vtt(tf.read_text())
            method = "page-transcript"

    sections = _section_table(transcript)
    header = f"Transcript — {source}/{vid}"
    tpath = out / "transcript.md"
    _write_transcript_md(tpath, transcript, sections, header)

    # 4 manifest
    manifest = []
    for f in [tpath]:
        b = f.read_bytes()
        manifest.append({"file": f.name, "bytes": len(b),
                         "sha256": hashlib.sha256(b).hexdigest()})

    report = {
        "prompt": f"Get me the transcript of {url}; produce a clean timestamped "
                  f"transcript + a table of sections/topics; save transcript.md.",
        "source": source, "vid": vid, "url": url,
        "resolve_strategy": strategy,
        "stealth": stealth,
        "transform_method": method, "transform_detail": method_detail,
        "n_cues": len(transcript.cues),
        "transcript_words": len(transcript.norm_tokens()),
        "sections": sections,
        "manifest": manifest,
        "wall_s": round(time.perf_counter() - t_start, 1),
        "audio_used": str(audio_path) if audio_path else "",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    return {"report": report, "outdir": str(out), "transcript": transcript}


def score_pipeline(res: dict) -> dict:
    report = res["report"]
    source, vid = report["source"], report["vid"]
    transcript: Transcript = res["transcript"]

    hard = {"save_ok": False, "transcript_nonempty": False}
    tpath = Path(res["outdir"]) / "transcript.md"
    hard["save_ok"] = tpath.exists() and tpath.stat().st_size > 0
    hard["transcript_nonempty"] = report["n_cues"] > 0
    hard["transform_method"] = report["transform_method"]

    # transcription accuracy vs gold (hard) — only if a frozen fixture exists
    acc = {"has_gold": False}
    if (FIXTURES / source / vid / "meta.json").exists():
        oc = Oracle(source, vid)
        sc = oc.score(transcript)
        acc = to_dict(sc)
    hard["accuracy"] = acc

    # stealth scorecard for THIS pull (hard-scored dimension)
    st = report["stealth"]
    stealth_score = {
        "strategy": st.get("strategy"),
        "resolved": bool(st.get("ok")) and not st.get("blocked"),
        "blocked": bool(st.get("blocked")),
        "latency_ms": st.get("latency_ms", 0),
    }

    advisory = {"n_sections": len(report["sections"]),
                "section_table": "advisory-only (not hard-scored)"}
    return {"outdir": res["outdir"], "hard": hard,
            "stealth": stealth_score, "advisory": advisory,
            "wall_s": report["wall_s"]}
