"""Tests for the class-2 (stealth browser) adapters — stdlib unittest only.

NO network, NO real browser. The file:// path is exercised against the frozen
tier1_dynamic.html fixture; the live path is exercised with fake donor modules
injected into sys.modules so we prove fetch() maps page.content()->html, sets
latency, and flags challenge pages — without launching anything.
"""

import sys
import types
import unittest
from pathlib import Path

from scrapler_eval.interface import FetchResult, Task, Tier, WeightClass
from scrapler_eval.adapters.browsers import (
    CANDIDATES,
    PlaywrightFetch,
    InvisiblePlaywrightFetch,
    CamofoxFetch,
    CloakBrowserFetch,
    ScraplingDynamicFetch,
)

_FIXTURE = Path(__file__).parent.parent / "scrapler_eval" / "fixtures" / "pages" / "tier1_dynamic.html"


def _file_task() -> Task:
    return Task(id="t1", tier=Tier.DYNAMIC, url="file://" + str(_FIXTURE))


def _live_task(url: str = "https://example.com/product") -> Task:
    return Task(id="live", tier=Tier.ANTIBOT, url=url)


# --------------------------------------------------------------------------- #
# Fake Playwright-style donor objects (playwright / invisible / camofox / cloak)
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, status=200):
        self.status = status


class _FakePage:
    """Minimal Playwright page: goto()->resp, content()->html. No screenshot."""

    def __init__(self, html, status=200):
        self._html = html
        self._resp = _FakeResp(status)
        self.goto_url = None

    def goto(self, url, **kw):
        self.goto_url = url
        return self._resp

    def content(self):
        return self._html


class _FakeBrowser:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class _FakeCtxBrowser:
    """A `with InvisiblePlaywright(...) as browser:` / Camoufox(...) object."""

    def __init__(self, browser):
        self._browser = browser

    def __enter__(self):
        return self._browser

    def __exit__(self, *a):
        return False


class _FakeChromium:
    def __init__(self, browser):
        self._browser = browser
        self.launch_kwargs = None

    def launch(self, **kw):
        self.launch_kwargs = kw
        return self._browser


class _FakePW:
    def __init__(self, browser):
        self.chromium = _FakeChromium(browser)


class _FakeSyncPWCtx:
    def __init__(self, browser):
        self._pw = _FakePW(browser)

    def __enter__(self):
        return self._pw

    def __exit__(self, *a):
        return False


class _FakeScraplingPage:
    def __init__(self, html, text, status=200):
        self.html_content = html
        self.status = status
        self._text = text

    def get_all_text(self):
        return self._text


class _ModuleInstaller(unittest.TestCase):
    """Base with a helper to temporarily inject fake modules into sys.modules."""

    def _install(self, name, **attrs):
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        prev = sys.modules.get(name)
        sys.modules[name] = mod
        self.addCleanup(self._restore, name, prev)
        return mod

    @staticmethod
    def _restore(name, prev):
        if prev is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prev


class TestFilePath(unittest.TestCase):
    """Every adapter's file:// branch reads the fixture and strips to text."""

    def _check_file(self, adapter):
        res = adapter.fetch(_file_task())
        self.assertIsInstance(res, FetchResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.status, 200)
        self.assertIn("Anti-Detect Browser Pro", res.text)
        self.assertFalse(res.artifacts["rendered"])  # render is meaningless on file://
        self.assertGreater(res.latency_ms, 0.0)
        self.assertGreaterEqual(res.peak_rss_mb, 0.0)
        self.assertGreater(res.bytes_down, 0)
        return res

    def test_playwright_file_render(self):
        self._check_file(PlaywrightFetch())

    def test_invisible_file_render(self):
        self._check_file(InvisiblePlaywrightFetch())

    def test_camofox_file_render(self):
        self._check_file(CamofoxFetch())

    def test_cloakbrowser_file_render(self):
        self._check_file(CloakBrowserFetch())

    def test_scrapling_file_render(self):
        self._check_file(ScraplingDynamicFetch())

    def test_file_fixture_not_flagged_blocked(self):
        # The benign fixture must not trip challenge detection.
        res = PlaywrightFetch().fetch(_file_task())
        self.assertFalse(res.blocked)


class TestAvailability(unittest.TestCase):
    """Deps are absent on this headless box -> available() is a clean False."""

    ADAPTERS = [
        PlaywrightFetch, InvisiblePlaywrightFetch, CamofoxFetch,
        CloakBrowserFetch, ScraplingDynamicFetch,
    ]

    def test_available_returns_bool_without_crashing(self):
        for cls in self.ADAPTERS:
            with self.subTest(adapter=cls.name):
                val = cls().available()  # must not raise even when dep missing
                self.assertIsInstance(val, bool)

    def test_available_is_false_when_dep_absent(self):
        for cls in self.ADAPTERS:
            with self.subTest(adapter=cls.name):
                self.assertFalse(cls().available())

    def test_all_are_browser_weight_class(self):
        for cls in self.ADAPTERS:
            with self.subTest(adapter=cls.name):
                self.assertEqual(cls().weight_class, WeightClass.BROWSER)

    def test_each_declares_pip_requirement(self):
        for cls in self.ADAPTERS:
            with self.subTest(adapter=cls.name):
                self.assertTrue(cls().requires)


class TestLivePlaywrightStyle(_ModuleInstaller):
    """Live branch with fake donor modules — proves content()->html + latency."""

    def test_playwright_live_maps_content_and_latency(self):
        page = _FakePage("<html><body><h1>Live Product</h1></body></html>", status=200)
        browser = _FakeBrowser(page)
        self._install("playwright")
        self._install("playwright.sync_api",
                      sync_playwright=lambda: _FakeSyncPWCtx(browser))
        res = PlaywrightFetch().fetch(_live_task())
        self.assertTrue(res.ok)
        self.assertIn("Live Product", res.html)
        self.assertIn("Live Product", res.text)
        self.assertEqual(res.status, 200)
        self.assertGreater(res.latency_ms, 0.0)
        self.assertTrue(res.artifacts["rendered"])
        self.assertIn("detector_pass", res.artifacts)  # left for the detector tier
        self.assertTrue(browser.closed)  # browser was cleaned up
        self.assertEqual(page.goto_url, "https://example.com/product")

    def test_invisible_live_maps_content(self):
        page = _FakePage("<html><body>Invisible OK</body></html>", status=200)
        browser = _FakeBrowser(page)
        self._install("invisible_playwright",
                      InvisiblePlaywright=lambda **kw: _FakeCtxBrowser(browser))
        res = InvisiblePlaywrightFetch().fetch(_live_task())
        self.assertTrue(res.ok)
        self.assertIn("Invisible OK", res.text)
        self.assertEqual(res.status, 200)
        self.assertGreater(res.latency_ms, 0.0)

    def test_camofox_live_maps_content(self):
        page = _FakePage("<html><body>Camo OK</body></html>", status=200)
        browser = _FakeBrowser(page)
        self._install("camoufox")
        self._install("camoufox.sync_api",
                      Camoufox=lambda **kw: _FakeCtxBrowser(browser))
        res = CamofoxFetch().fetch(_live_task())
        self.assertTrue(res.ok)
        self.assertIn("Camo OK", res.text)
        self.assertEqual(res.status, 200)

    def test_cloakbrowser_live_maps_content_and_closes(self):
        page = _FakePage("<html><body>Cloak OK</body></html>", status=200)
        browser = _FakeBrowser(page)
        self._install("cloakbrowser", launch=lambda **kw: browser)
        res = CloakBrowserFetch().fetch(_live_task())
        self.assertTrue(res.ok)
        self.assertIn("Cloak OK", res.text)
        self.assertTrue(browser.closed)

    def test_scrapling_live_maps_content_and_status(self):
        page = _FakeScraplingPage(
            "<html><body>Scrapling Dynamic</body></html>", "Scrapling Dynamic", status=200)
        fetcher = types.SimpleNamespace(fetch=staticmethod(lambda url, **kw: page))
        self._install("scrapling")
        self._install("scrapling.fetchers", DynamicFetcher=fetcher)
        res = ScraplingDynamicFetch().fetch(_live_task())
        self.assertTrue(res.ok)
        self.assertIn("Scrapling Dynamic", res.html)
        self.assertEqual(res.text, "Scrapling Dynamic")
        self.assertEqual(res.status, 200)
        self.assertGreater(res.latency_ms, 0.0)
        self.assertTrue(res.artifacts["rendered"])


class TestChallengeAndErrors(_ModuleInstaller):
    def test_live_challenge_page_is_flagged_blocked(self):
        # A Cloudflare interstitial: ok (we got a page) but blocked=True.
        challenge = "<html><head><title>Just a moment...</title></head>" \
                    "<body>Checking your browser before accessing. Ray ID: abc</body></html>"
        page = _FakePage(challenge, status=403)
        browser = _FakeBrowser(page)
        self._install("playwright")
        self._install("playwright.sync_api",
                      sync_playwright=lambda: _FakeSyncPWCtx(browser))
        res = PlaywrightFetch().fetch(_live_task())
        self.assertTrue(res.ok)
        self.assertTrue(res.blocked)
        self.assertEqual(res.status, 403)

    def test_scrapling_challenge_flagged_blocked(self):
        page = _FakeScraplingPage(
            "<html>Access denied - Cloudflare</html>", "Access denied", status=403)
        fetcher = types.SimpleNamespace(fetch=staticmethod(lambda url, **kw: page))
        self._install("scrapling")
        self._install("scrapling.fetchers", DynamicFetcher=fetcher)
        res = ScraplingDynamicFetch().fetch(_live_task())
        self.assertTrue(res.blocked)

    def test_live_exception_returns_ok_false(self):
        def boom():
            raise RuntimeError("browser binary missing")
        self._install("playwright")
        self._install("playwright.sync_api", sync_playwright=boom)
        res = PlaywrightFetch().fetch(_live_task())
        self.assertFalse(res.ok)
        self.assertIn("browser binary missing", res.error)
        self.assertGreater(res.latency_ms, 0.0)  # timing still stamped on failure

    def test_screenshot_branch_records_artifact(self):
        # A page that CAN screenshot gets a screenshot path in artifacts.
        class _ShotPage(_FakePage):
            def screenshot(self, path=None):
                self.shot_path = path  # no-op, no real file written

        page = _ShotPage("<html><body>Shot OK</body></html>", status=200)
        browser = _FakeBrowser(page)
        self._install("playwright")
        self._install("playwright.sync_api",
                      sync_playwright=lambda: _FakeSyncPWCtx(browser))
        res = PlaywrightFetch().fetch(_live_task())
        self.assertIn("screenshot", res.artifacts)
        self.assertTrue(res.artifacts["screenshot"].endswith(".png"))


class TestRegistration(unittest.TestCase):
    def test_candidates_exported(self):
        names = {c.name for c in CANDIDATES}
        self.assertEqual(names, {
            "playwright-baseline", "invisible-playwright", "camofox",
            "cloakbrowser", "scrapling-patchright",
        })

    def test_registered_in_registry(self):
        from scrapler_eval.adapters import REGISTRY
        for cls in CANDIDATES:
            with self.subTest(adapter=cls.name):
                self.assertIn(cls.name, REGISTRY)


if __name__ == "__main__":
    unittest.main()
