# HANDOFF — video-eval: "video → transcript" transform + stealth benchmark (Test 3)

> **2026-07-27 UPDATE** — 6-model ASR race, LIVE no-download transcript scrape,
> gold-leak fix, and the in-app Racetrack page are all covered in the session
> handoff: **`../scraper-search-lab/HANDOFF-2026-07-27-video-models-live-transcript.md`**
> (full results + every file path in §4–§5). Read that first; the below is the
> 2026-07-26 baseline.

**Updated:** 2026-07-26. **For:** the next AI picking this up.
**One-line:** New sibling benchmark to arxiv-eval. THREE source adapters
(YouTube / Twitch / arbitrary site), STEALTH as a first-class scored dimension,
and local ASR (faster-whisper) as the "transform" leg. Selftest green OFFLINE;
stealth-race, ASR-race, and a full pipeline all RAN LIVE this session.

---

## 0. Cleanup status (read first)

- **Nothing of mine is running. No ports opened. No containers created.**
  Nicholas's `phonectl-emu` / `kimi-cli` were NOT touched. arxiv-eval was NOT touched.
- `.venv/` (449M) and `fixtures/` (19M, 5 clips @ ~4.5M) are inert files. Nothing
  committed to git this session.
- **Time-sensitive:** the Twitch seed VOD id (`2829622205`, GamesDoneQuick) was
  live 2026-07-26. Twitch VOD ids rotate/expire — if the stealth-race twitch row
  starts erroring, grab a fresh id (see NEXT steps) or drive one via `pipeline --url`.
- The Twitch + arbitrary AUDIO fixtures deliberately reuse a trimmed YouTube clip
  (provenance recorded in each `meta.json`) so the no-gold ASR-consistency path and
  the on-page-transcript path are exercisable OFFLINE. This is documented, not hidden.

## 1. What this benchmark is

- **Seed prompt:** "Get me the transcript of `<media URL>`; produce a clean
  timestamped transcript + a table of sections/topics; save transcript.md."
- **Oracle trick:** the trustworthy transcript (creator MANUAL captions on YouTube;
  the on-page transcript for the arbitrary site) is GOLD, pulled grader-side ONCE by
  `fetch_fixtures.py` and frozen under `fixtures/<source>/<id>/`. The APP must produce
  its OWN transcript (scrape auto-captions OR local ASR on downloaded audio) — it may
  NOT read the gold channel.
- **Twitch** usually has no clean captions → `has_gold=False`: its ASR output is
  scored for consistency + latency/cost, NOT WER (flagged as such).
- **Two-track scoring:** transcription accuracy (WER/CER/drift) + stealth-success are
  HARD-scored; the section/topic table is ADVISORY only.

## 2. Results (all ran this session)

### STEALTH sub-leaderboard — `results-stealth-run1.json` (LIVE, the priority result)
3 fetch strategies raced on the media/caption pull, 2 urls/source × 2 retries.

| strategy | source | resolve | block | caps m/a | p50 ms |
|---|---|---|---|---|---|
| ytdlp-impersonate | youtube | 1.00 | 0.00 | 1.0/1.0 | 1179 |
| ytdlp-plain | youtube | 1.00 | 0.00 | 1.0/1.0 | 1208 |
| ytdlp-stealth-ua | youtube | 1.00 | 0.00 | 1.0/1.0 | 1603 |
| ytdlp-plain | twitch | 1.00 | 0.00 | 0.0/0.0 | 1159 |
| ytdlp-impersonate | twitch | 1.00 | 0.00 | 0.0/0.0 | 1173 |
| ytdlp-stealth-ua | twitch | 1.00 | 0.00 | 0.0/0.0 | 1180 |
| curl_cffi-page | arbitrary | 1.00 | 0.00 | — | ~0 (local) |
| ytdlp-{plain,stealth,impersonate} | arbitrary | 0.00 | 0.00 | — | ~30 |

**Finding:** *No bot-detection block tripped this session* (block_rate 0.00 across
every strategy that resolved) — echoes arxiv-eval's "blocking picture inverted."
YouTube served captions to ALL three yt-dlp strategies; `ytdlp-impersonate`
(curl_cffi TLS/JA3) is marginally fastest and the recommended default. Twitch VOD
resolved cleanly too (no wall hit on this IP/VOD). On the ARBITRARY source the yt-dlp
strategies correctly FAIL (`file://` disabled for security) and `curl_cffi-page` is
the right tool — a genuine strategy-fit result. The block-detection machinery
(soft-block markers, 403/429/sign-in-wall, retries) is wired and ready to score real
walls when they reappear (throttled IP, po-token challenge, aggressive Twitch VOD).

### ASR race — `results-asr-run1.json` (OFFLINE, on frozen audio)
faster-whisper on 5 frozen 120s clips (4 with gold), CPU int8, smallest models.

| candidate | gold | WER | CER | drift_s | cost s/min | wall_s |
|---|---|---|---|---|---|---|
| **faster-whisper-tiny** | 4 | **0.051** | 0.037 | 0.38 | **1.39** | 2.78 |
| faster-whisper-base | 4 | 0.053 | 0.037 | 1.17 | 5.67 | 11.33 |

**The one WER number: whisper-tiny = 0.051 WER (0.037 CER) on clean talk audio.**
tiny WINS: same accuracy as base but ~4× cheaper (1.39 vs 5.67 s of compute per
audio-minute) — the local-feasibility story. A local box transcribes a 30-min talk
in ~40s of CPU with tiny. (Both models actually ran fast enough here; base is kept as
a candidate but tiny is the recommended local default.)

### Pipeline scorecard — `pipeline-run1.json` + `out/youtube/UF8uR6Z6KLc/` (LIVE E2E)
Ran on ONE YouTube source (Steve Jobs 2005 Stanford, has gold). Chain: resolve via
ytdlp-impersonate → app-path auto-caption scrape → clean timestamped transcript +
topic table → save.

| metric | value |
|---|---|
| transform_method | caption-scrape (app auto-captions, NOT gold) |
| WER (windowed vs gold) | **0.0312** |
| CER | 0.032 |
| timestamp drift | 0.0 s (105 anchors) |
| stealth: resolved / blocked | true / false (impersonate, 1202 ms) |
| save_ok / transcript_nonempty | true / true |
| advisory sections | 8 (topic table) |
| wall | 3.7 s |

Deliverables saved: `out/youtube/UF8uR6Z6KLc/transcript.md` (topic table +
timestamped body) and `report.json` (with sha256 manifest).

## 3. What ran LIVE vs deferred

- **LIVE:** fixture freeze (3 YouTube manual-caption clips), stealth-race (all 3
  sources), ASR-race (tiny AND base, all 5 frozen clips, offline), pipeline (1 YouTube
  source, real network).
- **By design / not run:** Twitch has NO gold (WER n/a — scored consistency+latency).
  scrapling backend absent (skips). openai-whisper/larger models not installed (tiny
  is the local-AI target; add larger models as candidates later if a GPU appears).
- **ffmpeg is NOT installed** on this box. Worked around with PyAV (`av`): fixture
  audio is trimmed to 16k mono WAV without system ffmpeg, and yt-dlp keeps native audio
  in the app path. If you add ffmpeg you can trim on download (`download_ranges`).

## 4. Commands

```
cd ~/coding/docker-envs/projects/evo-myworld/racetrack/video-eval
.venv/bin/python -m video_eval list           # sources/strategies/candidates avail
.venv/bin/python -m video_eval selftest        # OFFLINE green (WER/CER/drift/VTT math)
.venv/bin/python -m video_eval stealth-race --limit 2 --retries 2 --out results-stealth-run1.json
.venv/bin/python -m video_eval asr-race --out results-asr-run1.json           # OFFLINE
.venv/bin/python -m video_eval pipeline --url "<media URL>" --out pipeline-run1.json
.venv/bin/python -m video_eval fetch-fixtures --sources youtube,arbitrary,twitch --limit 3
```
`uv` note (host python has no pip): `~/.local/bin/uv pip install --python .venv/bin/python <dep>`.
Optional: `VIDEO_EVAL_COOKIES=/path/cookies.txt` is honored by the stealth-UA / download
paths (cookies-from-browser is stubbed to this env var). Politeness sleeps are built in.

## 5. NEXT steps (in order of value)

1. **Wire as an evo benchmark** (the whole point). Optimize surface: fetch strategy per
   source (stealth), ASR model + decode knobs (vad_filter, beam_size — VAD nearly
   dropped a music-intro clip; that's a real tunable), caption-scrape vs ASR routing.
2. **Refresh Twitch fixtures with a REAL gold-less VOD you re-ASR** — grab a live id:
   `yt-dlp --flat-playlist --playlist-end 1 "https://www.twitch.tv/<channel>/videos"`.
   Twitch is the place to actually stress bot detection (try during a busy window).
3. **More YouTube gold clips** (seed pool has 6; 3 frozen). `fetch-fixtures --limit 6`.
4. **Caption-scrape vs ASR head-to-head in the race** — pipeline proves both work;
   promote caption-scrape into `asr-race` as a candidate where a frozen `app_auto.vtt`
   exists (much cheaper than ASR when captions are present).
5. **Real arbitrary site** — replace the self-authored fixture with a live podcast/
   conference page that embeds media + an on-page transcript (tests media discovery).

## 6. File locations

Package `video_eval/`: `oracle.py` (WER/CER/drift + windowed scoring), `transcript.py`
(VTT/SRT parse + normalize + rolling-window dedupe), `fetchers.py` (urllib/curl_cffi/
scrapling HTTP backends), `sources.py` (3 source adapters + SEED pool + URL classify),
`media.py` (yt-dlp stealth strategies + app-path caption/audio pulls), `asr.py`
(faster-whisper tiny/base + caption-scrape), `stealth_race.py`, `asr_race.py`,
`pipeline.py`, `race.py`, `cli.py`, `fetch_fixtures.py` (GRADER-ONLY gold freezer).
Results at repo root: `results-stealth-run1.json`, `results-asr-run1.json`,
`pipeline-run1.json`. Deliverable: `out/youtube/UF8uR6Z6KLc/`. Fixtures:
`fixtures/{youtube,twitch,arbitrary}/<id>/` (gold.vtt/gold.txt/audio.wav/meta.json;
arbitrary also has page.html + app_transcript.vtt). Base spec:
`../scraper-search-lab/test-suite-plan.md` (Test 3). Memory: `scraper-search-lab`.
