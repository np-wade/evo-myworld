"""STEALTH race — the sub-leaderboard Nicholas wants. Race the media/caption
fetch strategies (plain vs stealth-UA vs TLS-impersonate vs curl_cffi-page)
against real source URLs and record, per strategy:

  resolve_rate -- fraction of URLs whose media resolved WITHOUT a block
  block_rate   -- fraction of attempts flagged as bot-detection / 403 / 429 /
                  sign-in wall (across retries)
  p50/p95 ms   -- latency
  caps         -- how often manual/auto captions were exposed

Push it: we try the paths most likely to trip bot detection (YouTube's
sign-in-to-confirm wall, Twitch's aggressive checks) and record what gets
through. This stage NEEDS network. Politeness sleeps between attempts.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from . import media, sources
from .race import median, pct


@dataclass
class StealthRow:
    strategy: str
    source: str
    attempts: int
    resolve_rate: float       # resolved without block
    block_rate: float
    manual_caps_rate: float
    auto_caps_rate: float
    p50_ms: float
    p95_ms: float
    errors: list[str] = field(default_factory=list)


def _urls_for(source: str, limit: int, live_urls: list[str] | None) -> list[str]:
    if live_urls:
        return live_urls[:limit]
    urls = []
    for e in sources.by_source(source):
        # prefer a frozen fixture's real URL (e.g. arbitrary -> local page.html)
        mp = sources.FIXTURES / e.source / e.vid / "meta.json"
        if mp.exists():
            import json
            u = json.loads(mp.read_text()).get("url", e.url)
            urls.append(u)
        else:
            urls.append(e.url)
    return urls[:limit]


def stealth_race(source_list: list[str] | None = None, retries: int = 2,
                 limit: int = 3, polite_s: float = 2.5,
                 live_urls: dict | None = None) -> dict:
    source_list = source_list or ["youtube", "twitch", "arbitrary"]
    rows: list[StealthRow] = []
    skipped = [s.name for s in media.ALL_STRATEGIES if not s.available()]

    for source in source_list:
        urls = _urls_for(source, limit, (live_urls or {}).get(source))
        strats = media.strategies_for(source)
        for st in strats:
            lat, resolves, blocks, man, auto, attempts = [], 0, 0, 0, 0, 0
            errs: list[str] = []
            for url in urls:
                for _ in range(retries):
                    attempts += 1
                    try:
                        r = st.resolve(url)
                    except Exception as e:  # never let one attempt kill the race
                        blocks += 0
                        errs.append(f"{type(e).__name__}: {e}"[:120])
                        time.sleep(polite_s)
                        continue
                    lat.append(r.latency_ms)
                    if r.blocked:
                        blocks += 1
                    if r.ok and not r.blocked:
                        resolves += 1
                    if r.has_manual_caps:
                        man += 1
                    if r.has_auto_caps:
                        auto += 1
                    if r.error:
                        errs.append(r.error[:120])
                    time.sleep(polite_s)
            a = max(attempts, 1)
            rows.append(StealthRow(
                strategy=st.name, source=source, attempts=attempts,
                resolve_rate=round(resolves / a, 3),
                block_rate=round(blocks / a, 3),
                manual_caps_rate=round(man / a, 3),
                auto_caps_rate=round(auto / a, 3),
                p50_ms=pct(lat, .5), p95_ms=pct(lat, .95),
                errors=sorted(set(errs))[:3],
            ))
    # rank within the whole board: resolve desc, block asc, latency asc
    rows.sort(key=lambda r: (-r.resolve_rate, r.block_rate, r.p50_ms))
    return {
        "sources": source_list, "retries": retries, "limit": limit,
        "strategies_skipped": skipped,
        "leaderboard": [asdict(r) for r in rows],
    }


def format_stealth(res: dict) -> str:
    L = [f"STEALTH sub-leaderboard — sources={','.join(res['sources'])} "
         f"(retries={res['retries']}, {res['limit']} urls/source)", ""]
    hdr = (f"{'strategy':20} {'source':10} {'att':>4} {'resolve':>8} "
           f"{'block':>6} {'man':>5} {'auto':>5} {'p50ms':>8} {'p95ms':>8}")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        L.append(f"{r['strategy']:20} {r['source']:10} {r['attempts']:4d} "
                 f"{r['resolve_rate']:8.2f} {r['block_rate']:6.2f} "
                 f"{r['manual_caps_rate']:5.2f} {r['auto_caps_rate']:5.2f} "
                 f"{r['p50_ms']:8.1f} {r['p95_ms']:8.1f}")
        if r["errors"]:
            L.append(f"    err: {r['errors'][0]}")
    if res["strategies_skipped"]:
        L.append(f"\nskipped strategies (missing dep): "
                 f"{', '.join(res['strategies_skipped'])}")
    return "\n".join(L)
