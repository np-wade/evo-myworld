"""stealth.py — the stealth race against the JA3 hardened target (Tier-R).

Each strategy fetches the wall's home page with cert-verification OFF (so the
ONLY thing being judged is the TLS fingerprint, never cert trust). We record who
gets a 200 (RESOLVED) vs a 403 (BLOCKED), plus the JA3 signals the server saw
(GREASE present? ALPN h2?). This is the measurement the owned site could never
make — it finally shows what curl-impersonate / Scrapling actually buy.

Strategies:
  urllib            -- stdlib ssl (OpenSSL JA3, no GREASE)      -> expect BLOCKED
  curl_cffi-plain   -- libcurl default, no impersonation        -> expect BLOCKED
  curl_cffi-chrome  -- impersonate Chrome (GREASE)              -> expect RESOLVED
  curl_cffi-safari  -- impersonate Safari (GREASE)              -> expect RESOLVED
  scrapling         -- Scrapling static stealth fetch           -> measured
"""
from __future__ import annotations

import ssl
import statistics
import time
import urllib.request
from dataclasses import asdict, dataclass

from .hardened import HardenedServer

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/125.0 Safari/537.36")


@dataclass
class Hit:
    status: int = 0
    grease: int = -1
    ja3: str = ""
    alpn_h2: int = -1
    ms: float = 0.0
    err: str = ""


def _unverified() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def fetch_urllib(url: str) -> Hit:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        r = urllib.request.urlopen(req, timeout=8, context=_unverified())
        return Hit(r.status, int(r.headers.get("X-JA3-Grease", -1)),
                   r.headers.get("X-JA3-Hash", ""),
                   int(r.headers.get("X-JA3-ALPN-h2", -1)),
                   (time.perf_counter() - t0) * 1000)
    except urllib.error.HTTPError as e:      # 403 arrives here
        return Hit(e.code, int(e.headers.get("X-JA3-Grease", -1)),
                   e.headers.get("X-JA3-Hash", ""),
                   int(e.headers.get("X-JA3-ALPN-h2", -1)),
                   (time.perf_counter() - t0) * 1000)
    except Exception as e:
        return Hit(err=str(e)[:120], ms=(time.perf_counter() - t0) * 1000)


def fetch_curl(url: str, impersonate: str | None) -> Hit:
    from curl_cffi import requests as cr
    t0 = time.perf_counter()
    try:
        kw = {"verify": False, "timeout": 8}
        if impersonate:
            kw["impersonate"] = impersonate
        r = cr.get(url, **kw)
        h = r.headers
        return Hit(r.status_code, int(h.get("X-JA3-Grease", -1)),
                   h.get("X-JA3-Hash", ""), int(h.get("X-JA3-ALPN-h2", -1)),
                   (time.perf_counter() - t0) * 1000)
    except Exception as e:
        return Hit(err=str(e)[:120], ms=(time.perf_counter() - t0) * 1000)


def fetch_scrapling(url: str) -> Hit:
    from scrapling.fetchers import Fetcher
    t0 = time.perf_counter()
    for kw in ({"stealthy_headers": True, "verify": False, "timeout": 8},
               {"stealthy_headers": True, "timeout": 8}):
        try:
            page = Fetcher.get(url, **kw)
            st = getattr(page, "status", 0)
            h = getattr(page, "headers", {}) or {}
            g = h.get("X-JA3-Grease", h.get("x-ja3-grease", -1))
            return Hit(st, int(g), h.get("X-JA3-Hash", h.get("x-ja3-hash", "")),
                       int(h.get("X-JA3-ALPN-h2", h.get("x-ja3-alpn-h2", -1))),
                       (time.perf_counter() - t0) * 1000)
        except TypeError:
            continue    # this scrapling build rejects 'verify' -> retry w/o
        except Exception as e:
            return Hit(err=str(e)[:120], ms=(time.perf_counter() - t0) * 1000)
    return Hit(err="scrapling: no compatible signature")


STRATEGIES = [
    ("urllib", lambda u: fetch_urllib(u)),
    ("curl_cffi-plain", lambda u: fetch_curl(u, None)),
    ("curl_cffi-chrome", lambda u: fetch_curl(u, "chrome")),
    ("curl_cffi-safari", lambda u: fetch_curl(u, "safari")),
    ("scrapling", lambda u: fetch_scrapling(u)),
]


def _avail(name: str) -> bool:
    if name.startswith("curl_cffi"):
        try:
            import curl_cffi  # noqa: F401
            return True
        except Exception:
            return False
    if name == "scrapling":
        try:
            import scrapling  # noqa: F401
            return True
        except Exception:
            return False
    return True


def stealth_race(runs: int = 5) -> dict:
    srv = HardenedServer()
    rows = []
    skipped = []
    try:
        for name, fn in STRATEGIES:
            if not _avail(name):
                skipped.append(name)
                continue
            res, lats, grease, ja3, alpn = 0, [], -1, "", -1
            blocked, errs, err_msg = 0, 0, ""
            for _ in range(runs):
                h = fn(srv.base + "/")
                lats.append(h.ms)
                if h.err:
                    errs += 1; err_msg = h.err
                elif h.status == 200:
                    res += 1
                elif h.status == 403:
                    blocked += 1
                if h.grease != -1:
                    grease, ja3, alpn = h.grease, h.ja3, h.alpn_h2
            rows.append({
                "strategy": name, "runs": runs,
                "resolve_rate": round(res / runs, 3),
                "block_rate": round(blocked / runs, 3),
                "err_rate": round(errs / runs, 3),
                "grease": grease, "alpn_h2": alpn, "ja3_hash": ja3,
                "p50_ms": round(statistics.median(lats), 1) if lats else 0.0,
                "error": err_msg})
    finally:
        stats = srv.stats()
        srv.stop()
    ranked = sorted(rows, key=lambda r: (-r["resolve_rate"], r["p50_ms"]))
    return {"stage": "stealth", "runs": runs, "server_stats": stats,
            "leaderboard": ranked, "candidates_skipped": skipped}


def format_stealth(res: dict) -> str:
    L = [f"stealth race — JA3 hardened target (no-GREASE TLS = 403), "
         f"runs={res['runs']}", "",
         "  policy: a browser-like ClientHello (GREASE present) passes; stock "
         "Python/plain-libcurl is blocked.", ""]
    hdr = (f"{'strategy':18} {'resolve':>8} {'block':>7} {'err':>5} "
           f"{'GREASE':>7} {'alpn_h2':>8} {'p50ms':>8} {'ja3':>10}")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        g = {1: "yes", 0: "no", -1: "?"}.get(r["grease"], "?")
        a = {1: "yes", 0: "no", -1: "?"}.get(r["alpn_h2"], "?")
        tag = "🏆 " if r["resolve_rate"] == 1.0 else "   "
        L.append(f"{tag}{r['strategy']:15} {r['resolve_rate']:8.2f} "
                 f"{r['block_rate']:7.2f} {r['err_rate']:5.2f} {g:>7} {a:>8} "
                 f"{r['p50_ms']:8.1f} {(r['ja3_hash'] or '-')[:8]:>10}"
                 + ("  ERR:" + r["error"] if r["error"] else ""))
    if res["candidates_skipped"]:
        L += ["", f"skipped: {', '.join(res['candidates_skipped'])}"]
    return "\n".join(L)
