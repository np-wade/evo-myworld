"""video-eval — the video/media -> transcript "transform + stealth" benchmark.

Seed task: "Get me the transcript of <media URL>; produce a clean timestamped
transcript + a table of sections/topics; save transcript.md."

Rule: the APP resolves/fetches media and produces its OWN transcript by NORMAL
scraping only (auto-caption scrape OR local ASR on downloaded audio). The
trustworthy gold transcript (creator captions on YouTube / on-page transcript
for the arbitrary site) is a PRIVILEGED grader channel used ONLY to build the
answer key in fetch_fixtures.py — the app may never touch it.

Three source adapters (each available()-gated): YOUTUBE, TWITCH, ARBITRARY site.
STEALTH is a first-class scored dimension: fetch strategies (plain vs curl_cffi
TLS-impersonation vs yt-dlp stealth options) race on block-rate + latency.

Heavy deps (yt-dlp, curl_cffi, faster-whisper, ffmpeg) live only in adapters,
available()-gated; the core scoring is pure stdlib and offline-rerunnable.
"""
__all__ = ["oracle", "fetchers", "media", "asr", "stealth_race", "asr_race",
           "pipeline", "sources"]
