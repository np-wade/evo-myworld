"""hardened.py — a Tier-R target with a REAL anti-bot wall (TLS/JA3), so the
stealth fetchers finally have something to beat.

The owned internal site has no wall, so urllib == curl_cffi == scrapling there.
This server discriminates on the ONE thing curl-impersonate / Scrapling exist to
defeat: the **TLS ClientHello fingerprint (JA3)**. It peeks the raw ClientHello
off the socket (MSG_PEEK, before the handshake consumes it), computes the JA3,
and BLOCKS clients whose fingerprint isn't browser-like.

Block policy = **no GREASE**. Real Chrome/Safari (and curl-impersonate, which
mimics them) inject GREASE values (0x?a?a) into ciphers/extensions per RFC 8701;
stock Python `ssl`/OpenSSL and plain libcurl do NOT. So:
  urllib (Python OpenSSL JA3)           -> no GREASE -> 403 BLOCKED
  curl_cffi impersonate=chrome/safari   -> GREASE    -> 200 RESOLVED
That is exactly the stealth capability we could never measure before.

Everything is localhost + a self-signed cert (clients fetch with verify off), so
the ONLY discriminator is the fingerprint, never cert trust. Pure stdlib + openssl
for the one-time cert. JA3 hash = md5(SSLVer,Ciphers,Exts,Curves,PointFormats).
"""
from __future__ import annotations

import hashlib
import socket
import ssl
import subprocess
import threading
from collections import Counter
from pathlib import Path

FIX = Path(__file__).parent.parent / "fixtures"
CERT_DIR = FIX / "hardened"


def ensure_cert() -> tuple[Path, Path]:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    cert, key = CERT_DIR / "cert.pem", CERT_DIR / "key.pem"
    if not (cert.exists() and key.exists()):
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(key), "-out", str(cert), "-days", "3650",
             "-subj", "/CN=127.0.0.1",
             "-addext", "subjectAltName=IP:127.0.0.1"],
            check=True, capture_output=True)
    return cert, key


def _is_grease(v: int) -> bool:
    # GREASE (RFC 8701): 0x0a0a,0x1a1a,...,0xfafa — high byte==low byte, nibble a
    return (v >> 8) == (v & 0xff) and (v & 0x0f) == 0x0a


def parse_ja3(data: bytes) -> dict | None:
    """Parse a TLS ClientHello record -> JA3 fields. None if not a ClientHello."""
    try:
        if len(data) < 6 or data[0] != 0x16:      # not a TLS handshake record
            return None
        hs = data[5:]
        if not hs or hs[0] != 0x01:                # not a ClientHello
            return None
        p = 4                                       # skip hs type(1)+len(3)
        ver = int.from_bytes(hs[p:p + 2], "big"); p += 2
        p += 32                                     # random
        sid_len = hs[p]; p += 1 + sid_len
        cs_len = int.from_bytes(hs[p:p + 2], "big"); p += 2
        ciphers = [int.from_bytes(hs[p + i:p + i + 2], "big")
                   for i in range(0, cs_len, 2)]; p += cs_len
        comp_len = hs[p]; p += 1 + comp_len
        exts, curves, pfmts = [], [], []
        alpn_h2 = False
        if p + 2 <= len(hs):
            ext_total = int.from_bytes(hs[p:p + 2], "big"); p += 2
            end = min(p + ext_total, len(hs))
            while p + 4 <= end:
                et = int.from_bytes(hs[p:p + 2], "big")
                el = int.from_bytes(hs[p + 2:p + 4], "big"); p += 4
                ed = hs[p:p + el]; p += el
                exts.append(et)
                if et == 0x000a and len(ed) >= 2:               # supported_groups
                    gl = int.from_bytes(ed[0:2], "big")
                    curves = [int.from_bytes(ed[2 + i:4 + i], "big")
                              for i in range(0, gl, 2)]
                elif et == 0x000b and ed:                        # ec_point_formats
                    pfmts = list(ed[1:1 + ed[0]])
                elif et == 0x0010:                               # ALPN
                    alpn_h2 = b"h2" in ed
        cf = [c for c in ciphers if not _is_grease(c)]
        ef = [e for e in exts if not _is_grease(e)]
        cvf = [c for c in curves if not _is_grease(c)]
        ja3 = (f"{ver},{'-'.join(map(str, cf))},{'-'.join(map(str, ef))},"
               f"{'-'.join(map(str, cvf))},{'-'.join(map(str, pfmts))}")
        has_grease = any(_is_grease(c) for c in ciphers) or \
            any(_is_grease(e) for e in exts)
        return {"ja3": ja3, "hash": hashlib.md5(ja3.encode()).hexdigest(),
                "has_grease": has_grease, "alpn_h2": alpn_h2,
                "n_ciphers": len(ciphers), "n_exts": len(exts)}
    except Exception:
        return None


class HardenedServer:
    """HTTPS server that 403s any client whose TLS fingerprint lacks GREASE."""
    def __init__(self, host: str = "127.0.0.1", require_grease: bool = True,
                 js_challenge: bool = False):
        cert, key = ensure_cert()
        self.require_grease = require_grease
        self.js_challenge = js_challenge
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.load_cert_chain(cert, key)
        self._ctx.set_alpn_protocols(["http/1.1"])
        self._hits: Counter = Counter()
        self._blocks = 0
        self._lock = threading.Lock()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self.base = f"https://{host}:{self.port}"
        self._run = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while self._run:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,),
                             daemon=True).start()

    def _handle(self, conn: socket.socket):
        ja3 = None
        try:
            conn.settimeout(5)
            peek = conn.recv(8192, socket.MSG_PEEK)   # ClientHello, unconsumed
            ja3 = parse_ja3(peek)
            tls = self._ctx.wrap_socket(conn, server_side=True)
        except Exception:
            try: conn.close()
            except Exception: pass
            return
        try:
            req = tls.recv(4096).decode("latin1", "replace")
            path = "/"
            if req.startswith("GET"):
                path = req.split(" ", 2)[1]
            allowed = (ja3 is not None and
                       (ja3["has_grease"] or not self.require_grease))
            with self._lock:
                self._hits[path] += 1
                if not allowed:
                    self._blocks += 1
            hdr = (f"X-JA3-Hash: {ja3['hash'] if ja3 else 'none'}\r\n"
                   f"X-JA3-Grease: {int(ja3['has_grease']) if ja3 else 0}\r\n"
                   f"X-JA3-ALPN-h2: {int(ja3['alpn_h2']) if ja3 else 0}\r\n")
            if allowed and self.js_challenge:
                # Cloudflare-style: the content link exists ONLY after JS runs.
                # The path is assembled from fragments in JS (no literal in the
                # raw HTML), so a regex can't shortcut it — only real execution
                # reveals it. A stealth fetcher passes JA3 but stalls here.
                if path.split("?")[0] == "/human-only":
                    body = (b"<html><title>Human verified</title><body>"
                            b"<h1>SOLVED - you executed the challenge JS</h1>"
                            b"</body></html>")
                else:
                    body = (
                        "<!DOCTYPE html><html><head><title>Just a moment..."
                        "</title></head><body><h1>Checking your browser before "
                        "you continue...</h1><div id='c'>Verifying...</div>"
                        "<script>var a=7,b=35;var tok=(a*b).toString(36);"
                        "var p=['/hu','man','-on','ly'].join('');"
                        "document.getElementById('c').innerHTML="
                        "\"<a href='\"+p+\"?t=\"+tok+\"'>continue</a>\";"
                        "</script></body></html>").encode()
                resp = (f"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                        f"Content-Length: {len(body)}\r\n{hdr}"
                        f"Connection: close\r\n\r\n").encode() + body
            elif allowed:
                body = (f"<html><title>Protected {path}</title><body>"
                        f"<h1>Protected resource {path}</h1>"
                        f"<p>You passed the bot wall.</p></body></html>").encode()
                resp = (f"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                        f"Content-Length: {len(body)}\r\n{hdr}"
                        f"Connection: close\r\n\r\n").encode() + body
            else:
                body = b"<html><body><h1>403 - bot detected (TLS fingerprint)" \
                       b"</h1></body></html>"
                resp = (f"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\n"
                        f"Content-Length: {len(body)}\r\n{hdr}"
                        f"Connection: close\r\n\r\n").encode() + body
            tls.sendall(resp)
        except Exception:
            pass
        finally:
            try: tls.close()
            except Exception: pass

    def stats(self) -> dict:
        with self._lock:
            return {"requests": sum(self._hits.values()), "blocks": self._blocks}

    def stop(self):
        self._run = False
        try: self._sock.close()
        except Exception: pass


if __name__ == "__main__":
    import time
    s = HardenedServer()
    print(f"hardened target on {s.base} (JA3 wall: no-GREASE -> 403)")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        s.stop()
