# result: video-suite (T3)
seat: subagent (general-purpose) + video-eval
question: produce our OWN transcript of a video, across sources, under stealth
metric: min WER/CER vs creator-caption gold; min compute/min; max stealth resolve
gate: transcript.md saved, non-empty, in manifest; no fabricated transcript
oracle: creator-uploaded captions (manual) / on-page transcript — GRADER ONLY
package: video-eval/  •  run: `python3 -m video_eval pipeline --url <...>`

Seed task: "Get me the transcript of <media URL>; produce a clean timestamped
transcript + a section/topic table; save transcript.md." Sources: YouTube,
Twitch, arbitrary site. Stealth is a first-class scored dimension.

## Live transcript-SCRAPE race (LIVE, 3 YouTube, NO media download)  (results-transcript-run4.json)
Added 2026-07-27 for Nicholas's ask: scrape the transcript **without downloading
the media**. Every candidate pulls captions straight off the timedtext channel;
`media_bytes` is hard-gated at 0. AUTO captions only (manual = gold channel).
| scraper | resolve | WER | p50 ms | media B |
|---|---|---|---|---|
| 🏆 innertube-android | 1.00 | 0.102 | 1706 | 0 |
| ytdlp-caption-live | 1.00 | 0.102 | 5541 | 0 |
| watch-page-{curl_cffi,scrapling,urllib} | 0.00 | — | — | 0 |
Findings: YouTube's **web-client timedtext now returns empty HTTP-200 without a
POT token** → all watch-page scrapers fail; the private **InnerTube ANDROID**
player endpoint bypasses it (3/3, ~3× faster than yt-dlp). A rolling-caption
parser bug (WER 1.08) was fixed with token-overlap dedupe.

## Pipeline scorecard (LIVE, 1 YouTube source) — out/youtube/UF8uR6Z6KLc/
HARD: transcript saved ✓ non-empty ✓ (method: **caption-scrape-live**, in-memory,
no files/media), **WER 0.1055** (honest auto-caption vs manual-caption gold),
CER 0.0865, drift 1.18s over 96 anchors. STEALTH: ytdlp-impersonate, resolved,
not blocked. ADVISORY: 8-section topic table. 9.2s wall.
INTEGRITY FIX (2026-07-27): the old 0.0312 was a leak — `writesubtitles=True`
fetched the creator's MANUAL captions (the gold channel). Now auto-only.

## Stealth sub-leaderboard (LIVE, all 3 sources)  (results-stealth-run1.json)
Headline: **no bot-detection block tripped — block_rate 0.00 everywhere that
resolved** (mirrors arxiv-eval's "blocking inverted").
| strategy | source | resolve | block | caps m/a | p50 ms |
|---|---|---|---|---|---|
| 🏆 ytdlp-impersonate | youtube | 1.00 | 0.00 | 1.0/1.0 | 1179 |
| ytdlp-plain | youtube | 1.00 | 0.00 | 1.0/1.0 | 1208 |
| ytdlp-stealth-ua | youtube | 1.00 | 0.00 | 1.0/1.0 | 1603 |
| ytdlp-* (all 3) | twitch | 1.00 | 0.00 | 0/0 | ~1170 |
| 🏆 curl_cffi-page | arbitrary | 1.00 | 0.00 | — | local |
| ytdlp-* | arbitrary | 0.00 | 0.00 | — | ~30 (file:// blocked) |
Finding: impersonate (TLS/JA3) marginally fastest on YouTube → recommended
default. Twitch VOD resolved clean (no captions → ASR path). Arbitrary is a
strategy-fit result: yt-dlp can't do file://, curl_cffi-page can.

## ASR race (OFFLINE, 5×120s frozen clips)  (results-asr-run2.json)
Expanded 2026-07-27 from 2 → 6 models (the previously-deferred field, now raced):
- **faster-whisper-small** — WER **0.042** / CER 0.029. New accuracy leader, but
  22 s compute per audio-minute (~10× tiny) — GPU-or-batch territory.
- 🏆 **faster-whisper-tiny** — WER 0.051 at **2.2 s/min**. Still the local-
  feasibility winner (accuracy within 0.01 of small at a fraction of the cost).
- **whisper-streaming-tiny** (ufal corpus donor, simulated real-time chunks) —
  WER 0.052, but timestamp **drift 8.85s** from buffer-trimming: the honest
  streaming-vs-oneshot tradeoff, now measured instead of assumed.
- faster-whisper-base — WER 0.053.
- **openai-whisper-tiny/base** (torch CPU) — integrated; run ffmpeg-free by
  decoding the frozen WAV ourselves (openai-whisper otherwise shells to ffmpeg,
  absent here). tiny WER 0.058 @ 7.5 s/min, base WER 0.053 @ 10.2 s/min —
  confirms the CTranslate2 port (faster-whisper) is both faster AND slightly more
  accurate on this corpus (0 fails, all 6 models scored on 4 gold clips).

## Live vs stubbed
LIVE: fixture freeze (3 YouTube manual-caption clips), stealth-race (3 sources),
**transcript-scrape race (3 YouTube, no media download)**, pipeline (1 YouTube,
real network). OFFLINE: asr-race (6 models on 5 frozen clips).
BY DESIGN: Twitch has no gold (consistency+latency only); Twitch/arbitrary audio
reuse a trimmed YouTube clip (provenance in each meta.json). ffmpeg absent →
openai-whisper decodes WAV via stdlib `wave`; faster-whisper reads WAV natively.
scrapling now installed; playwright module present but watch-page still POT-walled.

## Files
Package `video-eval/video_eval/*.py` (15 modules; +`transcript_race.py`); results
`results-{stealth,asr}-run*.json`, `results-transcript-run4.json`,
`pipeline-run2.json`; deliverable `video-eval/out/youtube/UF8uR6Z6KLc/`;
fixtures `video-eval/fixtures/{youtube,twitch,arbitrary}/<id>/` (~19M, 5 clips);
handoff `video-eval/HANDOFF.md`. Run the live scrape race:
`python3 -m video_eval transcript-race --limit 3`.

## Notes
Twitch seed VOD id may expire (refresh cmd in HANDOFF). Top evo frontier: route
caption-scrape-live vs ASR by caption availability; faster-whisper-small when a
GPU appears; a hardened target to make the stealth bracket bite; POT-token solver
so the pure watch-page scrapers resolve again.
