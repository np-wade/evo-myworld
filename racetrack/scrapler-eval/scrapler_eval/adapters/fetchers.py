"""Class-1 (no-JS) fetcher adapters — TLS/JA3 impersonation lineage.

Two Candidate subclasses, weight_class = WeightClass.FETCHER:

- CurlImpersonateFetch (name="curl-impersonate"): wraps curl-impersonate via the
  `curl_cffi` library's requests-like API (`curl_cffi.requests.get(url,
  impersonate="chrome124", ...)`). curl-impersonate patches curl+BoringSSL so the
  TLS ClientHello / JA3 fingerprint matches a real Chrome, defeating TLS-level
  bot walls that a plain urllib/httpx fetch trips.
    Donor: lwthiker/curl-impersonate
      /home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/lwthiker_curl-impersonate/code
      README.md documents the impersonation targets (chrome, edge, safari, ff);
      the Python entrypoint is the `curl_cffi` binding (requests-compatible
      `get`/`Session`, `impersonate=` selects the ClientHello profile).

- ScraplingStaticFetch (name="scrapling-static"): wraps Scrapling's *static*
  HTTP fetcher (`scrapling.fetchers.Fetcher.get`), which is itself built on
  `curl_cffi` with stealthy browser headers and returns a unified `Response`.
    Donor: D4Vinci/Scrapling
      /home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/D4Vinci_Scrapling/scrapling/fetchers/requests.py
        -> `Fetcher.get(url, **kwargs) -> Response` (delegates to FetcherClient)
      /home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/D4Vinci_Scrapling/scrapling/engines/static.py
        -> `FetcherSession.get` uses `curl_cffi.requests` with `impersonate=`
      /home/npwad/coding/docker-envs/filing-cabinet/library-base/repos/D4Vinci_Scrapling/scrapling/engines/toolbelt/custom.py
        -> `Response(status=..., body=bytes, ...)`; `.status`, `.body`.

available()/offline policy (documented per build brief)
-------------------------------------------------------
The harness fixtures are `file://` URLs, which need **zero** third-party deps:
we just read the file and strip tags. The LIVE (http/https) path needs the
scraper dep. Rather than skip these candidates on a box without curl_cffi/
scrapling (which would drop them from every frozen-tier race), both adapters set
`works_offline = True` and `available()` returns **True always** — the file://
path always works. Inside the *live* branch, if the dep is missing we return a
clean `FetchResult(ok=False, blocked=False, error="<dep> not installed")` instead
of crashing (Hard rule #4: missing deps are recorded, never crash the race).
`requires` still lists the dep so `list`/provenance report what the LIVE path
wants. The live network call is funnelled through a module-level `_live_*` helper
so tests can monkeypatch it (or sys.modules) with no network.
"""

from __future__ import annotations

import html as htmlmod
import re
import time
from pathlib import Path

from ..interface import Candidate, FetchResult, Task, WeightClass

# --- pure-stdlib tag stripping (local, reused by both adapters) ---------------
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_SCRIPT_STYLE = re.compile(r"<(script|style|template)[^>]*>.*?</\1>", re.S | re.I)

# Challenge / interstitial markers a no-JS fetch sees when a wall bounces it.
_CHALLENGE_MARKERS = (
    "cf-challenge",
    "cf-browser-verification",
    "just a moment",
    "checking your browser",
    "attention required",
    "enable javascript and cookies to continue",
    "px-captcha",
    "/cdn-cgi/challenge-platform",
)
_BLOCK_STATUSES = (401, 403, 429, 503)


def _strip_to_text(html: str) -> str:
    """HTML -> visible text (pure stdlib). Drops <script>/<style>/<template>
    bodies first so their contents don't leak into the text axis, then removes
    remaining tags and collapses whitespace."""
    doc = _SCRIPT_STYLE.sub(" ", html)
    doc = _TAG.sub(" ", doc)
    return _WS.sub(" ", htmlmod.unescape(doc)).strip()


def _is_blocked(status: int, body: str) -> bool:
    if status in _BLOCK_STATUSES:
        return True
    low = body.lower()
    return any(m in low for m in _CHALLENGE_MARKERS)


def _read_file_url(url: str) -> str:
    return Path(url[len("file://"):]).read_text(encoding="utf-8")


def _file_result(url: str, t0: float) -> FetchResult:
    """Shared file:// path: read fixture, strip, return. Zero third-party deps."""
    try:
        html = _read_file_url(url)
    except Exception as exc:  # unreadable fixture is a fetch failure, not a crash
        return FetchResult(ok=False, error=str(exc), blocked=False,
                           latency_ms=(time.perf_counter() - t0) * 1000)
    text = _strip_to_text(html)
    return FetchResult(
        ok=True, html=html, text=text, status=200,
        blocked=_is_blocked(200, html),
        latency_ms=(time.perf_counter() - t0) * 1000,
        bytes_down=len(html.encode("utf-8")),
    )


# --- live-call indirections (import the dep lazily; tests monkeypatch these) ---
def _live_curl_fetch(url: str, timeout: float):
    """LIVE curl-impersonate call. Imports curl_cffi lazily (ImportError if the
    dep is absent). Returns the requests-like response (`.status_code`, `.text`,
    `.content`). Isolated so tests can replace it / sys.modules with a fake."""
    import curl_cffi.requests as creq  # noqa: WPS433 (lazy heavy dep)

    return creq.get(url, impersonate="chrome124", timeout=timeout)


def _live_scrapling_fetch(url: str, timeout: float):
    """LIVE Scrapling static call, faithful to the repo: `Fetcher.get(url)`,
    which drives curl_cffi with stealthy browser headers and returns a unified
    `Response` (`.status`, `.body`). Imported lazily; tests can fake it."""
    from scrapling.fetchers import Fetcher  # noqa: WPS433 (lazy heavy dep)

    return Fetcher.get(url, timeout=timeout, stealthy_headers=True)


class CurlImpersonateFetch(Candidate):
    """No-JS fetch with a real-Chrome TLS/JA3 fingerprint via curl-impersonate
    (`curl_cffi`, impersonate="chrome124")."""

    name = "curl-impersonate"
    weight_class = WeightClass.FETCHER
    requires: list[str] = ["curl_cffi"]
    works_offline = True  # file:// path needs no third-party dep

    def available(self) -> bool:
        # True always: the file:// fixture path needs nothing. The live branch
        # self-reports a missing dep (see module docstring).
        return True

    def fetch(self, task: Task) -> FetchResult:
        t0 = time.perf_counter()
        if task.url.startswith("file://"):
            return _file_result(task.url, t0)

        try:
            resp = _live_curl_fetch(task.url, timeout=self._timeout(task))
        except ImportError:
            return FetchResult(ok=False, blocked=False,
                               error="curl_cffi not installed",
                               latency_ms=(time.perf_counter() - t0) * 1000)
        except Exception as exc:
            return FetchResult(ok=False, error=str(exc), blocked=False,
                               latency_ms=(time.perf_counter() - t0) * 1000)

        status = int(getattr(resp, "status_code", 0) or 0)
        body = getattr(resp, "text", "") or ""
        raw = getattr(resp, "content", None)
        bytes_down = len(raw) if raw is not None else len(body.encode("utf-8"))
        return FetchResult(
            ok=True, html=body, text=_strip_to_text(body), status=status,
            blocked=_is_blocked(status, body),
            latency_ms=(time.perf_counter() - t0) * 1000,
            bytes_down=bytes_down,
        )

    @staticmethod
    def _timeout(task: Task) -> float:
        return float(task.meta.get("timeout", 20))


class ScraplingStaticFetch(Candidate):
    """Scrapling's static HTTP fetcher (`scrapling.fetchers.Fetcher.get`) — a
    curl_cffi-backed no-JS fetch with stealthy browser headers."""

    name = "scrapling-static"
    weight_class = WeightClass.FETCHER
    requires: list[str] = ["scrapling"]
    works_offline = True  # file:// path needs no third-party dep

    def available(self) -> bool:
        return True

    def fetch(self, task: Task) -> FetchResult:
        t0 = time.perf_counter()
        if task.url.startswith("file://"):
            return _file_result(task.url, t0)

        try:
            resp = _live_scrapling_fetch(task.url, timeout=self._timeout(task))
        except ImportError:
            return FetchResult(ok=False, blocked=False,
                               error="scrapling not installed",
                               latency_ms=(time.perf_counter() - t0) * 1000)
        except Exception as exc:
            return FetchResult(ok=False, error=str(exc), blocked=False,
                               latency_ms=(time.perf_counter() - t0) * 1000)

        status = int(getattr(resp, "status", 0) or 0)
        body = self._body_text(resp)
        return FetchResult(
            ok=True, html=body, text=_strip_to_text(body), status=status,
            blocked=_is_blocked(status, body),
            latency_ms=(time.perf_counter() - t0) * 1000,
            bytes_down=len(body.encode("utf-8")),
        )

    @staticmethod
    def _body_text(resp) -> str:
        """Scrapling Response exposes `.body` (str|bytes); fall back to str()."""
        body = getattr(resp, "body", None)
        if body is None:
            body = getattr(resp, "html_content", "") or ""
        if isinstance(body, bytes):
            return body.decode("utf-8", "replace")
        return str(body)

    @staticmethod
    def _timeout(task: Task) -> float:
        return float(task.meta.get("timeout", 20))


# Bulk-registered by adapters._autodiscover() via this module-level list.
CANDIDATES = [CurlImpersonateFetch, ScraplingStaticFetch]
