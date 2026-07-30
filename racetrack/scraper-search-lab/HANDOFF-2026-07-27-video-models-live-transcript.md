# HANDOFF — 2026-07-27: T3 video new models + LIVE no-download transcript scrape + Racetrack app page

**Written:** 2026-07-27. **For:** the next AI / seat picking this up.
**Scope of this session (3 asks from Nicholas):**
1. Integrate the previously-untested ASR models into the T3 video test and race them.
2. Make transcripting a **live scrape** test that gets the transcript **without downloading the media**.
3. Surface all racetrack results **natively in the evo-myworld app** (not a standalone HTML), properly nav-linked.

All three landed and were verified live. This doc is the full record: what worked,
what was problematic, what is still missing, the complete test results, and every file path.

---

## 0. TL;DR

- **6 ASR models** now raced (was 2). Winner on accuracy: `faster-whisper-small` (WER 0.042);
  winner on value: `faster-whisper-tiny` (WER 0.051 @ 1.9 s/audio-min). openai-whisper + the
  ufal whisper_streaming corpus donor are now integrated and scored. **0 fails.**
- **New `transcript-race`**: live caption scrape, **media_bytes hard-gated to 0** (verified 0 on
  every candidate). Winner `innertube-android` (private InnerTube ANDROID player endpoint), 3/3
  resolve, WER 0.102, ~3× faster than yt-dlp.
- **Integrity bug fixed**: the old pipeline scored a fake WER 0.031 because it was fetching the
  creator's MANUAL captions = the grader's gold channel. Now auto-only; honest WER ~0.10.
- **Racetrack page** added to the evo dashboard: `/api/racetrack` + a nav tab render every suite's
  `results-*.json` leaderboards and the `*-suite.md` cards natively.

---

## 1. What WORKED

| Thing | Result |
|---|---|
| faster-whisper-small/base/tiny | all ran on 5 frozen clips, 0 fails; tiny reads WAV natively (no ffmpeg) |
| openai-whisper tiny/base (torch CPU) | integrated; made ffmpeg-free by decoding the WAV ourselves → numpy array |
| whisper-streaming (ufal corpus donor) | driven in simulated real-time chunks; CUDA hardcode overridden to CPU int8; scored |
| `transcript-race` no-download scrape | 5 candidates, media_bytes=0 on all; 2 resolve fully |
| InnerTube ANDROID caption endpoint | bypasses the POT-token wall the web client now hits; fastest + reliable |
| Rolling-caption parser fix | token-overlap dedupe in `transcript.py` took live WER 1.08 → 0.10 |
| Pipeline routing | now uses in-memory `caption-scrape-live` first (no files, no media), fixture-audio ASR fallback |
| `/api/racetrack` + Racetrack nav page | verified live on a booted dashboard (:8097); all 5 suites + leaderboards render |

## 2. What was PROBLEMATIC (and how it was resolved)

1. **openai-whisper failed 5/5 on missing ffmpeg.** openai-whisper's `transcribe(path)` shells out
   to `ffmpeg`, which is not installed on this box. **Fix:** decode the frozen 16k-mono WAV with the
   stdlib `wave` module → numpy float32 and pass the array (`asr.py::_read_wav_16k_mono`,
   `OpenAIWhisper.transcribe`). faster-whisper never had this problem (it bundles its own decoder).
2. **Live transcript WER was 1.08 (worse than random).** YouTube's raw timedtext VTT is a *rolling
   window* — each cue repeats the previous line plus new words, so naive concatenation doubled every
   word. **Fix:** token-level suffix/prefix overlap dedupe in `transcript.py::_dedupe` +
   preferring word-timed lines in `parse_vtt`. Live WER dropped to 0.102.
3. **GOLD LEAK (integrity).** `media.py::download_auto_captions` had `writesubtitles=True`, which
   fetches the creator's MANUAL caption track — the exact channel the grader uses as gold. That is
   why the old pipeline "scored" WER 0.031. **Fix:** `writesubtitles=False` (auto-only). Honest WER
   is ~0.10. This was a real scoring-validity bug, not a perf regression.
4. **Web-client caption scraping is POT-token walled.** `watch-page-{curl_cffi,scrapling,urllib}`
   all fetch the watch page fine (HTTP 200) but the timedtext URL now returns an empty HTTP-200
   body without a valid POT token → 0 cues. Not solved; the android endpoint sidesteps it. These
   candidates are kept in the race precisely to *document* the wall (they resolve 0/3).
5. **scrapling watch-page needs a browser stack.** `scrapling`'s stealthy fetch pulls in
   playwright/browserforge; installed `playwright` + `browserforge` so it imports, but it still hits
   the same POT wall (0 cues) — so it adds nothing over curl_cffi here.
6. **No git workspace with `.evo` data on this box.** Couldn't boot the dashboard against a live
   experiment graph, so `/api/racetrack` was verified against the repo root directly (it only needs
   `racetrack/`, not graph data). The rest of the dashboard's pages were not re-smoke-tested.

## 3. What is STILL MISSING / not covered (lingering)

- **transcript-race is YouTube-only.** Twitch and the arbitrary source are NOT in the no-download
  scrape race. Twitch has no captions (ASR path); arbitrary uses an on-page transcript — both could
  be added as their own no-download scrape candidates.
- **Twitch was not re-tested live this session.** The seed VOD id `2829622205` was live 2026-07-26;
  it may have rotated/expired. `results-stealth-run1.json` is still from 7-26 — the stealth race was
  NOT re-run. Refresh a VOD id before trusting the twitch row.
- **Stealth race not re-run.** No hardened / Tier-R target exists yet, so block_rate is still 0.00
  everywhere and the stealth-browser candidates (camofox/cloak/invisible_playwright) still have no
  wall to prove themselves on. This is the same gap flagged in the T5 handoff.
- **GPU / larger models untested.** faster-whisper-small at ~20 s/audio-min is CPU-bound; medium/
  large and any GPU run are deferred until a GPU appears. openai-whisper medium/large not installed.
- **whisper-streaming is a proxy, not true streaming latency.** CHUNK_S=10s (real deployments feed
  ~1s chunks; too slow on this CPU). Its 8.85s timestamp drift reflects buffer-trimming at a coarse
  chunk size — a directional result, not a production latency number.
- **transcript-race gold pool = 3 frozen YouTube clips.** Only the 3 with frozen `gold.vtt` are
  scored for WER; the other 3 seed entries aren't frozen. Freeze more for a bigger sample.
- **Racetrack page not visually smoke-tested in a browser/Electron.** Verified via HTTP (endpoint
  JSON), static-asset 200s, and `node --check views.js` only. WSL can't launch the Electron GUI
  (same caveat as the evo-desktop app). Open it on Windows to eyeball the rendering.
- **Nothing committed to git.** All changes are in the working tree of `evo-myworld` (branch
  `ai/claude-dashboard-design`). Commit when ready.
- **InnerTube client version is hardcoded** (`ANDROID` / `20.10.38`). If YouTube ages it out or
  extends POT enforcement to the android client, `innertube-android` will start returning 0 cues —
  fall back to `ytdlp-caption-live` (also 3/3, just slower) and bump the version.

---

## 4. FULL TEST RESULTS

### 4a. ASR race — OFFLINE, 5×120s frozen clips (`results-asr-run2.json`)
4 clips have gold (WER scored); Twitch is gold-less (cost-only, omitted from the WER rows here).

| candidate | gold | WER | CER | drift_s | cost s/min | wall_s | fails |
|---|---|---|---|---|---|---|---|
| faster-whisper-small | 4 | **0.042** | 0.029 | 0.64 | 19.79 | 39.57 | 0 |
| 🏆 faster-whisper-tiny | 4 | 0.051 | 0.037 | 0.38 | **1.88** | 3.75 | 0 |
| whisper-streaming-tiny | 4 | 0.052 | 0.039 | 8.85 | 31.25 | 62.49 | 0 |
| faster-whisper-base | 4 | 0.053 | 0.037 | 1.17 | 9.84 | 19.67 | 0 |
| openai-whisper-base | 4 | 0.053 | 0.037 | 3.17 | 10.18 | 20.36 | 0 |
| openai-whisper-tiny | 4 | 0.058 | 0.041 | 0.61 | 7.53 | 15.05 | 0 |

**Read:** small is most accurate but ~10× tiny's compute. tiny is the local default (accuracy within
0.01 of small at a fraction of the cost). faster-whisper (CTranslate2) beats reference openai-whisper
at the same size on BOTH speed and accuracy. whisper-streaming matches tiny on WER but pays heavy
timestamp drift for chunked commit.

### 4b. Live transcript-SCRAPE race — LIVE, 3 YouTube, NO media download (`results-transcript-run4.json`)
`media_bytes` column MUST be 0 (the whole point) — it is 0 for every candidate.

| scraper | resolve | block | WER | CER | drift_s | p50 ms | cap kB | media B | fails |
|---|---|---|---|---|---|---|---|---|---|
| 🏆 innertube-android | 1.00 | 0.00 | 0.102 | 0.086 | 1.13 | 1813 | 112.4 | **0** | 0 |
| ytdlp-caption-live | 1.00 | 0.00 | 0.102 | 0.086 | 1.13 | 5270 | 112.4 | **0** | 0 |
| watch-page-scrapling | 0.00 | 0.00 | n/a | n/a | n/a | 2309 | n/a | 0 | 3 (POT wall / 0 cues) |
| watch-page-curl_cffi | 0.00 | 0.00 | n/a | n/a | n/a | 2433 | n/a | 0 | 3 (vtt 200 empty) |
| watch-page-urllib | 0.00 | 0.00 | n/a | n/a | n/a | 2716 | n/a | 0 | 3 (vtt 200 empty) |

### 4c. End-to-end pipeline — LIVE, 1 YouTube (`pipeline-run2.json`, `out/youtube/UF8uR6Z6KLc/`)

| metric | value |
|---|---|
| transform_method | **caption-scrape-live** (in-memory, no files, no media) |
| WER (auto-caption vs manual-caption gold) | **0.1055** |
| CER | 0.0865 |
| timestamp drift | 1.18 s (96 anchors) |
| stealth | ytdlp-impersonate, resolved, not blocked |
| save_ok / transcript_nonempty | true / true |
| advisory sections | 8 |
| wall | 9.2 s |

### 4d. Candidate availability (`python -m video_eval list`)
ASR: `faster-whisper-{tiny,base,small}`, `openai-whisper-{tiny,base}`, `whisper-streaming-tiny`,
`caption-scrape` — all `[x]`. Live scrapers: `innertube-android`, `ytdlp-caption-live`,
`watch-page-{curl_cffi,scrapling,urllib}` — all `[x]`. Sources: youtube 6 seed/3 frozen,
twitch 1/1, arbitrary 1/1.

### 4e. Historical rows (not re-run this session)
- Stealth sub-leaderboard: `results-stealth-run1.json` (2026-07-26) — block_rate 0.00 everywhere;
  ytdlp-impersonate the recommended default. **Stale; refresh before trusting Twitch.**
- Earlier transcript runs `results-transcript-run{1,2,3}.json` show the progression
  (run1 WER 1.08 pre-fix → run3/4 WER 0.102 post-fix; run3 added innertube).

---

## 5. FILE PATHS — everything

Base: `~/coding/docker-envs/projects/evo-myworld/` (repo, branch `ai/claude-dashboard-design`).

### 5a. Video-eval package — `racetrack/video-eval/`
| File | What changed / is |
|---|---|
| `video_eval/asr.py` | **+`OpenAIWhisper`, +`WhisperStreaming`, +`_read_wav_16k_mono`, faster-whisper-small in `build_asr_candidates`** |
| `video_eval/transcript_race.py` | **NEW** — `InnertubeAndroid`, `YtdlpCaptionLive`, `WatchPageScraper`, `transcript_race()`, `format_transcript_race()` |
| `video_eval/transcript.py` | **rolling-caption fix** in `_dedupe` + `parse_vtt` (word-timed-line preference) |
| `video_eval/media.py` | **gold-leak fix**: `download_auto_captions` now `writesubtitles=False` |
| `video_eval/pipeline.py` | **routes through `caption-scrape-live`** (in-memory scrapers) before file/ASR fallbacks |
| `video_eval/cli.py` | **+`transcript-race` subcommand**, `list` shows scrapers |
| `video_eval/{asr_race,sources,fetchers,oracle,stealth_race,race,__init__}.py` | unchanged this session |

### 5b. Results (video-eval root)
| File | Content |
|---|---|
| `racetrack/video-eval/results-asr-run2.json` | 6-model ASR leaderboard (the current one) |
| `racetrack/video-eval/results-transcript-run4.json` | live no-download scrape race (current) |
| `racetrack/video-eval/pipeline-run2.json` | E2E scorecard (caption-scrape-live) |
| `racetrack/video-eval/results-transcript-run{1,2,3}.json` | earlier progression |
| `racetrack/video-eval/results-asr-run1.json`, `results-stealth-run1.json`, `pipeline-run1.json` | prior-session baselines |
| `racetrack/video-eval/out/youtube/UF8uR6Z6KLc/` | deliverable: `transcript.md`, `report.json`, `work/` |
| `racetrack/video-eval/fixtures/{youtube,twitch,arbitrary}/<id>/` | frozen gold (~19M, 5 clips) |
| `racetrack/video-eval/asr-run{2,3}.log` | race stdout logs |

### 5c. Racetrack dashboard integration (evo plugin)
| File | What |
|---|---|
| `plugins/evo/src/evo/racetrack.py` | **NEW** — `build_racetrack()`, `find_racetrack_dir()`, leaderboard reader |
| `plugins/evo/src/evo/dashboard.py` | **+`GET /api/racetrack`** (just above the Assembly Office bridge) |
| `plugins/evo/src/evo/static/index.html` | **+Racetrack nav tab + `#view-racetrack` section** |
| `plugins/evo/src/evo/static/views.js` | **+`loadRacetrack()`, `renderRacetrackDetail()`, `rtTable()`**; `#racetrack` in router/refresh |
| `plugins/evo/src/evo/static/design.css` | **+`.rt-*` styles** (appended) |

### 5d. Result cards / index (what the dashboard renders)
| File | What |
|---|---|
| `racetrack/results/video-suite.md` | **updated** with 6-model ASR, live scrape race, pipeline, integrity note |
| `racetrack/results/INDEX.md` | **updated** — points to the in-app Racetrack page |
| `racetrack/results/{arxiv,substack,watchdog}-suite.md` | other suites (unchanged) |
| `racetrack/results/dashboard.html` | standalone fallback (superseded by the in-app page) |

### 5e. Corpus donor + venv
- whisper_streaming donor: `~/coding/docker-envs/filing-cabinet/library-base/repos/ufal_whisper_streaming/code/whisper_online.py`
- venv (host python has no pip): `racetrack/video-eval/.venv/`; installs via
  `~/.local/bin/uv pip install --python .venv/bin/python <dep>`. Added this session:
  `torch` (CPU wheel), `openai-whisper`, `scrapling`, `playwright`, `browserforge`.

### 5f. Memory
- `~/.claude/projects/-home-npwad/memory/scraper-search-lab.md` (2026-07-27 entry)
- `~/.claude/projects/-home-npwad/memory/evo-desktop-app.md` (Racetrack page note)

---

## 6. Commands

```bash
cd ~/coding/docker-envs/projects/evo-myworld/racetrack/video-eval
.venv/bin/python -m video_eval list                    # availability (ASR + scrapers)
.venv/bin/python -m video_eval selftest                # OFFLINE parser/WER math
.venv/bin/python -m video_eval asr-race --out results-asr-run2.json          # OFFLINE, 6 models
.venv/bin/python -m video_eval transcript-race --limit 3 --out results-transcript-run4.json  # LIVE, no download
.venv/bin/python -m video_eval pipeline --url "<yt url>" --no-asr --out pipeline-run2.json    # E2E live scrape

# Racetrack page (from repo root, host venv):
EVO_DASHBOARD_PORT=8097 PYTHONPATH=plugins/evo/src plugins/evo/.venv-host/bin/python -m evo.dashboard
curl -s http://127.0.0.1:8097/api/racetrack | python3 -m json.tool   # then open #racetrack in the app
```

## 7. NEXT (priority order)
1. **Add Twitch + arbitrary to `transcript-race`** so "no-download" covers all three sources.
2. **Refresh the Twitch VOD id + re-run the stealth race** (it's stale from 7-26).
3. **Add a hardened Tier-R target** so the stealth-browser candidates and block-detection actually bite.
4. **Wire T3 into `/evo:optimize`** — the optimize surface is caption-scrape-live-vs-ASR routing +
   ASR model/decoding knobs (reuse `scrapler-eval` metrics/gates/leaderboard).
5. **Eyeball the Racetrack page on Windows/Electron** (WSL can't launch the GUI).
6. **Commit** the working tree.
7. GPU pass: faster-whisper-small/medium + openai-whisper medium/large when a GPU appears.

Relevant memories: `scraper-search-lab`, `evo-desktop-app`, `graph-first-protocol`.
Sibling handoff (crawler field + T5): `HANDOFF-integration-and-T5.md`.
