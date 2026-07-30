"""Transcription candidates — the "transform" leg. App produces its OWN
transcript by NORMAL means (never the grader's gold channel):

  (a) caption-scrape   -- app-scraped auto-captions (yt-dlp writeautomaticsub),
                          parsed to a Transcript. Cheapest; when it works it wins.
  (b) faster-whisper    -- local ASR on downloaded audio. SMALLEST models
     (tiny/base)          (tiny/base int8) = the local-AI angle: a local box must
                          handle it. Runs OFFLINE on frozen audio fixtures.
  (c) page-transcript   -- for the arbitrary site: scrape the ON-PAGE transcript
                          the app can see (NOT the grader gold parse).

Each candidate is available()-gated. The offline asr-race runs the ASR
candidates on frozen audio; caption/page candidates run in the pipeline where a
frozen app-scrape is available.
"""
from __future__ import annotations

import sys
import time
import types
import wave
from dataclasses import dataclass
from pathlib import Path

from .transcript import Transcript, Cue, clean_caption_text, parse_vtt

# corpus donor for the streaming candidate (graph-first: reuse, don't rewrite)
WHISPER_STREAMING_CORPUS = (Path.home() / "coding/docker-envs/filing-cabinet"
                            / "library-base/repos/ufal_whisper_streaming/code")


@dataclass
class ASROut:
    ok: bool
    transcript: Transcript
    wall_s: float = 0.0
    model: str = ""
    error: str = ""
    audio_min: float = 0.0     # audio duration used, for cost/min


class ASRCandidate:
    key = "?"
    kind = "asr"               # "asr" | "caption" | "page"
    def available(self) -> bool: return False
    def transcribe(self, audio: Path, audio_min: float = 0.0) -> ASROut: ...


class FasterWhisper(ASRCandidate):
    kind = "asr"
    def __init__(self, model_size: str = "tiny"):
        self.model_size = model_size
        self.key = f"faster-whisper-{model_size}"
        self._model = None
    def available(self) -> bool:
        try: import faster_whisper; return True  # noqa
        except Exception: return False
    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device="cpu",
                                       compute_type="int8")
        return self._model
    def transcribe(self, audio: Path, audio_min: float = 0.0) -> ASROut:
        t0 = time.perf_counter()
        try:
            model = self._load()
            segments, info = model.transcribe(str(audio), language="en",
                                              beam_size=1, vad_filter=True)
            cues = [Cue(float(s.start), float(s.end),
                        clean_caption_text(s.text)) for s in segments]
            dur = audio_min or (float(getattr(info, "duration", 0)) / 60.0)
            return ASROut(True, Transcript(cues),
                          round(time.perf_counter() - t0, 2),
                          model=self.key, audio_min=round(dur, 3))
        except Exception as e:
            return ASROut(False, Transcript([]),
                          round(time.perf_counter() - t0, 2),
                          model=self.key, error=str(e)[:200])


class OpenAIWhisper(ASRCandidate):
    """Reference openai-whisper (torch CPU). Heavier than faster-whisper; raced
    to check whether the CTranslate2 port gives anything up on accuracy."""
    kind = "asr"
    def __init__(self, model_size: str = "tiny"):
        self.model_size = model_size
        self.key = f"openai-whisper-{model_size}"
        self._model = None
    def available(self) -> bool:
        try: import whisper; return hasattr(whisper, "load_model")  # noqa
        except Exception: return False
    def _load(self):
        if self._model is None:
            import whisper
            self._model = whisper.load_model(self.model_size, device="cpu")
        return self._model
    def transcribe(self, audio: Path, audio_min: float = 0.0) -> ASROut:
        t0 = time.perf_counter()
        try:
            model = self._load()
            # openai-whisper shells out to ffmpeg for a path; decode the frozen
            # 16k-mono WAV ourselves and pass the array so no ffmpeg is needed
            samples = _read_wav_16k_mono(Path(audio))
            res = model.transcribe(samples, language="en", fp16=False)
            cues = [Cue(float(s["start"]), float(s["end"]),
                        clean_caption_text(s["text"]))
                    for s in res.get("segments", [])]
            return ASROut(True, Transcript(cues),
                          round(time.perf_counter() - t0, 2),
                          model=self.key, audio_min=round(audio_min, 3))
        except Exception as e:
            return ASROut(False, Transcript([]),
                          round(time.perf_counter() - t0, 2),
                          model=self.key, error=str(e)[:200])


def _read_wav_16k_mono(audio: Path):
    """Fixture audio is frozen as 16 kHz mono PCM WAV — decode with stdlib wave
    (no librosa/ffmpeg on this box)."""
    import numpy as np
    with wave.open(str(audio), "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1:
            raise ValueError(f"need 16k mono wav, got "
                             f"{w.getframerate()}Hz/{w.getnchannels()}ch")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


class WhisperStreaming(ASRCandidate):
    """ufal/whisper_streaming (corpus donor) driven in simulated real-time:
    audio fed in chunks through OnlineASRProcessor, transcript = committed
    output. Same faster-whisper weights underneath — what's raced is the
    STREAMING policy (buffer trimming, re-transcription), i.e. does chunked
    commit cost accuracy vs one-shot, and what latency profile it buys."""
    kind = "asr"
    CHUNK_S = 10.0    # sim step; real deployments use ~1s, too slow for CPU race
    def __init__(self, model_size: str = "tiny"):
        self.model_size = model_size
        self.key = f"whisper-streaming-{model_size}"
        self._online_mod = None
    def available(self) -> bool:
        if not (WHISPER_STREAMING_CORPUS / "whisper_online.py").exists():
            return False
        try: import faster_whisper, numpy; return True  # noqa
        except Exception: return False
    def _mod(self):
        if self._online_mod is None:
            # donor imports librosa/soundfile at module top but only its own
            # load_audio() uses them — shim so the import succeeds without deps
            for name in ("librosa", "soundfile"):
                if name not in sys.modules:
                    sys.modules[name] = types.ModuleType(name)
            if str(WHISPER_STREAMING_CORPUS) not in sys.path:
                sys.path.insert(0, str(WHISPER_STREAMING_CORPUS))
            import whisper_online
            self._online_mod = whisper_online
        return self._online_mod
    def transcribe(self, audio: Path, audio_min: float = 0.0) -> ASROut:
        t0 = time.perf_counter()
        try:
            wo = self._mod()

            class _CPUFasterWhisperASR(wo.FasterWhisperASR):
                # donor hardcodes device="cuda"; this box is CPU int8
                def load_model(self, modelsize=None, cache_dir=None,
                               model_dir=None):
                    from faster_whisper import WhisperModel
                    return WhisperModel(modelsize or "tiny", device="cpu",
                                        compute_type="int8",
                                        download_root=cache_dir)

            asr = _CPUFasterWhisperASR("en", self.model_size)
            online = wo.OnlineASRProcessor(asr)
            pcm = _read_wav_16k_mono(audio)
            step = int(self.CHUNK_S * 16000)
            cues: list[Cue] = []
            for i in range(0, len(pcm), step):
                online.insert_audio_chunk(pcm[i:i + step])
                beg, end, text = online.process_iter()
                if beg is not None and text:
                    cues.append(Cue(float(beg), float(end),
                                    clean_caption_text(text)))
            beg, end, text = online.finish()
            if beg is not None and text:
                cues.append(Cue(float(beg), float(end),
                                clean_caption_text(text)))
            dur = audio_min or (len(pcm) / 16000.0 / 60.0)
            return ASROut(True, Transcript(cues),
                          round(time.perf_counter() - t0, 2),
                          model=self.key, audio_min=round(dur, 3))
        except Exception as e:
            return ASROut(False, Transcript([]),
                          round(time.perf_counter() - t0, 2),
                          model=self.key, error=str(e)[:200])


class CaptionScrape(ASRCandidate):
    """Reads an app-scraped auto-caption VTT (frozen as app_auto.vtt in the
    fixture, or produced live in the pipeline). Not the grader's gold.vtt."""
    key = "caption-scrape"
    kind = "caption"
    def available(self) -> bool: return True
    def from_vtt(self, vtt_path: Path) -> ASROut:
        t0 = time.perf_counter()
        try:
            t = parse_vtt(Path(vtt_path).read_text())
            return ASROut(bool(t.cues), t, round(time.perf_counter() - t0, 3),
                          model=self.key)
        except Exception as e:
            return ASROut(False, Transcript([]), 0.0, model=self.key,
                          error=str(e)[:200])
    def transcribe(self, audio: Path, audio_min: float = 0.0) -> ASROut:
        # no audio path; caption-scrape works from a vtt, handled via from_vtt
        return ASROut(False, Transcript([]), 0.0, model=self.key,
                      error="caption-scrape needs a vtt, not audio")


def build_asr_candidates() -> list[ASRCandidate]:
    return [FasterWhisper("tiny"), FasterWhisper("base"), FasterWhisper("small"),
            OpenAIWhisper("tiny"), OpenAIWhisper("base"),
            WhisperStreaming("tiny"), CaptionScrape()]


def audio_asr_candidates() -> list[ASRCandidate]:
    return [c for c in build_asr_candidates()
            if c.kind == "asr" and c.available()]
