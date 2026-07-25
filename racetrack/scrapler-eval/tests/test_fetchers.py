"""Tests for the Class-1 fetcher adapters (curl-impersonate, scrapling-static).

Pure stdlib unittest. NO network, NO heavy deps:
  * the file:// path is exercised end-to-end against the real frozen fixture;
  * the LIVE (http) path is exercised with a fake response by monkeypatching the
    module's `_live_*` indirection (or sys.modules) — never a real socket.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

from scrapler_eval import adapters
from scrapler_eval.adapters import fetchers
from scrapler_eval.adapters.fetchers import (
    CurlImpersonateFetch,
    ScraplingStaticFetch,
)
from scrapler_eval.interface import Task, Tier, WeightClass

_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "scrapler_eval" / "fixtures" / "pages" / "tier0_article.html"
)


def _file_task() -> Task:
    return Task(id="t0", tier=Tier.STATIC, url="file://" + str(_FIXTURE))


def _http_task(url: str = "https://example.com/", **meta) -> Task:
    return Task(id="live", tier=Tier.ANTIBOT, url=url, meta=meta)


class _FakeCurlResp:
    """Mimics curl_cffi.requests response (.status_code/.text/.content)."""

    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")


class _FakeScraplingResp:
    """Mimics scrapling Response (.status/.body)."""

    def __init__(self, status: int, body):
        self.status = status
        self.body = body


# --------------------------------------------------------------------------- #
# Metadata / registration
# --------------------------------------------------------------------------- #
class TestMetadata(unittest.TestCase):
    def test_names_and_weight_class(self):
        self.assertEqual(CurlImpersonateFetch.name, "curl-impersonate")
        self.assertEqual(ScraplingStaticFetch.name, "scrapling-static")
        self.assertEqual(int(CurlImpersonateFetch.weight_class), int(WeightClass.FETCHER))
        self.assertEqual(int(ScraplingStaticFetch.weight_class), int(WeightClass.FETCHER))

    def test_requires_and_offline_flag(self):
        self.assertEqual(CurlImpersonateFetch.requires, ["curl_cffi"])
        self.assertEqual(ScraplingStaticFetch.requires, ["scrapling"])
        self.assertTrue(CurlImpersonateFetch.works_offline)
        self.assertTrue(ScraplingStaticFetch.works_offline)

    def test_available_always_true(self):
        # True regardless of whether the heavy dep is present (file:// needs none)
        self.assertTrue(CurlImpersonateFetch().available())
        self.assertTrue(ScraplingStaticFetch().available())

    def test_registered_in_registry(self):
        self.assertIn("curl-impersonate", adapters.REGISTRY)
        self.assertIn("scrapling-static", adapters.REGISTRY)
        self.assertIs(adapters.REGISTRY["curl-impersonate"], CurlImpersonateFetch)
        self.assertIs(adapters.REGISTRY["scrapling-static"], ScraplingStaticFetch)

    def test_module_exposes_candidates(self):
        self.assertEqual(
            fetchers.CANDIDATES, [CurlImpersonateFetch, ScraplingStaticFetch]
        )


# --------------------------------------------------------------------------- #
# file:// path — zero deps, real fixture, both adapters
# --------------------------------------------------------------------------- #
class TestFileURLPath(unittest.TestCase):
    def _assert_good_article(self, res):
        self.assertTrue(res.ok)
        self.assertEqual(res.status, 200)
        self.assertFalse(res.blocked)
        self.assertIn("Marathon", res.text)
        self.assertIn("Ada Lovelace", res.text)
        self.assertGreater(res.bytes_down, 0)
        self.assertGreaterEqual(res.latency_ms, 0.0)
        self.assertIn("<article>", res.html)
        self.assertEqual(res.error, "")

    def test_curl_file_url(self):
        self._assert_good_article(CurlImpersonateFetch().fetch(_file_task()))

    def test_scrapling_file_url(self):
        self._assert_good_article(ScraplingStaticFetch().fetch(_file_task()))

    def test_file_url_needs_no_dep(self):
        # Guarantee: even with the deps absent (as on this box), file:// works.
        self.assertNotIn("curl_cffi", sys.modules)
        res = CurlImpersonateFetch().fetch(_file_task())
        self.assertTrue(res.ok)

    def test_missing_file_returns_not_ok(self):
        task = Task(id="x", tier=Tier.STATIC, url="file:///no/such/fixture.html")
        res = ScraplingStaticFetch().fetch(task)
        self.assertFalse(res.ok)
        self.assertNotEqual(res.error, "")
        self.assertFalse(res.blocked)


# --------------------------------------------------------------------------- #
# LIVE path — curl-impersonate, mocked via _live_curl_fetch
# --------------------------------------------------------------------------- #
class TestCurlLiveBranch(unittest.TestCase):
    def setUp(self):
        self._orig = fetchers._live_curl_fetch

    def tearDown(self):
        fetchers._live_curl_fetch = self._orig

    def test_success_maps_status_text_bytes(self):
        fetchers._live_curl_fetch = lambda url, timeout: _FakeCurlResp(
            200, "<html><body><h1>Live OK</h1><p>hello</p></body></html>"
        )
        res = CurlImpersonateFetch().fetch(_http_task())
        self.assertTrue(res.ok)
        self.assertEqual(res.status, 200)
        self.assertFalse(res.blocked)
        self.assertIn("Live OK", res.text)
        self.assertIn("hello", res.text)
        self.assertGreater(res.bytes_down, 0)
        self.assertGreaterEqual(res.latency_ms, 0.0)

    def test_403_challenge_is_blocked(self):
        fetchers._live_curl_fetch = lambda url, timeout: _FakeCurlResp(
            403, "<html><title>Just a moment...</title><body>cf-challenge</body></html>"
        )
        res = CurlImpersonateFetch().fetch(_http_task())
        self.assertTrue(res.ok)          # we got a response...
        self.assertEqual(res.status, 403)
        self.assertTrue(res.blocked)     # ...but it's a block page

    def test_200_challenge_marker_is_blocked(self):
        fetchers._live_curl_fetch = lambda url, timeout: _FakeCurlResp(
            200, "<html><body>Checking your browser before accessing</body></html>"
        )
        res = CurlImpersonateFetch().fetch(_http_task())
        self.assertEqual(res.status, 200)
        self.assertTrue(res.blocked)

    def test_429_status_is_blocked(self):
        fetchers._live_curl_fetch = lambda url, timeout: _FakeCurlResp(429, "slow down")
        res = CurlImpersonateFetch().fetch(_http_task())
        self.assertEqual(res.status, 429)
        self.assertTrue(res.blocked)

    def test_exception_returns_not_ok(self):
        def boom(url, timeout):
            raise RuntimeError("connection reset")
        fetchers._live_curl_fetch = boom
        res = CurlImpersonateFetch().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("connection reset", res.error)
        self.assertFalse(res.blocked)
        self.assertGreaterEqual(res.latency_ms, 0.0)

    def test_missing_dep_reports_not_installed(self):
        def missing(url, timeout):
            raise ImportError("No module named 'curl_cffi'")
        fetchers._live_curl_fetch = missing
        res = CurlImpersonateFetch().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("not installed", res.error)
        self.assertFalse(res.blocked)


class TestCurlLiveViaSysModules(unittest.TestCase):
    """Exercise the real _live_curl_fetch import path with a fake curl_cffi in
    sys.modules — proves the impersonate call is wired without a real socket."""

    def test_sys_modules_fake(self):
        captured = {}

        fake_requests = types.ModuleType("curl_cffi.requests")

        def fake_get(url, impersonate=None, timeout=None):
            captured["url"] = url
            captured["impersonate"] = impersonate
            captured["timeout"] = timeout
            return _FakeCurlResp(200, "<p>via sys.modules</p>")

        fake_requests.get = fake_get
        fake_pkg = types.ModuleType("curl_cffi")
        fake_pkg.requests = fake_requests

        sys.modules["curl_cffi"] = fake_pkg
        sys.modules["curl_cffi.requests"] = fake_requests
        try:
            res = CurlImpersonateFetch().fetch(_http_task(timeout=7))
        finally:
            sys.modules.pop("curl_cffi", None)
            sys.modules.pop("curl_cffi.requests", None)

        self.assertTrue(res.ok)
        self.assertIn("via sys.modules", res.text)
        self.assertEqual(captured["impersonate"], "chrome124")
        self.assertEqual(captured["timeout"], 7)


# --------------------------------------------------------------------------- #
# LIVE path — scrapling-static, mocked via _live_scrapling_fetch
# --------------------------------------------------------------------------- #
class TestScraplingLiveBranch(unittest.TestCase):
    def setUp(self):
        self._orig = fetchers._live_scrapling_fetch

    def tearDown(self):
        fetchers._live_scrapling_fetch = self._orig

    def test_success_bytes_body(self):
        fetchers._live_scrapling_fetch = lambda url, timeout: _FakeScraplingResp(
            200, b"<html><body><h1>Scrapling</h1></body></html>"
        )
        res = ScraplingStaticFetch().fetch(_http_task())
        self.assertTrue(res.ok)
        self.assertEqual(res.status, 200)
        self.assertFalse(res.blocked)
        self.assertIn("Scrapling", res.text)
        self.assertGreater(res.bytes_down, 0)

    def test_success_str_body(self):
        fetchers._live_scrapling_fetch = lambda url, timeout: _FakeScraplingResp(
            200, "<p>string body</p>"
        )
        res = ScraplingStaticFetch().fetch(_http_task())
        self.assertTrue(res.ok)
        self.assertIn("string body", res.text)

    def test_503_is_blocked(self):
        fetchers._live_scrapling_fetch = lambda url, timeout: _FakeScraplingResp(
            503, b"<html>Attention Required! Cloudflare</html>"
        )
        res = ScraplingStaticFetch().fetch(_http_task())
        self.assertEqual(res.status, 503)
        self.assertTrue(res.blocked)

    def test_exception_returns_not_ok(self):
        def boom(url, timeout):
            raise ValueError("bad tls")
        fetchers._live_scrapling_fetch = boom
        res = ScraplingStaticFetch().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("bad tls", res.error)

    def test_missing_dep_reports_not_installed(self):
        def missing(url, timeout):
            raise ImportError("No module named 'scrapling'")
        fetchers._live_scrapling_fetch = missing
        res = ScraplingStaticFetch().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("not installed", res.error)


# --------------------------------------------------------------------------- #
# stripper / block heuristic units
# --------------------------------------------------------------------------- #
class TestHelpers(unittest.TestCase):
    def test_strip_drops_script_and_tags(self):
        html = "<html><script>var x=1</script><body><p>Keep&amp;me</p></body></html>"
        text = fetchers._strip_to_text(html)
        self.assertIn("Keep&me", text)
        self.assertNotIn("var x=1", text)
        self.assertNotIn("<p>", text)

    def test_is_blocked_status_and_marker(self):
        self.assertTrue(fetchers._is_blocked(403, "ok"))
        self.assertTrue(fetchers._is_blocked(200, "Please enable JavaScript and cookies to continue"))
        self.assertFalse(fetchers._is_blocked(200, "normal article body"))


if __name__ == "__main__":
    unittest.main()
