"""Fetch backends the discovery candidates scrape THROUGH — normal scraping only.

Each backend is available()-gated: a missing dep or unreachable service makes a
candidate SKIP, never crash (scrapler-eval convention). No arXiv API here.

Backends:
  urllib      -- stdlib baseline (no stealth). Gets 429/403 on hardened targets.
  curl_cffi   -- TLS/JA3 impersonation (curl-impersonate engine). The stealth path.
  scrapling   -- Scrapling static fetch, if installed.
"""
from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass, field

DESKTOP_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


@dataclass
class FetchOut:
    ok: bool
    status: int = 0
    text: str = ""
    blocked: bool = False        # 403/429/challenge page
    latency_ms: float = 0.0
    bytes_down: int = 0
    error: str = ""
    content: bytes = b""         # raw body (needed for binary targets like PDFs)


def _blocked(status: int, text: str) -> bool:
    if status in (403, 429, 503):
        return True
    low = text[:2000].lower()
    # arXiv soft-throttle: HTTP 200 with a bare "Rate exceeded." body
    if len(text) < 200 and "rate exceeded" in low:
        return True
    return any(s in low for s in ("captcha", "are you a robot",
                                  "verify you are human", "access denied"))


class Backend:
    name = "base"
    def available(self) -> bool: return False
    def get(self, url: str, timeout: int = 30) -> FetchOut: ...


class UrllibBackend(Backend):
    name = "urllib"
    def available(self) -> bool: return True
    def get(self, url: str, timeout: int = 30) -> FetchOut:
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": DESKTOP_UA})
            r = urllib.request.urlopen(req, timeout=timeout)
            body = r.read()
            txt = body.decode("utf-8", "replace")
            dt = (time.perf_counter() - t0) * 1000
            return FetchOut(True, r.status, txt, _blocked(r.status, txt), dt,
                            len(body), content=body)
        except urllib.error.HTTPError as e:
            dt = (time.perf_counter() - t0) * 1000
            body = ""
            try: body = e.read().decode("utf-8", "replace")
            except Exception: pass
            return FetchOut(False, e.code, body, _blocked(e.code, body), dt,
                            len(body), error=f"HTTP {e.code}")
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000
            return FetchOut(False, 0, "", False, dt, 0, error=str(e))


class CurlCffiBackend(Backend):
    name = "curl_cffi"
    def available(self) -> bool:
        try:
            import curl_cffi  # noqa: F401
            return True
        except Exception:
            return False
    def get(self, url: str, timeout: int = 30) -> FetchOut:
        from curl_cffi import requests as cr
        t0 = time.perf_counter()
        try:
            r = cr.get(url, impersonate="chrome", timeout=timeout)
            dt = (time.perf_counter() - t0) * 1000
            txt = r.text
            return FetchOut(True, r.status_code, txt,
                            _blocked(r.status_code, txt), dt, len(r.content),
                            content=r.content)
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000
            return FetchOut(False, 0, "", False, dt, 0, error=str(e))


class ScraplingBackend(Backend):
    name = "scrapling"
    def available(self) -> bool:
        try:
            import scrapling  # noqa: F401
            return True
        except Exception:
            return False
    def get(self, url: str, timeout: int = 30) -> FetchOut:
        from scrapling.fetchers import Fetcher
        t0 = time.perf_counter()
        try:
            page = Fetcher.get(url, stealthy_headers=True, timeout=timeout)
            dt = (time.perf_counter() - t0) * 1000
            txt = getattr(page, "html_content", "") or str(page)
            st = getattr(page, "status", 200)
            body = getattr(page, "body", b"") or txt.encode()
            if isinstance(body, str):
                body = body.encode()
            return FetchOut(True, st, txt, _blocked(st, txt), dt, len(body),
                            content=body)
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000
            return FetchOut(False, 0, "", False, dt, 0, error=str(e))


ALL_BACKENDS = [UrllibBackend(), CurlCffiBackend(), ScraplingBackend()]


def available_backends() -> list[Backend]:
    return [b for b in ALL_BACKENDS if b.available()]
