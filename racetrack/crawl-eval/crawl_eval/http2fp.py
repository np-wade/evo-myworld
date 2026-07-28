"""http2fp.py — HTTP/2 fingerprinting target (the Akamai-style layer).

JA3 fingerprints the TLS ClientHello; the *next* layer real anti-bot systems use
is the HTTP/2 fingerprint — the client's SETTINGS frame values, its initial
connection WINDOW_UPDATE, and whether it sends PRIORITY frames. Different HTTP
stacks have very different h2 fingerprints: Chrome ≠ Firefox ≠ Safari ≠ plain
libcurl, and stock Python doesn't speak h2 at all.

This server negotiates ALPN, and for an h2 connection it parses the raw frames
(preface → SETTINGS → WINDOW_UPDATE → HEADERS) to build a fingerprint
`settings|window_update|priority`, then sends a minimal valid h2 200 so the
client gets a clean response. The race reads the server-captured fingerprint for
each client (requests are sequential, so `last` correlates cleanly). Pure stdlib
+ the shared self-signed cert. This is SETTINGS+WINDOW_UPDATE+PRIORITY of the
Akamai fp; pseudo-header order (needs HPACK decode) is left out.
"""
from __future__ import annotations

import socket
import ssl
import threading
import time
import urllib.request
from dataclasses import dataclass

from .hardened import ensure_cert

PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"
_SETTING_NAMES = {1: "HEADER_TABLE_SIZE", 2: "ENABLE_PUSH",
                  3: "MAX_CONCURRENT_STREAMS", 4: "INITIAL_WINDOW_SIZE",
                  5: "MAX_FRAME_SIZE", 6: "MAX_HEADER_LIST_SIZE"}


# --- minimal HPACK decode: just enough to read the pseudo-header ORDER ---
# Real browsers reference pseudo-header NAMES via the HPACK static table, so we
# never need Huffman name decoding here; literal VALUES are skipped by length.
_STATIC = {1: ":authority", 2: ":method", 3: ":method", 4: ":path",
           5: ":path", 6: ":scheme", 7: ":scheme", 8: ":status", 9: ":status",
           10: ":status", 11: ":status", 12: ":status", 13: ":status",
           14: ":status"}
_PCODE = {":method": "m", ":authority": "a", ":scheme": "s", ":path": "p",
          ":status": "st"}


def _hpack_int(data, pos, prefix):
    mask = (1 << prefix) - 1
    val = data[pos] & mask
    pos += 1
    if val < mask:
        return val, pos
    m = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        val += (b & 0x7f) << m
        m += 7
        if not (b & 0x80):
            break
    return val, pos


def _hpack_skip_str(data, pos):
    length, pos = _hpack_int(data, pos, 7)   # top bit = Huffman flag (ignored)
    return pos + length


def _hpack_str(data, pos):
    huff = data[pos] & 0x80
    length, pos = _hpack_int(data, pos, 7)
    raw = data[pos:pos + length]; pos += length
    if huff:
        return "", pos                        # Huffman literal name: skip (rare)
    return raw.decode("latin1", "replace"), pos


def pseudo_order(block: bytes) -> str:
    """Walk the HPACK header block, collect pseudo-header names in order."""
    pos, n, order = 0, len(block), []
    try:
        while pos < n:
            b = block[pos]
            if b & 0x80:                       # Indexed Header Field (7-bit)
                idx, pos = _hpack_int(block, pos, 7)
                nm = _STATIC.get(idx)
                if nm:
                    order.append(nm)
            elif b & 0x40:                     # Literal w/ Incremental Indexing
                idx, pos = _hpack_int(block, pos, 6)
                nm = (_hpack_str(block, pos)[0] if idx == 0
                      else _STATIC.get(idx, ""))
                if idx == 0:
                    pos = _hpack_skip_str(block, pos)   # literal name
                pos = _hpack_skip_str(block, pos)       # value
                if nm.startswith(":"):
                    order.append(nm)
            elif b & 0x20:                     # Dynamic Table Size Update
                _, pos = _hpack_int(block, pos, 5)
            else:                              # Literal w/o Indexing / Never Idx
                idx, pos = _hpack_int(block, pos, 4)
                nm = (_hpack_str(block, pos)[0] if idx == 0
                      else _STATIC.get(idx, ""))
                if idx == 0:
                    pos = _hpack_skip_str(block, pos)
                pos = _hpack_skip_str(block, pos)
                if nm.startswith(":"):
                    order.append(nm)
    except Exception:
        pass
    return ",".join(_PCODE.get(x, x) for x in order)


def _recv_exactly(sock, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _parse_frames_until_headers(tls) -> dict:
    """Read h2 frames after the preface; capture SETTINGS/WINDOW_UPDATE/PRIORITY
    up to (and including) the client's first HEADERS. Returns fp fields."""
    settings, wu, prio, pseudo = [], 0, 0, ""
    got_client_settings = False
    for _ in range(24):                    # bounded: a normal opener is few frames
        hdr = _recv_exactly(tls, 9)
        if len(hdr) < 9:
            break
        length = int.from_bytes(hdr[0:3], "big")
        ftype, flags = hdr[3], hdr[4]
        stream = int.from_bytes(hdr[5:9], "big") & 0x7fffffff
        payload = _recv_exactly(tls, length) if length else b""
        if ftype == 0x4 and not (flags & 0x1):      # SETTINGS (not ACK)
            for i in range(0, len(payload), 6):
                sid = int.from_bytes(payload[i:i + 2], "big")
                val = int.from_bytes(payload[i + 2:i + 6], "big")
                settings.append((sid, val))
            got_client_settings = True
        elif ftype == 0x8:                           # WINDOW_UPDATE
            inc = int.from_bytes(payload[0:4], "big") & 0x7fffffff
            if stream == 0:
                wu = inc
        elif ftype == 0x2:                           # PRIORITY
            prio += 1
        elif ftype == 0x1:                           # HEADERS = the request
            block = payload
            if flags & 0x8:                          # PADDED: strip pad len + pad
                pad = block[0]
                block = block[1:len(block) - pad]
            if flags & 0x20:                         # PRIORITY: strip 5-byte prio
                block = block[5:]
            pseudo = pseudo_order(block)
            break
    return {"settings": settings, "window_update": wu, "priority": prio,
            "pseudo": pseudo, "got": got_client_settings}


def _fingerprint(f: dict) -> str:
    s = ";".join(f"{sid}:{val}" for sid, val in f["settings"])
    return f"{s}|{f['window_update']}|{f['priority']}|{f['pseudo']}"


# minimal valid h2 server frames
def _frame(ftype, flags, stream, payload=b""):
    return (len(payload).to_bytes(3, "big") + bytes([ftype, flags])
            + stream.to_bytes(4, "big") + payload)


class HTTP2FPServer:
    def __init__(self, host: str = "127.0.0.1"):
        cert, key = ensure_cert()
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.load_cert_chain(cert, key)
        self._ctx.set_alpn_protocols(["h2", "http/1.1"])
        self.last = {"alpn": None, "fp": "", "settings": []}
        self._lock = threading.Lock()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self.base = f"https://{host}:{self.port}"
        self._run = True
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while self._run:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,),
                             daemon=True).start()

    def _handle(self, conn):
        try:
            conn.settimeout(5)
            tls = self._ctx.wrap_socket(conn, server_side=True)
        except Exception:
            try: conn.close()
            except Exception: pass
            return
        alpn = tls.selected_alpn_protocol()
        try:
            if alpn == "h2":
                pre = _recv_exactly(tls, len(PREFACE))       # client preface
                tls.sendall(_frame(0x4, 0, 0))               # server SETTINGS
                f = _parse_frames_until_headers(tls)
                tls.sendall(_frame(0x4, 0x1, 0))             # SETTINGS ACK
                fp = _fingerprint(f)
                with self._lock:
                    self.last = {"alpn": "h2", "fp": fp, "settings": f["settings"]}
                # minimal 200: HEADERS(:status 200) then DATA(END_STREAM)
                tls.sendall(_frame(0x1, 0x4, 1, b"\x88"))
                tls.sendall(_frame(0x0, 0x1, 1, b"ok"))
                tls.sendall(_frame(0x7, 0, 0, b"\x00\x00\x00\x00\x00\x00\x00\x00"))
            else:
                _ = tls.recv(2048)                            # http/1.1 request
                with self._lock:
                    self.last = {"alpn": alpn or "http/1.1",
                                 "fp": "(no h2)", "settings": []}
                body = b"<html><body>http/1.1</body></html>"
                tls.sendall((f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n"
                             f"Connection: close\r\n\r\n").encode() + body)
        except Exception:
            pass
        finally:
            try: tls.close()
            except Exception: pass

    def snapshot(self):
        with self._lock:
            return dict(self.last)

    def stop(self):
        self._run = False
        try: self._sock.close()
        except Exception: pass


# ---------------- the h2 fingerprint race ----------------
def _unverified():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _hit_urllib(url):
    try:
        urllib.request.urlopen(url, timeout=8, context=_unverified()).read()
        return True, ""
    except Exception as e:
        return False, str(e)[:80]


def _hit_curl(url, imp):
    from curl_cffi import requests as cr
    try:
        r = cr.get(url, impersonate=imp, verify=False, timeout=8)
        return r.status_code == 200, ""
    except Exception as e:
        return False, str(e)[:80]


def _hit_scrapling(url):
    from scrapling.fetchers import Fetcher
    for kw in ({"stealthy_headers": True, "verify": False, "timeout": 8},
               {"stealthy_headers": True, "timeout": 8}):
        try:
            Fetcher.get(url, **kw)
            return True, ""
        except TypeError:
            continue
        except Exception as e:
            return False, str(e)[:80]
    return False, "no signature"


STRATEGIES = [
    ("urllib", lambda u: _hit_urllib(u), True),
    ("curl_cffi-plain", lambda u: _hit_curl(u, None), "curl"),
    ("curl_cffi-chrome", lambda u: _hit_curl(u, "chrome"), "curl"),
    ("curl_cffi-safari", lambda u: _hit_curl(u, "safari"), "curl"),
    ("curl_cffi-firefox", lambda u: _hit_curl(u, "firefox"), "curl"),
    ("scrapling", lambda u: _hit_scrapling(u), "scrapling"),
]


def _avail(flag):
    if flag == "curl":
        try: import curl_cffi; return True  # noqa
        except Exception: return False
    if flag == "scrapling":
        try: import scrapling; return True  # noqa
        except Exception: return False
    return True


def http2_race() -> dict:
    srv = HTTP2FPServer()
    rows, skipped = [], []
    try:
        for name, fn, flag in STRATEGIES:
            if not _avail(flag):
                skipped.append(name); continue
            with srv._lock:
                srv.last = {"alpn": None, "fp": "", "settings": []}
            t0 = time.perf_counter()
            ok, err = fn(srv.base + "/")
            ms = (time.perf_counter() - t0) * 1000
            snap = srv.snapshot()
            rows.append({"strategy": name, "h2": snap["alpn"] == "h2",
                         "alpn": snap["alpn"] or "-", "fp": snap["fp"],
                         "n_settings": len(snap["settings"]),
                         "resolved": ok, "ms": round(ms, 1),
                         "error": "" if ok else err})
    finally:
        srv.stop()
    # group by distinct fingerprint
    ranked = sorted(rows, key=lambda r: (not r["h2"], r["strategy"]))
    fps = {}
    for r in rows:
        if r["h2"]:
            fps.setdefault(r["fp"], []).append(r["strategy"])
    return {"stage": "http2", "leaderboard": ranked,
            "distinct_h2_fingerprints": len(fps),
            "fingerprint_groups": fps, "candidates_skipped": skipped}


def format_http2(res: dict) -> str:
    L = [f"http/2 fingerprint race — full Akamai (SETTINGS|WINDOW_UPDATE|"
         f"PRIORITY|PSEUDO_HEADER_ORDER)", "",
         f"  distinct browser h2 fingerprints seen: "
         f"{res['distinct_h2_fingerprints']}", ""]
    hdr = f"{'strategy':18} {'h2':>4} {'ok':>4} {'setts':>6}  fingerprint"
    L += [hdr, "-" * (len(hdr) + 20)]
    for r in res["leaderboard"]:
        h2 = "yes" if r["h2"] else "NO"
        ok = "✓" if r["resolved"] else "✗"
        fp = r["fp"] if len(r["fp"]) < 46 else r["fp"][:44] + "…"
        L.append(f"{r['strategy']:18} {h2:>4} {ok:>4} {r['n_settings']:6d}  {fp}")
    L += ["", "  each distinct fingerprint = a different HTTP/2 stack a WAF can "
          "tell apart:"]
    for fp, who in res["fingerprint_groups"].items():
        L.append(f"    [{', '.join(who)}]  {fp}")
    if res["candidates_skipped"]:
        L += ["", f"skipped: {', '.join(res['candidates_skipped'])}"]
    return "\n".join(L)
