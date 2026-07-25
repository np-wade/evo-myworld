"""Class-2 (stealth browser) candidates — the RAM-cost axis of the ladder.

These wrap real browser stacks faithfully to how each donor repo drives them.
None of their deps (nor the browser binaries they need) are assumed present on
this box: every adapter gates on `available()`, and a missing dep means the
harness records the candidate as *skipped*, never crashed. That skipped-state is
the EXPECTED common case here — a headless box with no browser binary.

For `file://` fixtures a render is meaningless, so we just read the file, strip
it to text, and tag `artifacts={"rendered": False}` — enough for the harness to
exercise the adapter deterministically without a browser. For live URLs each
adapter drives its donor's real API: navigate → wait for network idle →
`page.content()` → optional cheap screenshot.

Donor lineage (exact files read to wrap each faithfully):
- playwright-baseline  -> microsoft_playwright/code (playwright.sync_api; the
  chromium launch/new_page/goto/content pattern; the browser we try to beat).
- invisible-playwright -> feder-cr_invisible_playwright/code/src/invisible_playwright/
  launcher.py (`class InvisiblePlaywright` context-manager yielding a patched
  Firefox `Browser`; examples/basic.py for the new_page/goto/title flow).
- camofox              -> jo-inc_camofox-browser/code/README.md (Camoufox
  hardened-Firefox server) + the upstream `camoufox` python pkg's
  `camoufox.sync_api.Camoufox` context manager.
- cloakbrowser         -> cloakhq_cloakbrowser/code/examples/basic.py &
  cloakbrowser/browser.py (`from cloakbrowser import launch` -> Playwright
  Browser; launch/new_page/goto/content/close).
- scrapling-patchright -> D4Vinci_Scrapling/scrapling/fetchers/chrome.py
  (`DynamicFetcher.fetch(url, headless=, network_idle=)` -> Response) and
  scrapling/engines/toolbelt/custom.py::Response (.status/.body/.html_content)
  + parser.py (.get_all_text/.html_content). This is Scrapling's DYNAMIC mode.
"""

from __future__ import annotations

import resource
import tempfile
import time
from pathlib import Path

from ..interface import Candidate, FetchResult, Task, WeightClass
from .baseline import strip_to_text

# Screenshots (live only) land in a throwaway tmp dir, never in the repo.
_SHOT_DIR = Path(tempfile.gettempdir()) / "scrapler_eval_shots"

# Challenge / block markers — substring match against html+text, case-folded.
_BLOCK_MARKERS = (
    "just a moment",
    "checking your browser",
    "cf-chl",
    "cf-challenge",
    "attention required",
    "cloudflare",
    "access denied",
    "verifying you are human",
    "enable javascript and cookies",
    "ddos protection",
    "please enable cookies",
    "captcha",
    "ray id",
)


def _peak_rss_mb() -> float:
    """Best-effort peak RSS in MB. On Linux ru_maxrss is KB (this box is WSL)."""
    kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(kb / 1024.0, 1)


def _looks_blocked(html: str, text: str) -> bool:
    blob = f"{html}\n{text}".lower()
    return any(m in blob for m in _BLOCK_MARKERS)


class _BrowserFetch(Candidate):
    """Shared class-2 plumbing: file:// short-circuit, live driver, timing/RSS.

    Subclasses set `name`, `requires`, `_import_name`, and implement
    `_live_fetch(task)` returning a FetchResult (latency/RSS are stamped here)."""

    weight_class = WeightClass.BROWSER
    requires: list[str] = []
    _import_name: str = ""

    def available(self) -> bool:
        """True iff the donor package imports. Note: importing the wrapper does
        NOT prove the browser binary is installed, so a True here can still fail
        at fetch() on a box without the binary. On this headless box the import
        itself is absent, so every class-2 adapter reports False and is skipped."""
        try:
            __import__(self._import_name)
            return True
        except Exception:
            return False

    # --- file:// fixtures: no render, just read + strip (deterministic) --------
    def _file_fetch(self, task: Task) -> FetchResult:
        html = Path(task.url[len("file://"):]).read_text(encoding="utf-8")
        text = strip_to_text(html, keep_hidden=True)
        return FetchResult(
            ok=True, html=html, text=text, status=200,
            blocked=_looks_blocked(html, text),
            bytes_down=len(html.encode("utf-8")),
            artifacts={"rendered": False, "detector_pass": None},
        )

    # --- live: subclasses drive their donor browser ----------------------------
    def _live_fetch(self, task: Task) -> FetchResult:  # pragma: no cover - needs browser
        raise NotImplementedError(f"{self.name} has no live driver")

    def fetch(self, task: Task) -> FetchResult:
        t0 = time.perf_counter()
        try:
            if task.url.startswith("file://"):
                res = self._file_fetch(task)
            else:
                res = self._live_fetch(task)
        except Exception as exc:  # a browser blowup is a recorded miss, never a crash
            res = FetchResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        res.latency_ms = (time.perf_counter() - t0) * 1000
        if not res.peak_rss_mb:
            res.peak_rss_mb = _peak_rss_mb()
        return res

    # --- helpers shared by the Playwright-API donors (all but scrapling) -------
    def _screenshot(self, page) -> str | None:
        """Cheap screenshot into a tmp dir; None if the page can't shoot."""
        shot_fn = getattr(page, "screenshot", None)
        if not callable(shot_fn):
            return None
        try:
            _SHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = str(_SHOT_DIR / f"{self.name}-{int(time.time() * 1000)}.png")
            shot_fn(path=path)
            return path
        except Exception:
            return None

    def _page_to_result(self, page, resp, task: Task) -> FetchResult:
        """Map a Playwright-style page + response onto a FetchResult."""
        html = page.content()
        text = strip_to_text(html, keep_hidden=False)  # a browser shows rendered text
        status = getattr(resp, "status", 0) or 0
        blocked = _looks_blocked(html, text)
        artifacts: dict = {"rendered": True, "detector_pass": None}
        shot = self._screenshot(page)
        if shot:
            artifacts["screenshot"] = shot
        return FetchResult(
            ok=True, html=html, text=text,
            status=status or (200 if html else 0),
            blocked=blocked,
            bytes_down=len(html.encode("utf-8")),
            artifacts=artifacts,
        )


class PlaywrightFetch(_BrowserFetch):
    """The baseline browser — vanilla Playwright chromium. The thing to beat.
    Donor: microsoft_playwright/code (playwright.sync_api)."""

    name = "playwright-baseline"
    requires = ["playwright"]
    _import_name = "playwright"

    def _live_fetch(self, task: Task) -> FetchResult:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                resp = page.goto(task.url, wait_until="networkidle", timeout=30000)
                return self._page_to_result(page, resp, task)
            finally:
                browser.close()


class InvisiblePlaywrightFetch(_BrowserFetch):
    """Patched Firefox with a randomized stealth fingerprint profile.
    Donor: feder-cr_invisible_playwright (InvisiblePlaywright context manager)."""

    name = "invisible-playwright"
    requires = ["invisible-playwright"]
    _import_name = "invisible_playwright"

    def _live_fetch(self, task: Task) -> FetchResult:
        from invisible_playwright import InvisiblePlaywright

        # The context manager yields a patched Firefox Browser (see launcher.py).
        with InvisiblePlaywright(headless=True) as browser:
            page = browser.new_page()
            resp = page.goto(task.url, wait_until="networkidle", timeout=30000)
            return self._page_to_result(page, resp, task)


class CamofoxFetch(_BrowserFetch):
    """Camoufox — a Firefox fork with C++-level fingerprint spoofing.
    Donor: jo-inc_camofox-browser + upstream `camoufox` python pkg
    (camoufox.sync_api.Camoufox context manager)."""

    name = "camofox"
    requires = ["camoufox"]
    _import_name = "camoufox"

    def _live_fetch(self, task: Task) -> FetchResult:
        from camoufox.sync_api import Camoufox

        with Camoufox(headless=True) as browser:
            page = browser.new_page()
            resp = page.goto(task.url, wait_until="networkidle", timeout=30000)
            return self._page_to_result(page, resp, task)


class CloakBrowserFetch(_BrowserFetch):
    """CloakBrowser — anti-detect Chromium patched at the source level, driven
    over the Playwright API. Donor: cloakhq_cloakbrowser (`launch()` -> Browser)."""

    name = "cloakbrowser"
    requires = ["cloakbrowser"]
    _import_name = "cloakbrowser"

    def _live_fetch(self, task: Task) -> FetchResult:
        from cloakbrowser import launch

        browser = launch(headless=True)
        try:
            page = browser.new_page()
            resp = page.goto(task.url, wait_until="networkidle", timeout=30000)
            return self._page_to_result(page, resp, task)
        finally:
            browser.close()


class ScraplingDynamicFetch(_BrowserFetch):
    """Scrapling's DYNAMIC mode — chromium automation with patchright/zendriver
    escalation, exposed through DynamicFetcher. Donor: D4Vinci_Scrapling
    (scrapling.fetchers.DynamicFetcher; Response.status/.html_content/.get_all_text)."""

    name = "scrapling-patchright"
    requires = ["scrapling"]
    _import_name = "scrapling"

    def _live_fetch(self, task: Task) -> FetchResult:
        from scrapling.fetchers import DynamicFetcher

        # One-off request style: opens a browser, fetches, closes (chrome.py).
        page = DynamicFetcher.fetch(task.url, headless=True, network_idle=True)
        html = str(page.html_content or "")
        if not html:
            body = getattr(page, "body", b"")
            html = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
        try:
            text = page.get_all_text()
        except Exception:
            text = strip_to_text(html, keep_hidden=False)
        status = getattr(page, "status", 0) or 0
        blocked = _looks_blocked(html, text)
        return FetchResult(
            ok=True, html=html, text=str(text),
            status=status or (200 if html else 0),
            blocked=blocked,
            bytes_down=len(html.encode("utf-8")),
            artifacts={"rendered": True, "detector_pass": None},
        )


# Auto-registered by adapters/__init__::_autodiscover via this module-level list.
CANDIDATES = [
    PlaywrightFetch,
    InvisiblePlaywrightFetch,
    CamofoxFetch,
    CloakBrowserFetch,
    ScraplingDynamicFetch,
]
