"""site_server — serve the authored internal site on a local port.

Deterministic, offline, in-process. The server strips query strings (so
/products?ref=home serves the /products file — the duplicate trap), serves
robots.txt and catalog.js, and keeps an independent HIT LOG so the grader can
count real requests and detect robots violations WITHOUT trusting a candidate's
self-report.

  srv = SiteServer()            # binds a free port, starts a background thread
  srv.base                      # -> "http://127.0.0.1:<port>"
  srv.reset()                   # clear the hit log before a run
  srv.hits()                    # -> {path: count}
  srv.forbidden_hits()          # -> [paths fetched that robots disallowed]
  srv.stop()
"""
from __future__ import annotations

import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import site_spec as S

FIX = Path(__file__).parent.parent / "fixtures" / "site1"

_CTYPE = {".html": "text/html; charset=utf-8", ".js": "application/javascript",
          ".txt": "text/plain; charset=utf-8", ".json": "application/json"}


def _disallowed(path: str) -> bool:
    return any(path.startswith(pre) for pre in S.ROBOTS_DISALLOW)


def _maze_page(node_id: int, maze_max: int, fanout: int = 3) -> bytes:
    """Synthesize an endurance-maze node on the fly: a deterministic, effectively
    endless graph. Node N links to fanout children plus a deep 'next' chain and
    the root, so a crawler can 'keep looking around' for as long as its own
    budget allows. Distinct keyword per node so extract/index stay meaningful."""
    kids = [node_id * fanout + i for i in range(1, fanout + 1)]
    kids = [k for k in kids if k < maze_max]
    nxt = node_id + 1 if node_id + 1 < maze_max else None
    links = [f"/maze/{k}" for k in kids]
    if nxt is not None:
        links.append(f"/maze/{nxt}")
    links.append("/maze/0")
    body = (f"<!DOCTYPE html><html><head><title>Maze node {node_id}</title></head>"
            f"<body><h1>Maze node {node_id}</h1>"
            f"<p>Endurance maze node number {node_id} keyword-{node_id}. "
            f"Follow the links to keep crawling.</p><nav>"
            + "".join(f"<a href='{l}'>{l}</a>" for l in links)
            + "</nav></body></html>")
    return body.encode()


class SiteServer:
    def __init__(self, host: str = "127.0.0.1", maze_max: int = 1_000_000):
        self.routes: dict[str, str] = json.loads(
            (FIX / "routes.json").read_text())
        self.maze_max = maze_max
        self._hits: Counter = Counter()
        self._lock = threading.Lock()
        server_self = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence stderr spam
                pass

            def do_GET(self):
                split = urlsplit(self.path)
                path = split.path
                if path == "/__hits__":
                    return self._json(dict(server_self._hits))
                if path == "/__reset__":
                    server_self.reset()
                    return self._json({"ok": True})
                # record the request exactly as asked (query preserved for dedup
                # analysis; forbidden-detection uses the bare path).
                with server_self._lock:
                    server_self._hits[self.path] += 1
                # endurance maze: synthesized on the fly (/maze, /maze/<id>)
                if path == "/maze" or path.startswith("/maze/"):
                    tail = path[len("/maze"):].strip("/")
                    try:
                        nid = int(tail) if tail else 0
                    except ValueError:
                        return self._err(404, "bad maze id")
                    if not (0 <= nid < server_self.maze_max):
                        return self._err(404, "maze out of range")
                    body = _maze_page(nid, server_self.maze_max)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                # query-stripped lookup -> duplicate URLs collapse to canonical
                rel = server_self.routes.get(self.path) or \
                    server_self.routes.get(path)
                if not rel:
                    return self._err(404, "not found")
                fp = FIX / rel
                if not fp.exists():
                    return self._err(404, "missing file")
                body = fp.read_bytes()
                ct = _CTYPE.get(fp.suffix, "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj):
                b = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _err(self, code, msg):
                b = msg.encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self._srv = ThreadingHTTPServer((host, 0), Handler)
        self.port = self._srv.server_address[1]
        self.base = f"http://{host}:{self.port}"
        self._thread = threading.Thread(target=self._srv.serve_forever,
                                        daemon=True)
        self._thread.start()

    def reset(self):
        with self._lock:
            self._hits.clear()

    def hits(self) -> dict[str, int]:
        with self._lock:
            return dict(self._hits)

    def request_count(self) -> int:
        with self._lock:
            return sum(self._hits.values())

    def forbidden_hits(self) -> list[str]:
        with self._lock:
            seen = list(self._hits)
        return sorted({urlsplit(p).path for p in seen
                       if _disallowed(urlsplit(p).path)})

    def stop(self):
        self._srv.shutdown()
        self._srv.server_close()


if __name__ == "__main__":
    import time
    s = SiteServer()
    print(f"serving {s.base} — try {s.base}/ and {s.base}/robots.txt")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        s.stop()
