"""challenge.py — Tier-R+ : a JS/behavioral challenge behind the JA3 wall.

Two layers now stack: (1) TLS/JA3 (no GREASE -> 403) and (2) a Cloudflare-style
JS challenge where the content link is assembled by JavaScript from fragments
(no literal in the raw HTML, so a regex can't shortcut it). To reach content a
client must BOTH present a browser TLS fingerprint AND execute JS. That splits
the field three ways:
  urllib                         -> BLOCKED at JA3 (403)
  curl_cffi-chrome / scrapling   -> pass JA3, but no JS -> CHALLENGED (stuck)
  playwright/selenium/crawl4ai   -> pass JA3 + run JS   -> SOLVED
  jsdom                          -> runs JS -> SOLVED (DOM-only is enough here)
This is the measurement that separates stealth FETCHERS from stealth BROWSERS —
JA3 alone couldn't, because a stealth fetcher clears a pure-TLS wall.
"""
from __future__ import annotations

import ssl
import time
import urllib.request

from .crawl import (Crawl4aiRenderer, JsdomRenderer, PlaywrightRenderer,
                    SeleniumRenderer)
from .hardened import HardenedServer

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/125.0 Safari/537.36")
MARKER = "/human-only"    # the JS-assembled link; its presence == solved


def _classify(status: int, text: str, err: str) -> str:
    if err:
        return "error"
    if status == 403:
        return "blocked"          # stopped at the JA3 wall
    if MARKER in (text or ""):
        return "solved"           # executed the JS, revealed the link
    return "challenged"           # passed JA3 but stuck on the JS wall


def _unverified() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _f_urllib(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        r = urllib.request.urlopen(req, timeout=8, context=_unverified())
        return r.status, r.read().decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as e:
        return e.code, "", ""
    except Exception as e:
        return 0, "", str(e)[:120]


def _f_curl(url, imp):
    from curl_cffi import requests as cr
    try:
        r = cr.get(url, impersonate=imp, verify=False, timeout=8)
        return r.status_code, r.text, ""
    except Exception as e:
        return 0, "", str(e)[:120]


def _f_scrapling(url):
    from scrapling.fetchers import Fetcher
    for kw in ({"stealthy_headers": True, "verify": False, "timeout": 8},
               {"stealthy_headers": True, "timeout": 8}):
        try:
            p = Fetcher.get(url, **kw)
            return getattr(p, "status", 0), \
                getattr(p, "html_content", "") or str(p), ""
        except TypeError:
            continue
        except Exception as e:
            return 0, "", str(e)[:120]
    return 0, "", "scrapling: no compatible signature"


FETCHERS = [
    ("urllib", lambda u: _f_urllib(u)),
    ("curl_cffi-chrome", lambda u: _f_curl(u, "chrome")),
    ("scrapling", lambda u: _f_scrapling(u)),
]
BROWSERS = [PlaywrightRenderer, JsdomRenderer, Crawl4aiRenderer, SeleniumRenderer]


def challenge_race(runs: int = 3) -> dict:
    srv = HardenedServer(js_challenge=True)
    rows = []
    skipped = []
    try:
        # fetch strategies (fast; run N times)
        for name, fn in FETCHERS:
            avail = True
            if name.startswith("curl"):
                try: import curl_cffi  # noqa
                except Exception: avail = False
            if name == "scrapling":
                try: import scrapling  # noqa
                except Exception: avail = False
            if not avail:
                skipped.append(name); continue
            outs, lats = [], []
            for _ in range(runs):
                t0 = time.perf_counter()
                st, txt, err = fn(srv.base + "/")
                lats.append((time.perf_counter() - t0) * 1000)
                outs.append(_classify(st, txt, err))
            rows.append(_row(name, "fetcher", outs, lats))
        # browser strategies (expensive; one launch each)
        for R in BROWSERS:
            r = R()
            if not r.available():
                skipped.append(f"{r.name}-crawl"); continue
            t0 = time.perf_counter()
            try:
                r.open(); out = r.fetch(srv.base + "/"); r.close()
                if out.ok:
                    res = _classify(200, out.text, "")
                elif "403" in (out.error or ""):
                    res = "blocked"          # jsdom: Node TLS has no GREASE
                else:
                    res = "error"
            except Exception as e:
                res = "error"
            rows.append(_row(f"{r.name}", "browser", [res],
                             [(time.perf_counter() - t0) * 1000]))
    finally:
        stats = srv.stats()
        srv.stop()
    order = {"solved": 0, "challenged": 1, "blocked": 2, "error": 3}
    ranked = sorted(rows, key=lambda x: (order.get(x["outcome"], 9), x["p50_ms"]))
    return {"stage": "challenge", "runs": runs, "server_stats": stats,
            "leaderboard": ranked, "candidates_skipped": skipped}


def _row(name, kind, outs, lats):
    import statistics
    # dominant outcome
    outcome = max(set(outs), key=outs.count)
    solved = sum(1 for o in outs if o == "solved") / len(outs)
    return {"strategy": name, "kind": kind, "outcome": outcome,
            "solve_rate": round(solved, 3),
            "p50_ms": round(statistics.median(lats), 1) if lats else 0.0}


def format_challenge(res: dict) -> str:
    L = [f"challenge race — Tier-R+ (JA3 wall + JS challenge), runs={res['runs']}",
         "", "  need BOTH a browser TLS fingerprint AND JS execution to reach "
         "content.", ""]
    hdr = f"{'strategy':18} {'kind':8} {'outcome':>11} {'solve':>6} {'p50ms':>9}"
    L += [hdr, "-" * len(hdr)]
    icon = {"solved": "🏆", "challenged": "🧱", "blocked": "⛔", "error": "⚠"}
    for r in res["leaderboard"]:
        L.append(f"{r['strategy']:18} {r['kind']:8} "
                 f"{icon.get(r['outcome'],'')} {r['outcome']:>9} "
                 f"{r['solve_rate']:6.2f} {r['p50_ms']:9.1f}")
    if res["candidates_skipped"]:
        L += ["", f"skipped: {', '.join(res['candidates_skipped'])}"]
    L += ["", "  🏆 solved  🧱 passed TLS but stuck on JS  ⛔ blocked at JA3 wall"]
    return "\n".join(L)
