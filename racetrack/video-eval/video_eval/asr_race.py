"""ASR race — OFFLINE. Run each available ASR candidate on the frozen audio
fixtures and score vs gold (oracle). No network: only faster-whisper model
weights are needed (cached once under ~/.cache/huggingface).

Per candidate, aggregated over fixtures WITH gold:
  WER / CER      -- median vs gold captions
  drift_s        -- median timestamp drift over aligned anchors
  cost_min       -- wall-clock SECONDS per MINUTE of audio (local-feasibility)
  wall_s         -- median wall-clock
For no-gold fixtures (Twitch): WER/CER are omitted; the row is flagged and only
cost/latency + a consistency note are reported.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import sources
from .asr import audio_asr_candidates, build_asr_candidates
from .oracle import Oracle
from .race import median

FIXTURES = Path(__file__).parent.parent / "fixtures"


@dataclass
class ASRRow:
    candidate: str
    n_gold: int
    n_nogold: int
    wer_med: float
    cer_med: float
    drift_s_med: float
    cost_s_per_min: float     # local-feasibility: sec of compute per audio-minute
    wall_s_med: float
    fails: int
    note: str = ""
    error: str = ""


def _fixtures_with_audio() -> list[tuple[str, str, Path, dict]]:
    out = []
    for e in sources.frozen_entries():
        d = FIXTURES / e.source / e.vid
        meta = json.loads((d / "meta.json").read_text())
        af = meta.get("audio_file")
        if af and (d / af).exists():
            out.append((e.source, e.vid, d / af, meta))
    return out


def asr_race(sample: int = 0) -> dict:
    fixtures = _fixtures_with_audio()
    if sample:
        fixtures = fixtures[:sample]
    cands = audio_asr_candidates()
    skipped = [c.key for c in build_asr_candidates()
               if c.kind == "asr" and not c.available()]

    rows: list[ASRRow] = []
    for c in cands:
        wers, cers, drifts, costs, walls = [], [], [], [], []
        n_gold, n_nogold, fails = 0, 0, 0
        err = ""
        for source, vid, audio, meta in fixtures:
            audio_min = float(meta.get("duration_s", 0)) / 60.0
            try:
                out = c.transcribe(audio, audio_min=audio_min)
            except Exception as e:
                fails += 1
                err = f"{vid}: {type(e).__name__}: {e}"[:160]
                continue
            if not out.ok:
                fails += 1
                if out.error:
                    err = out.error
                continue
            walls.append(out.wall_s)
            amin = out.audio_min or audio_min
            if amin > 0:
                costs.append(out.wall_s / amin)
            oc = Oracle(source, vid)
            sc = oc.score(out.transcript)
            if sc.has_gold:
                n_gold += 1
                wers.append(sc.wer)
                cers.append(sc.cer)
                if sc.drift_s >= 0:
                    drifts.append(sc.drift_s)
            else:
                n_nogold += 1
        rows.append(ASRRow(
            candidate=c.key, n_gold=n_gold, n_nogold=n_nogold,
            wer_med=round(median(wers), 4) if wers else -1.0,
            cer_med=round(median(cers), 4) if cers else -1.0,
            drift_s_med=round(median(drifts), 3) if drifts else -1.0,
            cost_s_per_min=round(median(costs), 2) if costs else -1.0,
            wall_s_med=round(median(walls), 2) if walls else -1.0,
            fails=fails,
            note=("no-gold fixtures scored cost-only" if n_nogold and not n_gold
                  else ""),
            error=err,
        ))
    # rank: lowest WER first (gold rows), then cost
    rows.sort(key=lambda r: (r.wer_med if r.wer_med >= 0 else 9.9,
                             r.cost_s_per_min if r.cost_s_per_min >= 0 else 9e9))
    return {
        "n_fixtures": len(fixtures),
        "fixtures": [f"{s}/{v}" for s, v, _, _ in fixtures],
        "candidates_skipped": skipped,
        "leaderboard": [asdict(r) for r in rows],
    }


def format_asr(res: dict) -> str:
    L = [f"ASR race (OFFLINE) — {res['n_fixtures']} frozen audio fixtures "
         f"({', '.join(res['fixtures']) or 'NONE'})", ""]
    hdr = (f"{'candidate':22} {'gold':>4} {'WER':>7} {'CER':>7} "
           f"{'drift_s':>8} {'cost/min':>9} {'wall_s':>8} {'fail':>5}")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        wer = f"{r['wer_med']:7.3f}" if r['wer_med'] >= 0 else "   n/a "
        cer = f"{r['cer_med']:7.3f}" if r['cer_med'] >= 0 else "   n/a "
        dr = f"{r['drift_s_med']:8.2f}" if r['drift_s_med'] >= 0 else "     n/a"
        cost = f"{r['cost_s_per_min']:9.2f}" if r['cost_s_per_min'] >= 0 else "      n/a"
        wall = f"{r['wall_s_med']:8.2f}" if r['wall_s_med'] >= 0 else "     n/a"
        L.append(f"{r['candidate']:22} {r['n_gold']:4d} {wer} {cer} {dr} "
                 f"{cost} {wall} {r['fails']:5d}")
        if r["error"]:
            L.append(f"    err: {r['error'][:80]}")
    if res["candidates_skipped"]:
        L.append(f"\nskipped: {', '.join(res['candidates_skipped'])}")
    return "\n".join(L)
