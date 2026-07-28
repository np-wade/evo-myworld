"""Static fetch backends — normal scraping, no JS execution.

Same available()-gated shape as the sibling evals: a missing dep makes the
candidate SKIP, never crash. These fetch RAW HTML only — so they structurally
CANNOT see the JS-injected /item links (that's the point of the JS-nav trap).

  urllib     -- stdlib baseline
  curl_cffi  -- TLS/JA3 impersonation (curl-impersonate engine)
  scrapling  -- Scrapling static fetch, if installed
"""
from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass

DESKTOP_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


@dataclass
class FetchOut:
    ok: bool
    status: int = 0
    text: str = ""
    latency_ms: float = 0.0
    error: str = ""


class Backend:
    name = "base"
    def available(self) -> bool: return False
    def get(self, url: str, timeout: int = 15) -> FetchOut: ...


class UrllibBackend(Backend):
    name = "urllib"
    def available(self) -> bool: return True
    def get(self, url: str, timeout: int = 15) -> FetchOut:
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": DESKTOP_UA})
            r = urllib.request.urlopen(req, timeout=timeout)
            txt = r.read().decode("utf-8", "replace")
            return FetchOut(True, r.status, txt,
                            (time.perf_counter() - t0) * 1000)
        except urllib.error.HTTPError as e:
            return FetchOut(False, e.code, "", (time.perf_counter() - t0) * 1000,
                            error=f"HTTP {e.code}")
        except Exception as e:
            return FetchOut(False, 0, "", (time.perf_counter() - t0) * 1000,
                            error=str(e))


class CurlCffiBackend(Backend):
    name = "curl_cffi"
    def available(self) -> bool:
        try:
            import curl_cffi  # noqa: F401
            return True
        except Exception:
            return False
    def get(self, url: str, timeout: int = 15) -> FetchOut:
        from curl_cffi import requests as cr
        t0 = time.perf_counter()
        try:
            r = cr.get(url, impersonate="chrome", timeout=timeout)
            return FetchOut(True, r.status_code, r.text,
                            (time.perf_counter() - t0) * 1000)
        except Exception as e:
            return FetchOut(False, 0, "", (time.perf_counter() - t0) * 1000,
                            error=str(e))


class ScraplingBackend(Backend):
    name = "scrapling"
    def available(self) -> bool:
        try:
            import scrapling  # noqa: F401
            return True
        except Exception:
            return False
    def get(self, url: str, timeout: int = 15) -> FetchOut:
        from scrapling.fetchers import Fetcher
        t0 = time.perf_counter()
        try:
            page = Fetcher.get(url, stealthy_headers=True, timeout=timeout)
            txt = getattr(page, "html_content", "") or str(page)
            st = getattr(page, "status", 200)
            return FetchOut(True, st, txt, (time.perf_counter() - t0) * 1000)
        except Exception as e:
            return FetchOut(False, 0, "", (time.perf_counter() - t0) * 1000,
                            error=str(e))


ALL_BACKENDS = [UrllibBackend(), CurlCffiBackend(), ScraplingBackend()]


def backend_by_name(name: str) -> Backend:
    for b in ALL_BACKENDS:
        if b.name == name:
            return b
    raise KeyError(name)


def available_backends() -> list[Backend]:
    return [b for b in ALL_BACKENDS if b.available()]
