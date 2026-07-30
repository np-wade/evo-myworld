"""Media resolution + STEALTH strategies — the first-class scored dimension.

Each MediaStrategy is a way to reach the media/caption servers. They race on:
did it resolve the media without a block, block-rate across retries, latency.
Strategies (available()-gated on yt-dlp / curl_cffi):

  ytdlp-plain       -- yt-dlp defaults, generic UA. The naive path bot-detectors
                       catch first.
  ytdlp-stealth-ua  -- custom Chrome UA + Accept-Language, sleep_interval,
                       retries, geo_bypass, android/web player client rotation,
                       cookies-from-browser STUBBED (honored if VIDEO_EVAL_COOKIES
                       points to a cookies.txt). The "stealth options" path.
  ytdlp-impersonate -- yt-dlp's built-in curl_cffi TLS/JA3 impersonation
                       (impersonate=chrome). The TLS-fingerprint path most likely
                       to slip past JA3-based bot detection.
  curl_cffi-page    -- for ARBITRARY sites: TLS-impersonated raw page fetch, then
                       detect <video>/<audio>/embed the app would scrape.

App path = normal scraping only; the gold caption channel is grader-only.
"""
from __future__ import annotations

import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import sources
from .fetchers import CurlCffiBackend, UrllibBackend


@dataclass
class MediaResult:
    strategy: str
    ok: bool                       # resolved media (formats or media tags found)
    blocked: bool                  # bot-detection / 403 / 429 / sign-in wall
    latency_ms: float = 0.0
    n_formats: int = 0
    has_manual_caps: bool = False
    has_auto_caps: bool = False
    caption_langs: list[str] = field(default_factory=list)
    media_urls: list[str] = field(default_factory=list)
    error: str = ""
    note: str = ""


_BLOCK_MARKERS = (
    "sign in to confirm", "not a bot", "confirm you're not a robot",
    "http error 403", "http error 429", "http error 503", "429",
    "unable to download", "blocked", "captcha", "unusual traffic",
    "this video is unavailable", "geo restricted", "rate-limit", "rate limit",
    "requested format is not available",  # often a downstream symptom of a block
    "failed to extract", "unable to extract",
)


def _is_block(msg: str) -> bool:
    low = msg.lower()
    return any(m in low for m in _BLOCK_MARKERS)


def _cookiefile() -> str | None:
    c = os.environ.get("VIDEO_EVAL_COOKIES", "")
    return c if c and Path(c).exists() else None


class MediaStrategy:
    name = "base"
    def available(self) -> bool: return False
    def resolve(self, url: str, timeout: int = 40) -> MediaResult: ...


# ---------------- yt-dlp-backed strategies ----------------------------------
def _ydl_opts_base(timeout: int) -> dict:
    return {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "socket_timeout": timeout, "noprogress": True,
        "extractor_retries": 1, "retries": 1,
    }


def _run_ydl(url: str, opts: dict) -> MediaResult:
    import yt_dlp
    name = opts.pop("_name", "ytdlp")
    t0 = time.perf_counter()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        dt = (time.perf_counter() - t0) * 1000
        if info is None:
            return MediaResult(name, False, True, dt, error="no info (blocked?)")
        # a playlist entry?
        if info.get("_type") == "playlist" and info.get("entries"):
            info = next((e for e in info["entries"] if e), info)
        fmts = info.get("formats") or []
        subs = info.get("subtitles") or {}
        auto = info.get("automatic_captions") or {}
        media = [f.get("url") for f in fmts if f.get("url")][:3]
        return MediaResult(
            name, ok=bool(fmts) or bool(info.get("url")), blocked=False,
            latency_ms=dt, n_formats=len(fmts),
            has_manual_caps=bool(subs), has_auto_caps=bool(auto),
            caption_langs=sorted(set(list(subs) + list(auto)))[:12],
            media_urls=media,
            note=f"title={str(info.get('title',''))[:50]}")
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000
        msg = str(e)
        return MediaResult(name, False, _is_block(msg), dt, error=msg[:200])


class YtdlpPlain(MediaStrategy):
    name = "ytdlp-plain"
    def available(self) -> bool:
        try: import yt_dlp; return True  # noqa
        except Exception: return False
    def resolve(self, url: str, timeout: int = 40) -> MediaResult:
        opts = _ydl_opts_base(timeout)
        opts["_name"] = self.name
        return _run_ydl(url, opts)


class YtdlpStealthUA(MediaStrategy):
    name = "ytdlp-stealth-ua"
    def available(self) -> bool:
        try: import yt_dlp; return True  # noqa
        except Exception: return False
    def resolve(self, url: str, timeout: int = 40) -> MediaResult:
        opts = _ydl_opts_base(timeout)
        opts.update({
            "_name": self.name,
            "http_headers": {
                "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/125.0 Safari/537.36"),
                "Accept-Language": "en-US,en;q=0.9",
            },
            "sleep_interval": 1, "max_sleep_interval": 3,
            "geo_bypass": True, "retries": 3, "extractor_retries": 2,
            # rotate player clients for youtube (android+web dodges some walls)
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        })
        cf = _cookiefile()
        if cf:
            opts["cookiefile"] = cf
        return _run_ydl(url, opts)


class YtdlpImpersonate(MediaStrategy):
    name = "ytdlp-impersonate"
    def available(self) -> bool:
        try:
            import yt_dlp  # noqa
            import curl_cffi  # noqa
            return True
        except Exception:
            return False
    def resolve(self, url: str, timeout: int = 40) -> MediaResult:
        import yt_dlp
        opts = _ydl_opts_base(timeout)
        opts["_name"] = self.name
        try:
            from yt_dlp.networking.impersonate import ImpersonateTarget
            opts["impersonate"] = ImpersonateTarget("chrome")
        except Exception:
            opts["impersonate"] = "chrome"
        return _run_ydl(url, opts)


# ---------------- arbitrary-site strategy (raw TLS page fetch) ---------------
_MEDIA_TAG = re.compile(
    r"""<(?:audio|video|source|iframe)[^>]+(?:src)=["']([^"']+)["']""", re.I)


class CurlCffiPage(MediaStrategy):
    name = "curl_cffi-page"
    def available(self) -> bool:
        return CurlCffiBackend().available()
    def resolve(self, url: str, timeout: int = 40) -> MediaResult:
        be = CurlCffiBackend()
        # local self-hosted fixture: read from disk (no network)
        if url.startswith("file://"):
            p = url[len("file://"):]
            try:
                html = Path(p).read_text()
            except Exception as e:
                return MediaResult(self.name, False, False, error=str(e)[:120])
            media = _MEDIA_TAG.findall(html)
            return MediaResult(self.name, ok=bool(media), blocked=False,
                               media_urls=media[:5],
                               note="local fixture page (no network)")
        r = be.get(url, timeout=timeout)
        media = _MEDIA_TAG.findall(r.text) if r.text else []
        return MediaResult(
            self.name, ok=r.ok and bool(media), blocked=r.blocked,
            latency_ms=r.latency_ms, media_urls=media[:5], error=r.error,
            note=f"status={r.status}")


ALL_STRATEGIES = [YtdlpPlain(), YtdlpStealthUA(), YtdlpImpersonate(),
                  CurlCffiPage()]


def available_strategies() -> list[MediaStrategy]:
    return [s for s in ALL_STRATEGIES if s.available()]


def strategies_for(source: str) -> list[MediaStrategy]:
    """The curl_cffi-page strategy only makes sense for arbitrary pages; the
    yt-dlp strategies carry youtube/twitch (yt-dlp also handles many generic
    sites, so it's offered for arbitrary too)."""
    strat = available_strategies()
    if source in ("youtube", "twitch"):
        return [s for s in strat if s.name != "curl_cffi-page"]
    return strat


# ---------------- app-path media/caption pulls (used by pipeline) -----------
def download_auto_captions(url: str, outdir: Path, lang: str = "en",
                           timeout: int = 60) -> Path | None:
    """APP PATH: scrape auto-generated captions via yt-dlp (NOT the gold channel).
    Returns the .vtt path or None. Writes into outdir."""
    import yt_dlp
    outdir.mkdir(parents=True, exist_ok=True)
    opts = _ydl_opts_base(timeout)
    opts.pop("_name", None)
    opts.update({
        # AUTO captions ONLY — writesubtitles would fetch the creator MANUAL
        # track, which is the grader's gold channel (integrity leak, found
        # 2026-07-27: it made caption-scrape score a fake WER 0.031)
        "writesubtitles": False, "writeautomaticsub": True,
        "subtitleslangs": [lang, f"{lang}.*", "en"], "subtitlesformat": "vtt",
        "skip_download": True, "outtmpl": str(outdir / "%(id)s.%(ext)s"),
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception:
        pass
    vtts = sorted(outdir.glob("*.vtt"))
    return vtts[0] if vtts else None


def download_audio(url: str, outdir: Path, timeout: int = 180,
                   impersonate: bool = True) -> Path | None:
    """APP PATH: download bestaudio in NATIVE format (no ffmpeg postproc, since
    ffmpeg may be absent). Returns the audio path or None."""
    import yt_dlp
    outdir.mkdir(parents=True, exist_ok=True)
    opts = _ydl_opts_base(timeout)
    opts.pop("_name", None)
    opts.update({
        "skip_download": False, "format": "bestaudio/best",
        "outtmpl": str(outdir / "%(id)s.%(ext)s"),
        "sleep_interval": 1, "max_sleep_interval": 3, "geo_bypass": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    })
    if impersonate:
        try:
            from yt_dlp.networking.impersonate import ImpersonateTarget
            opts["impersonate"] = ImpersonateTarget("chrome")
        except Exception:
            pass
    cf = _cookiefile()
    if cf:
        opts["cookiefile"] = cf
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            vid = info.get("id", "")
    except Exception:
        vid = ""
    cands = [p for p in outdir.iterdir()
             if p.suffix.lower() in (".m4a", ".webm", ".opus", ".mp3", ".wav",
                                     ".mp4", ".ogg") and not p.name.endswith(".vtt")]
    if vid:
        pref = [p for p in cands if p.stem == vid]
        if pref:
            return pref[0]
    return cands[0] if cands else None
