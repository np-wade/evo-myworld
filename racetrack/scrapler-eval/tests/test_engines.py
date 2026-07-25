"""Tests for the Class-3 engine adapters (crawl4ai, headlessx, browserless,
scrapegraph-ai).

Pure stdlib unittest. NO network, NO heavy deps:
  * the file:// path is exercised end-to-end against a real frozen fixture;
  * live paths are exercised with fakes by monkeypatching each module-level
    `_live_*` indirection (and, for crawl4ai, `_make_crawl4ai_crawler` so the
    real `asyncio.run(_acrawl(...))` wiring runs against a synchronously-
    awaitable fake) — never a real socket or a real browser.
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path

from scrapler_eval import adapters
from scrapler_eval.adapters import engines
from scrapler_eval.adapters.engines import (
    BrowserlessEngine,
    Crawl4aiEngine,
    HeadlessXEngine,
    ScrapegraphEngine,
)
from scrapler_eval.interface import ExtractResult, Task, Tier, WeightClass

_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "scrapler_eval" / "fixtures" / "pages" / "tier0_article.html"
)


def _file_task() -> Task:
    return Task(id="t0", tier=Tier.STATIC, url="file://" + str(_FIXTURE))


def _http_task(url: str = "https://example.com/", **meta) -> Task:
    schema = meta.pop("schema", {})
    return Task(id="live", tier=Tier.ANTIBOT, url=url, schema=schema, meta=meta)


# --- fakes -------------------------------------------------------------------
class _FakeCrawlResult:
    """Mimics crawl4ai CrawlResult (proxied .html/.markdown/.success/.status)."""

    def __init__(self, html, markdown, success=True, status_code=200):
        self.html = html
        self.markdown = markdown
        self.success = success
        self.status_code = status_code
        self.cleaned_html = html


class _FakeMarkdown:
    """Mimics MarkdownGenerationResult (.raw_markdown)."""

    def __init__(self, raw):
        self.raw_markdown = raw
        self.fit_markdown = raw


class _FakeCrawler:
    """Synchronously-awaitable fake AsyncWebCrawler: async context manager whose
    arun() coroutine resolves immediately so asyncio.run(_acrawl(...)) completes."""

    def __init__(self, result):
        self._result = result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def arun(self, url=None, config=None, **kw):
        return self._result


class _EnvGuard:
    """Context-manager helper: set env vars, restore on exit."""

    def __init__(self, **kv):
        self._kv = kv
        self._saved = {}

    def __enter__(self):
        for k, v in self._kv.items():
            self._saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


# --------------------------------------------------------------------------- #
# Metadata / registration
# --------------------------------------------------------------------------- #
class TestMetadata(unittest.TestCase):
    def test_names(self):
        self.assertEqual(Crawl4aiEngine.name, "crawl4ai")
        self.assertEqual(HeadlessXEngine.name, "headlessx")
        self.assertEqual(BrowserlessEngine.name, "browserless")
        self.assertEqual(ScrapegraphEngine.name, "scrapegraph-ai")

    def test_all_weight_class_engine(self):
        for cls in (Crawl4aiEngine, HeadlessXEngine, BrowserlessEngine, ScrapegraphEngine):
            self.assertEqual(int(cls.weight_class), int(WeightClass.ENGINE))

    def test_requires(self):
        self.assertEqual(Crawl4aiEngine.requires, ["crawl4ai"])
        self.assertEqual(HeadlessXEngine.requires, ["http-service"])
        self.assertEqual(BrowserlessEngine.requires, ["http-service"])
        self.assertEqual(ScrapegraphEngine.requires, ["scrapegraphai"])

    def test_module_exposes_candidates(self):
        self.assertEqual(
            engines.CANDIDATES,
            [Crawl4aiEngine, HeadlessXEngine, BrowserlessEngine, ScrapegraphEngine],
        )

    def test_registered_in_registry(self):
        for name, cls in (
            ("crawl4ai", Crawl4aiEngine),
            ("headlessx", HeadlessXEngine),
            ("browserless", BrowserlessEngine),
            ("scrapegraph-ai", ScrapegraphEngine),
        ):
            self.assertIn(name, adapters.REGISTRY)
            self.assertIs(adapters.REGISTRY[name], cls)


# --------------------------------------------------------------------------- #
# available() — bool without crashing; False on this bare box
# --------------------------------------------------------------------------- #
class TestAvailable(unittest.TestCase):
    def test_all_return_bool(self):
        for cls in (Crawl4aiEngine, HeadlessXEngine, BrowserlessEngine, ScrapegraphEngine):
            self.assertIsInstance(cls().available(), bool)

    def test_pkg_engines_false_when_dep_absent(self):
        # crawl4ai / scrapegraphai are not installed on this box.
        self.assertNotIn("crawl4ai", sys.modules)
        self.assertFalse(Crawl4aiEngine().available())
        self.assertFalse(ScrapegraphEngine().available())

    def test_http_engines_false_without_env(self):
        with _EnvGuard(HEADLESSX_URL=None, BROWSERLESS_URL=None):
            self.assertFalse(HeadlessXEngine().available())
            self.assertFalse(BrowserlessEngine().available())

    def test_http_engines_true_with_env(self):
        with _EnvGuard(HEADLESSX_URL="http://localhost:3000",
                       BROWSERLESS_URL="http://localhost:3001"):
            self.assertTrue(HeadlessXEngine().available())
            self.assertTrue(BrowserlessEngine().available())


# --------------------------------------------------------------------------- #
# file:// path — zero deps, real fixture, all four engines
# --------------------------------------------------------------------------- #
class TestFileURLPath(unittest.TestCase):
    def _assert_good(self, res, engine):
        self.assertTrue(res.ok)
        self.assertEqual(res.status, 200)
        self.assertFalse(res.blocked)
        self.assertIn("Marathon", res.text)
        self.assertIn("Ada Lovelace", res.text)
        self.assertGreater(res.bytes_down, 0)
        self.assertGreaterEqual(res.latency_ms, 0.0)
        self.assertEqual(res.artifacts.get("engine"), engine)
        self.assertEqual(res.error, "")

    def test_crawl4ai_file(self):
        self._assert_good(Crawl4aiEngine().fetch(_file_task()), "crawl4ai")

    def test_headlessx_file(self):
        self._assert_good(HeadlessXEngine().fetch(_file_task()), "headlessx")

    def test_browserless_file(self):
        self._assert_good(BrowserlessEngine().fetch(_file_task()), "browserless")

    def test_scrapegraph_file(self):
        self._assert_good(ScrapegraphEngine().fetch(_file_task()), "scrapegraph-ai")

    def test_file_needs_no_dep(self):
        self.assertNotIn("crawl4ai", sys.modules)
        self.assertTrue(Crawl4aiEngine().fetch(_file_task()).ok)

    def test_missing_file_returns_not_ok(self):
        task = Task(id="x", tier=Tier.STATIC, url="file:///no/such/fixture.html")
        res = HeadlessXEngine().fetch(task)
        self.assertFalse(res.ok)
        self.assertNotEqual(res.error, "")
        self.assertEqual(res.artifacts.get("engine"), "headlessx")


# --------------------------------------------------------------------------- #
# crawl4ai LIVE — real asyncio.run against a synchronously-awaitable fake
# --------------------------------------------------------------------------- #
class TestCrawl4aiLive(unittest.TestCase):
    def setUp(self):
        self._orig = engines._make_crawl4ai_crawler

    def tearDown(self):
        engines._make_crawl4ai_crawler = self._orig

    def test_markdown_object_maps_html_text(self):
        result = _FakeCrawlResult(
            html="<html><body><h1>Live</h1><p>body</p></body></html>",
            markdown=_FakeMarkdown("# Live\n\nbody"),
        )
        engines._make_crawl4ai_crawler = lambda: _FakeCrawler(result)
        res = Crawl4aiEngine().fetch(_http_task())
        self.assertTrue(res.ok)
        self.assertEqual(res.status, 200)
        self.assertIn("<h1>Live</h1>", res.html)
        self.assertIn("# Live", res.text)          # markdown wins as text
        self.assertEqual(res.artifacts["markdown"], "# Live\n\nbody")
        self.assertEqual(res.artifacts["engine"], "crawl4ai")
        self.assertGreater(res.bytes_down, 0)

    def test_string_markdown(self):
        result = _FakeCrawlResult(html="<p>x</p>", markdown="plain md")
        engines._make_crawl4ai_crawler = lambda: _FakeCrawler(result)
        res = Crawl4aiEngine().fetch(_http_task())
        self.assertEqual(res.text, "plain md")

    def test_failure_result_sets_ok_false(self):
        result = _FakeCrawlResult(html="", markdown="", success=False, status_code=500)
        engines._make_crawl4ai_crawler = lambda: _FakeCrawler(result)
        res = Crawl4aiEngine().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertEqual(res.status, 500)

    def test_exception_returns_not_ok(self):
        def boom():
            raise RuntimeError("browser launch failed")
        engines._make_crawl4ai_crawler = boom
        res = Crawl4aiEngine().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("browser launch failed", res.error)
        self.assertEqual(res.artifacts["engine"], "crawl4ai")

    def test_missing_dep_reports_not_installed(self):
        def missing():
            raise ImportError("No module named 'crawl4ai'")
        engines._make_crawl4ai_crawler = missing
        res = Crawl4aiEngine().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("not installed", res.error)


# --------------------------------------------------------------------------- #
# HeadlessX LIVE — mocked via _live_headlessx_fetch
# --------------------------------------------------------------------------- #
class TestHeadlessXLive(unittest.TestCase):
    def setUp(self):
        self._orig = engines._live_headlessx_fetch

    def tearDown(self):
        engines._live_headlessx_fetch = self._orig

    def test_json_response_maps_html(self):
        import json as _json
        body = _json.dumps({"url": "u", "html": "<h1>HX</h1><p>ok</p>",
                            "metadata": {"statusCode": 200}})
        engines._live_headlessx_fetch = lambda base, url, token, timeout: (200, body)
        with _EnvGuard(HEADLESSX_URL="http://localhost:3000"):
            res = HeadlessXEngine().fetch(_http_task())
        self.assertTrue(res.ok)
        self.assertEqual(res.status, 200)
        self.assertIn("HX", res.text)
        self.assertIn("<h1>HX</h1>", res.html)
        self.assertGreaterEqual(res.latency_ms, 0.0)

    def test_challenge_body_is_blocked(self):
        import json as _json
        body = _json.dumps({"html": "<title>Just a moment...</title>",
                            "metadata": {"statusCode": 503}})
        engines._live_headlessx_fetch = lambda base, url, token, timeout: (200, body)
        with _EnvGuard(HEADLESSX_URL="http://localhost:3000"):
            res = HeadlessXEngine().fetch(_http_task())
        self.assertEqual(res.status, 503)     # inner statusCode wins
        self.assertTrue(res.blocked)

    def test_env_missing_at_fetch_returns_not_ok(self):
        with _EnvGuard(HEADLESSX_URL=None):
            res = HeadlessXEngine().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("HEADLESSX_URL", res.error)

    def test_unreachable_service_returns_not_ok(self):
        def boom(base, url, token, timeout):
            raise OSError("Connection refused")
        engines._live_headlessx_fetch = boom
        with _EnvGuard(HEADLESSX_URL="http://localhost:3000"):
            res = HeadlessXEngine().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("Connection refused", res.error)
        self.assertEqual(res.artifacts["engine"], "headlessx")


# --------------------------------------------------------------------------- #
# browserless LIVE — mocked via _live_browserless_fetch
# --------------------------------------------------------------------------- #
class TestBrowserlessLive(unittest.TestCase):
    def setUp(self):
        self._orig = engines._live_browserless_fetch

    def tearDown(self):
        engines._live_browserless_fetch = self._orig

    def test_raw_html_body(self):
        engines._live_browserless_fetch = lambda base, url, token, timeout: (
            200, "<html><body><h1>BL</h1><p>rendered</p></body></html>"
        )
        with _EnvGuard(BROWSERLESS_URL="http://localhost:3001"):
            res = BrowserlessEngine().fetch(_http_task())
        self.assertTrue(res.ok)
        self.assertEqual(res.status, 200)
        self.assertIn("rendered", res.text)
        self.assertIn("<h1>BL</h1>", res.html)
        self.assertGreater(res.bytes_down, 0)

    def test_403_is_blocked(self):
        engines._live_browserless_fetch = lambda base, url, token, timeout: (
            403, "<html>cf-challenge</html>"
        )
        with _EnvGuard(BROWSERLESS_URL="http://localhost:3001"):
            res = BrowserlessEngine().fetch(_http_task())
        self.assertEqual(res.status, 403)
        self.assertTrue(res.blocked)

    def test_env_missing_at_fetch_returns_not_ok(self):
        with _EnvGuard(BROWSERLESS_URL=None):
            res = BrowserlessEngine().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("BROWSERLESS_URL", res.error)

    def test_unreachable_returns_not_ok(self):
        def boom(base, url, token, timeout):
            raise OSError("timed out")
        engines._live_browserless_fetch = boom
        with _EnvGuard(BROWSERLESS_URL="http://localhost:3001"):
            res = BrowserlessEngine().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("timed out", res.error)


# --------------------------------------------------------------------------- #
# Scrapegraph-ai LIVE fetch + extract — mocked via _live_scrapegraph_run
# --------------------------------------------------------------------------- #
class TestScrapegraphLive(unittest.TestCase):
    def setUp(self):
        self._orig = engines._live_scrapegraph_run

    def tearDown(self):
        engines._live_scrapegraph_run = self._orig

    def test_fetch_maps_fields_and_tokens(self):
        exec_info = [
            {"node_name": "Fetch", "total_tokens": 0},
            {"node_name": "GenerateAnswer", "total_tokens": 128},
            {"node_name": "TOTAL RESULT", "total_tokens": 128},
        ]
        answer = {"title": "The Marathon Continues", "author": "Ada Lovelace"}
        engines._live_scrapegraph_run = lambda prompt, source, config: (answer, exec_info)
        task = _http_task(schema={"fields": ["title", "author"]})
        res = ScrapegraphEngine().fetch(task)
        self.assertTrue(res.ok)
        self.assertEqual(res.artifacts["fields"], answer)
        self.assertEqual(res.llm_tokens, 256)   # summed across the two nonzero rows
        self.assertIn("Marathon", res.text)
        self.assertEqual(res.artifacts["engine"], "scrapegraph-ai")

    def test_fetch_prompt_derived_from_schema(self):
        captured = {}

        def fake_run(prompt, source, config):
            captured["prompt"] = prompt
            captured["source"] = source
            return {"x": 1}, []
        engines._live_scrapegraph_run = fake_run
        task = _http_task(schema={"prompt": "Grab the price"})
        ScrapegraphEngine().fetch(task)
        self.assertEqual(captured["prompt"], "Grab the price")
        self.assertEqual(captured["source"], task.url)   # URL is the fetch source

    def test_fetch_error_returns_not_ok(self):
        def boom(prompt, source, config):
            raise RuntimeError("llm auth failed")
        engines._live_scrapegraph_run = boom
        res = ScrapegraphEngine().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("llm auth failed", res.error)

    def test_fetch_missing_dep_reports_not_installed(self):
        def missing(prompt, source, config):
            raise ImportError("No module named 'scrapegraphai'")
        engines._live_scrapegraph_run = missing
        res = ScrapegraphEngine().fetch(_http_task())
        self.assertFalse(res.ok)
        self.assertIn("not installed", res.error)

    def test_extract_over_html(self):
        captured = {}

        def fake_run(prompt, source, config):
            captured["source"] = source
            return {"name": "Widget"}, [{"total_tokens": 10}]
        engines._live_scrapegraph_run = fake_run
        html = "<html><body><h1>Widget</h1></body></html>"
        out = ScrapegraphEngine().extract(html, _http_task(schema={"fields": ["name"]}))
        self.assertIsInstance(out, ExtractResult)
        self.assertTrue(out.ok)
        self.assertEqual(out.fields, {"name": "Widget"})
        self.assertEqual(captured["source"], html)       # HTML is the extract source

    def test_extract_error_falls_back_to_stripped_text(self):
        def boom(prompt, source, config):
            raise ValueError("graph blew up")
        engines._live_scrapegraph_run = boom
        out = ScrapegraphEngine().extract("<p>hello world</p>", _http_task())
        self.assertFalse(out.ok)
        self.assertIn("graph blew up", out.error)
        self.assertIn("hello world", out.text)


# --------------------------------------------------------------------------- #
# helper units
# --------------------------------------------------------------------------- #
class TestHelpers(unittest.TestCase):
    def test_md_to_str_variants(self):
        self.assertEqual(engines._md_to_str(None), "")
        self.assertEqual(engines._md_to_str("raw"), "raw")
        self.assertEqual(engines._md_to_str(_FakeMarkdown("obj md")), "obj md")

    def test_sum_tokens(self):
        self.assertEqual(engines._sum_tokens([{"total_tokens": 5}, {"total_tokens": 7}]), 12)
        self.assertEqual(engines._sum_tokens({"total_tokens": 9}), 9)
        self.assertEqual(engines._sum_tokens([{"nope": 1}, "junk", None]), 0)

    def test_is_blocked(self):
        self.assertTrue(engines._is_blocked(403, "ok"))
        self.assertTrue(engines._is_blocked(200, "Checking your browser"))
        self.assertFalse(engines._is_blocked(200, "normal body"))

    def test_scrapegraph_prompt_precedence(self):
        p = engines._scrapegraph_prompt(_http_task(schema={"prompt": "P"}))
        self.assertEqual(p, "P")
        f = engines._scrapegraph_prompt(_http_task(schema={"fields": ["a", "b"]}))
        self.assertIn("a, b", f)


if __name__ == "__main__":
    unittest.main()
