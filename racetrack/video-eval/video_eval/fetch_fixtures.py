"""GRADER-ONLY fixture freezer — builds the answer key. This is the PRIVILEGED
channel the app may NEVER use: it pulls the trustworthy transcript (creator
MANUAL captions on YouTube; the on-page transcript for the arbitrary site) and
freezes it as gold, plus a SMALL trimmed audio clip the offline ASR race runs on.

  fixtures/<source>/<id>/
    gold.vtt / gold.txt   -- gold transcript (manual captions / on-page)
    audio.wav             -- 16kHz mono, trimmed to max_secs (kept SMALL)
    meta.json             -- has_gold, duration_s, audio_file, langs, provenance

Re-runnable: skips an entry whose meta.json already exists. Trims with PyAV so
NO system ffmpeg is required. Keeps clips short so ASR stays fast.
"""
from __future__ import annotations

import json
import wave
from pathlib import Path

from . import sources
from .transcript import parse_vtt

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _trim_audio_to_wav(src: Path, dst: Path, max_secs: int) -> float:
    """Decode src, resample to 16k mono s16, write <= max_secs to dst WAV.
    Returns the written duration in seconds. Uses PyAV (no system ffmpeg).

    Robust: reads resampled samples via to_ndarray() (packed s16 mono) rather
    than raw planes, which decode-mangled some codecs (opus/mp4)."""
    import av
    import numpy as np
    from av.audio.resampler import AudioResampler
    rs = AudioResampler(format="s16", layout="mono", rate=16000)
    chunks: list = []
    total = 0
    with av.open(str(src)) as container:
        stream = container.streams.audio[0]
        for frame in container.decode(stream):
            t = float(frame.pts * stream.time_base) if frame.pts is not None else 0.0
            if t > max_secs:
                break
            for rf in rs.resample(frame):
                arr = rf.to_ndarray()          # shape (1, n) int16 for mono s16
                chunks.append(arr.reshape(-1).astype("<i2"))
        # flush the resampler
        for rf in rs.resample(None):
            chunks.append(rf.to_ndarray().reshape(-1).astype("<i2"))
    data = np.concatenate(chunks) if chunks else np.zeros(0, "<i2")
    data = data[: max_secs * 16000]
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(data.tobytes())
    return round(len(data) / 16000, 2)


def _trim_vtt(vtt_text: str, max_secs: int) -> str:
    t = parse_vtt(vtt_text)
    keep = [c for c in t.cues if c.start < max_secs]
    def hms(s: float) -> str:
        h = int(s // 3600); m = int(s % 3600 // 60); sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:06.3f}"
    out = ["WEBVTT", ""]
    for c in keep:
        out.append(f"{hms(c.start)} --> {hms(min(c.end, max_secs))}")
        out.append(c.text); out.append("")
    return "\n".join(out)


def _freeze_youtube(e, max_secs: int) -> dict:
    import yt_dlp
    d = FIXTURES / e.source / e.vid
    d.mkdir(parents=True, exist_ok=True)
    work = d / "_work"; work.mkdir(exist_ok=True)
    # 1 resolve + check MANUAL captions (gold channel)
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "socket_timeout": 40,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}}}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(e.url, download=False)
    subs = info.get("subtitles") or {}
    dur = int(info.get("duration") or 0)
    lang = "en" if "en" in subs else next((l for l in subs if l.startswith("en")),
                                          next(iter(subs), ""))
    has_gold = bool(lang)
    meta = {"source": e.source, "vid": e.vid, "url": e.url,
            "title": str(info.get("title", ""))[:120],
            "orig_duration_s": dur, "caption_lang": lang, "has_gold": has_gold}
    # 2 pull MANUAL captions -> gold.vtt (privileged)
    if has_gold:
        gopts = {"quiet": True, "no_warnings": True, "skip_download": True,
                 "writesubtitles": True, "writeautomaticsub": False,
                 "subtitleslangs": [lang], "subtitlesformat": "vtt",
                 "outtmpl": str(work / "%(id)s.%(ext)s"),
                 "extractor_args": {"youtube": {"player_client": ["android", "web"]}}}
        with yt_dlp.YoutubeDL(gopts) as y:
            y.download([e.url])
        vtts = sorted(work.glob("*.vtt"))
        if vtts:
            trimmed = _trim_vtt(vtts[0].read_text(), max_secs)
            (d / "gold.vtt").write_text(trimmed)
            (d / "gold.txt").write_text(parse_vtt(trimmed).full_text)
        else:
            meta["has_gold"] = has_gold = False
    # 3 download audio (native) then trim to small WAV
    aopts = {"quiet": True, "no_warnings": True, "format": "bestaudio/best",
             "outtmpl": str(work / "%(id)s.%(ext)s"), "socket_timeout": 60,
             "extractor_args": {"youtube": {"player_client": ["android", "web"]}}}
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget
        aopts["impersonate"] = ImpersonateTarget("chrome")
    except Exception:
        pass
    with yt_dlp.YoutubeDL(aopts) as y:
        y.download([e.url])
    raw = [p for p in work.iterdir()
           if p.suffix.lower() in (".m4a", ".webm", ".opus", ".mp3", ".mp4", ".ogg")]
    if raw:
        wdur = _trim_audio_to_wav(raw[0], d / "audio.wav", max_secs)
        meta["audio_file"] = "audio.wav"
        meta["duration_s"] = wdur
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def _freeze_arbitrary_from(youtube_vid: str, e, max_secs: int) -> dict:
    """Self-authored arbitrary page: embed the trimmed audio + the on-page
    transcript (gold). Reuses a frozen youtube clip as the media so the fixture
    is fully offline + self-consistent (the 'I own the truth' oracle trick)."""
    src = FIXTURES / "youtube" / youtube_vid
    d = FIXTURES / e.source / e.vid
    d.mkdir(parents=True, exist_ok=True)
    if not (src / "audio.wav").exists() or not (src / "gold.vtt").exists():
        meta = {"source": e.source, "vid": e.vid, "url": e.url,
                "has_gold": False, "note": "donor youtube fixture missing"}
        (d / "meta.json").write_text(json.dumps(meta, indent=2))
        return meta
    (d / "audio.wav").write_bytes((src / "audio.wav").read_bytes())
    gold = (src / "gold.vtt").read_text()
    (d / "gold.vtt").write_text(gold)
    (d / "gold.txt").write_text(parse_vtt(gold).full_text)
    # app-visible transcript on the page == the same words (app scrapes THIS)
    (d / "app_transcript.vtt").write_text(gold)
    page = ("<html><head><title>Conference talk</title></head><body>"
            "<h1>Talk</h1>"
            "<audio controls src=\"audio.wav\"></audio>"
            "<section id=\"transcript\"><h2>Transcript</h2><pre>"
            + parse_vtt(gold).full_text[:4000] +
            "</pre></section></body></html>")
    (d / "page.html").write_text(page)
    src_meta = json.loads((src / "meta.json").read_text())
    meta = {"source": e.source, "vid": e.vid,
            "url": f"file://{d/'page.html'}", "has_gold": True,
            "audio_file": "audio.wav",
            "duration_s": src_meta.get("duration_s", 0),
            "note": f"self-authored page; media+transcript from youtube/{youtube_vid}"}
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def _freeze_twitch_nogold_from(youtube_vid: str, e) -> dict:
    """No-gold ASR-consistency fixture. Live Twitch VODs weren't frozen this
    session (ids rotate + aggressive bot-walls); we reuse a trimmed clip with
    has_gold=False to exercise the consistency+latency scoring path OFFLINE.
    Provenance is recorded honestly."""
    src = FIXTURES / "youtube" / youtube_vid
    d = FIXTURES / e.source / e.vid
    d.mkdir(parents=True, exist_ok=True)
    meta = {"source": e.source, "vid": e.vid, "url": e.url, "has_gold": False}
    if (src / "audio.wav").exists():
        (d / "audio.wav").write_bytes((src / "audio.wav").read_bytes())
        sm = json.loads((src / "meta.json").read_text())
        meta.update({"audio_file": "audio.wav",
                     "duration_s": sm.get("duration_s", 0),
                     "note": ("no-gold ASR-only fixture; audio borrowed from "
                              f"youtube/{youtube_vid} to exercise consistency "
                              "scoring OFFLINE. Live Twitch VOD not frozen.")})
    else:
        meta["note"] = "no donor audio; Twitch VOD not frozen this session"
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def fetch_fixtures(sources_arg: str = "", limit: int = 6, max_secs: int = 120):
    want = set(sources_arg.split(",")) if sources_arg else {"youtube"}
    frozen_yt = []
    # YouTube first (the donors)
    if "youtube" in want:
        done = 0
        for e in sources.by_source("youtube"):
            if done >= limit:
                break
            d = FIXTURES / e.source / e.vid
            if (d / "meta.json").exists():
                print(f"skip (exists) {e.source}/{e.vid}")
                if (d / "audio.wav").exists():
                    frozen_yt.append(e.vid)
                continue
            try:
                m = _freeze_youtube(e, max_secs)
                ok = m.get("has_gold") and (d / "audio.wav").exists()
                print(f"froze youtube/{e.vid}: gold={m.get('has_gold')} "
                      f"audio={m.get('duration_s','?')}s title={m.get('title','')[:40]}")
                if (d / "audio.wav").exists():
                    frozen_yt.append(e.vid)
                done += 1
            except Exception as ex:
                print(f"FAIL youtube/{e.vid}: {str(ex)[:160]}")
    else:
        frozen_yt = [e.vid for e in sources.by_source("youtube")
                     if (FIXTURES / "youtube" / e.vid / "audio.wav").exists()]

    donor = frozen_yt[0] if frozen_yt else None
    if "arbitrary" in want and donor:
        for e in sources.by_source("arbitrary"):
            d = FIXTURES / e.source / e.vid
            if (d / "meta.json").exists():
                print(f"skip (exists) {e.source}/{e.vid}"); continue
            m = _freeze_arbitrary_from(donor, e, max_secs)
            print(f"froze arbitrary/{e.vid}: gold={m.get('has_gold')} (donor={donor})")
    if "twitch" in want and donor:
        for e in sources.by_source("twitch"):
            d = FIXTURES / e.source / e.vid
            if (d / "meta.json").exists():
                print(f"skip (exists) {e.source}/{e.vid}"); continue
            m = _freeze_twitch_nogold_from(donor, e)
            print(f"froze twitch/{e.vid}: has_gold=False (donor={donor})")
    print("done.")
