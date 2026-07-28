"""behavioral.py — Tier-R++ : a JS-FINGERPRINT / behavioral wall.

The missing rung of the stealth ladder. The challenge race (challenge.py) proved
you need a JS engine to reach content — but a *plain* headless browser
(Playwright/Selenium/crawl4ai) already HAS a JS engine, so it clears that wall
just as well as a stealth one. challenge.py therefore can't separate a VANILLA
headless browser from a STEALTH browser. This server can.

It composes on top of the JA3 wall (require_grease, reused from hardened.py) and
then adds a second gate: the page ships a probe that measures the classic
*headless tells* and beacons the result back. Content is revealed ONLY if the
JS environment looks like a real human browser. The six checks:

  bit0  navigator.webdriver === false        (Playwright/Selenium set it TRUE)
  bit1  window.chrome present                 (absent in vanilla headless here)
  bit2  navigator.plugins.length > 0          (0 in headless)
  bit3  navigator.languages non-empty
  bit4  WebGL UNMASKED_RENDERER_WEBGL not headless (SwiftShader/llvmpipe/Mesa/
        Google == the software-GL renderer a headless box falls back to)
  bit5  a 2D canvas fingerprint that isn't the blank/degenerate signature

The probe ORs the passing bits into a mask and fetches /human-only?fp=<mask>.
The server is authoritative: mask == 0b111111 (all six) -> SOLVED, else DETECTED.
That splits the field a FOURTH way, beyond challenge.py:
  urllib                          -> BLOCKED at JA3 (no GREASE -> 403)
  curl_cffi-chrome / scrapling    -> pass JA3, but no JS -> DETECTED (no beacon)
  playwright/selenium/crawl4ai    -> pass JA3, run JS, FAIL fingerprint -> DETECTED
  playwright-stealth              -> pass JA3, run JS, PASS fingerprint -> SOLVED
Everything is localhost + the shared self-signed cert + deterministic offline JS.
"""
from __future__ import annotations

import ssl
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .crawl import (STEALTH_BROWSERS, Crawl4aiRenderer, JsdomRenderer,
                    PlaywrightRenderer, SeleniumRenderer)
from .hardened import ensure_cert, parse_ja3

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/125.0 Safari/537.36")

NBITS = 6
FULL_MASK = (1 << NBITS) - 1        # 0b111111 == 63 : all six tells passed
MARKER = "/human-only"

# The client-side probe. Runs on load, ORs each passing tell into `m`, then
# beacons /human-only?fp=<m>. Reveals the content link only on a full pass. No
# literal content URL in the raw HTML that a regex could shortcut — the mask (and
# thus the SOLVED verdict) exists only after real JS execution in a human-like env.
PROBE_JS = r"""
(function(){
  function webgl(){
    try{
      var c=document.createElement('canvas');
      var gl=c.getContext('webgl')||c.getContext('experimental-webgl');
      var d=gl.getExtension('WEBGL_debug_renderer_info');
      var r=(gl.getParameter(d.UNMASKED_RENDERER_WEBGL)||'')+'';
      return /(swiftshader|llvmpipe|mesa|google)/i.test(r)?0:1;
    }catch(e){return 0;}
  }
  function canvas(){
    try{
      var c=document.createElement('canvas');c.width=64;c.height=24;
      var x=c.getContext('2d');x.textBaseline='top';x.font='14px Arial';
      x.fillStyle='#f60';x.fillRect(0,0,52,20);
      x.fillStyle='#069';x.fillText('bot?<canvas>',2,2);
      var u=c.toDataURL();
      return (u.indexOf('data:image/png')===0 && u.length>200)?1:0;
    }catch(e){return 0;}
  }
  var b=[
    (navigator.webdriver===false)?1:0,
    (!!window.chrome)?1:0,
    (navigator.plugins&&navigator.plugins.length>0)?1:0,
    (navigator.languages&&navigator.languages.length>0)?1:0,
    webgl(),
    canvas()
  ];
  var m=0; for(var i=0;i<b.length;i++){ m|=(b[i]<<i); }
  fetch('/human-only?fp='+m).then(function(){
    var el=document.getElementById('c');
    if(m===63){ el.innerHTML="<a href='/human-only?fp="+m+"'>continue</a>"
      +" — SOLVED (human-like JS fingerprint)"; }
    else { el.innerHTML="bot detected — headless tells, fp="+m; }
  }).catch(function(){});
})();
"""

_CHALLENGE_HTML = (
    "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
    "<body><h1>Checking your browser before you continue...</h1>"
    "<div id='c'>Verifying your environment...</div>"
    "<script>" + PROBE_JS + "</script></body></html>").encode()


def _unverified() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


class BehavioralServer:
    """HTTPS server behind the JA3 wall that reveals content only to a client
    whose JS environment passes the headless-tell probe. Server-authoritative:
    it reads the beacon mask and decides SOLVED vs DETECTED. Keeps an independent
    hit-log; per-candidate state is reset() between sequential candidates (same
    single-connection correlation the http2fp race relies on)."""

    def __init__(self, host: str = "127.0.0.1", require_grease: bool = True):
        cert, key = ensure_cert()
        self.require_grease = require_grease
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.load_cert_chain(cert, key)
        self._ctx.set_alpn_protocols(["http/1.1"])
        self._hits: Counter = Counter()      # independent hit-log (path -> n)
        self._blocks = 0
        self._solved = 0
        self._lock = threading.Lock()
        # per-candidate run state (reset between candidates)
        self._state = {"page": False, "beacon": None, "blocked": False}
        import socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self.base = f"https://{host}:{self.port}"
        self._run = True
        threading.Thread(target=self._serve, daemon=True).start()

    def reset(self):
        with self._lock:
            self._state = {"page": False, "beacon": None, "blocked": False}

    def outcome(self) -> str:
        """Server-authoritative verdict for the current candidate."""
        with self._lock:
            s = self._state
        if s["blocked"]:
            return "blocked"                 # stopped at the JA3 wall (403)
        if s["beacon"] is not None:
            return "solved" if s["beacon"] == FULL_MASK else "detected"
        if s["page"]:
            return "detected"                # got the page but never ran JS
        return "blocked"                     # never reached content at all

    def _serve(self):
        while self._run:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,),
                             daemon=True).start()

    def _handle(self, conn):
        ja3 = None
        try:
            import socket as _s
            conn.settimeout(5)
            peek = conn.recv(8192, _s.MSG_PEEK)      # ClientHello, unconsumed
            ja3 = parse_ja3(peek)
            tls = self._ctx.wrap_socket(conn, server_side=True)
        except Exception:
            try: conn.close()
            except Exception: pass
            return
        try:
            req = tls.recv(4096).decode("latin1", "replace")
            raw = "/"
            if req.startswith("GET"):
                raw = req.split(" ", 2)[1]
            path = raw.split("?")[0]
            allowed = (ja3 is not None and
                       (ja3["has_grease"] or not self.require_grease))
            with self._lock:
                self._hits[path] += 1
            hdr = (f"X-JA3-Hash: {ja3['hash'] if ja3 else 'none'}\r\n"
                   f"X-JA3-Grease: {int(ja3['has_grease']) if ja3 else 0}\r\n")
            if not allowed:
                with self._lock:
                    self._state["blocked"] = True
                    self._blocks += 1
                body = (b"<html><body><h1>403 - bot detected (TLS fingerprint)"
                        b"</h1></body></html>")
                resp = (f"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\n"
                        f"Content-Length: {len(body)}\r\n{hdr}"
                        f"Connection: close\r\n\r\n").encode() + body
            elif path == MARKER:
                # the probe's beacon: record the fingerprint mask it reported.
                q = parse_qs(urlsplit(raw).query)
                try:
                    mask = int(q.get("fp", ["-1"])[0])
                except ValueError:
                    mask = -1
                solved = (mask == FULL_MASK)
                with self._lock:
                    self._state["beacon"] = mask
                    if solved:
                        self._solved += 1
                if solved:
                    body = (b"<html><title>Human verified</title><body>"
                            b"<h1>SOLVED - your JS fingerprint passed</h1>"
                            b"</body></html>")
                else:
                    body = (b"<html><title>Bot detected</title><body>"
                            b"<h1>DETECTED - headless fingerprint</h1>"
                            b"</body></html>")
                resp = (f"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                        f"Content-Length: {len(body)}\r\n{hdr}"
                        f"Connection: close\r\n\r\n").encode() + body
            else:
                # the challenge page: ships the probe; content link only appears
                # after the probe passes.
                with self._lock:
                    self._state["page"] = True
                resp = (f"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                        f"Content-Length: {len(_CHALLENGE_HTML)}\r\n{hdr}"
                        f"Connection: close\r\n\r\n").encode() + _CHALLENGE_HTML
            tls.sendall(resp)
        except Exception:
            pass
        finally:
            try: tls.close()
            except Exception: pass

    def stats(self) -> dict:
        with self._lock:
            return {"requests": sum(self._hits.values()),
                    "blocks": self._blocks, "solved": self._solved}

    def stop(self):
        self._run = False
        try: self._sock.close()
        except Exception: pass


# ---------------- fetchers (JS-less; they can never pass a JS wall) ----------
def _f_urllib(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        urllib.request.urlopen(req, timeout=8, context=_unverified()).read()
        return ""
    except Exception as e:
        return str(e)[:120]


def _f_curl(url, imp):
    from curl_cffi import requests as cr
    try:
        cr.get(url, impersonate=imp, verify=False, timeout=8)
        return ""
    except Exception as e:
        return str(e)[:120]


def _f_scrapling(url):
    from scrapling.fetchers import Fetcher
    for kw in ({"stealthy_headers": True, "verify": False, "timeout": 8},
               {"stealthy_headers": True, "timeout": 8}):
        try:
            Fetcher.get(url, **kw)
            return ""
        except TypeError:
            continue
        except Exception as e:
            return str(e)[:120]
    return "scrapling: no compatible signature"


FETCHERS = [
    ("urllib", lambda u: _f_urllib(u)),
    ("curl_cffi-chrome", lambda u: _f_curl(u, "chrome")),
    ("scrapling", lambda u: _f_scrapling(u)),
]
# Vanilla headless browsers (DETECTED) + the stealth-patched candidate(s) that
# PASS. STEALTH_BROWSERS is the extension point a later agent appends camofox/
# cloakbrowser/invisible_playwright/etc. to (see crawl.py).
BROWSERS = [PlaywrightRenderer, JsdomRenderer, Crawl4aiRenderer,
            SeleniumRenderer] + STEALTH_BROWSERS


def behavioral_race(runs: int = 3) -> dict:
    srv = BehavioralServer(require_grease=True)
    rows, skipped = [], []
    try:
        # JS-less fetchers (fast; N times). They can pass JA3 but never beacon.
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
                srv.reset()
                t0 = time.perf_counter()
                try:
                    fn(srv.base + "/")
                except Exception:
                    pass
                lats.append((time.perf_counter() - t0) * 1000)
                outs.append(srv.outcome())
            rows.append(_row(name, "fetcher", outs, lats))
        # browsers (expensive; one launch each). Per-candidate try/except so a
        # broken/missing entrant SKIPS or errors, never kills the race.
        for R in BROWSERS:
            r = R()
            if not r.available():
                skipped.append(getattr(r, "name", R.__name__)); continue
            srv.reset()
            t0 = time.perf_counter()
            try:
                r.open(); r.fetch(srv.base + "/"); r.close()
                res = srv.outcome()
            except Exception:
                res = "error"
            rows.append(_row(r.name, "browser", [res],
                             [(time.perf_counter() - t0) * 1000]))
    finally:
        stats = srv.stats()
        srv.stop()
    order = {"solved": 0, "detected": 1, "blocked": 2, "error": 3}
    ranked = sorted(rows, key=lambda x: (order.get(x["outcome"], 9), x["p50_ms"]))
    return {"stage": "behavioral", "runs": runs, "server_stats": stats,
            "leaderboard": ranked, "candidates_skipped": skipped}


def _row(name, kind, outs, lats):
    import statistics
    outcome = max(set(outs), key=outs.count)
    solved = sum(1 for o in outs if o == "solved") / len(outs)
    return {"strategy": name, "kind": kind, "outcome": outcome,
            "solve_rate": round(solved, 3),
            "p50_ms": round(statistics.median(lats), 1) if lats else 0.0}


def format_behavioral(res: dict) -> str:
    L = [f"behavioral race — Tier-R++ (JA3 wall + JS-fingerprint wall), "
         f"runs={res['runs']}", "",
         "  content is revealed only to a browser whose JS env passes the "
         "headless-tell probe", "  (webdriver/chrome/plugins/languages/WebGL-"
         "renderer/canvas) — separates PLAIN vs STEALTH.", ""]
    hdr = f"{'strategy':20} {'kind':8} {'outcome':>11} {'solve':>6} {'p50ms':>9}"
    L += [hdr, "-" * len(hdr)]
    icon = {"solved": "🏆", "detected": "🤖", "blocked": "⛔", "error": "⚠"}
    for r in res["leaderboard"]:
        L.append(f"{r['strategy']:20} {r['kind']:8} "
                 f"{icon.get(r['outcome'],'')} {r['outcome']:>9} "
                 f"{r['solve_rate']:6.2f} {r['p50_ms']:9.1f}")
    if res["candidates_skipped"]:
        L += ["", f"skipped: {', '.join(res['candidates_skipped'])}"]
    L += ["", "  🏆 solved (human-like JS fp)  🤖 detected (headless tells / no "
          "JS)  ⛔ blocked at JA3 wall"]
    # Honest footnote: a ⛔-blocked BROWSER is stopped at the TLS/JA3 layer, so its
    # JS-fingerprint stealth is never measured on the combined wall. camoufox is the
    # case in point — it passes all six JS tells with GREASE relaxed, but its
    # patched-Firefox ClientHello has no browser-JA3, so the combined wall 403s it.
    blocked_browsers = [r["strategy"] for r in res["leaderboard"]
                        if r["kind"] == "browser" and r["outcome"] == "blocked"]
    if "camoufox" in blocked_browsers:
        L += ["", "  note: camoufox ⛔ is a TLS/JA3 block, NOT a stealth failure — "
              "it passes all 6 JS tells", "  when GREASE is relaxed, but spoofs the "
              "browser fp only, not a browser JA3. Only an", "  engine carrying a "
              "GREASE JA3 (Chromium/Playwright path) clears BOTH layers."]
    return "\n".join(L)


if __name__ == "__main__":
    print(format_behavioral(behavioral_race()))
