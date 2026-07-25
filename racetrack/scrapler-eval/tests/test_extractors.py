"""Class-4 extractor adapter tests — stdlib unittest, NO network, NO heavy deps.

Drives the real tier1_dynamic.html fixture (JSON-in-HTML product page) through
the four extractor adapters and asserts the ported logic + self-heal + the LLM
no-key guard. The LLM adapter is verified to make ZERO network calls without a
key by monkeypatching urlopen to raise if it is ever touched.
"""

import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from scrapler_eval.adapters import extractors as ex
from scrapler_eval.adapters.extractors import (
    AdaptiveExtract,
    CssJsonExtract,
    LlmExtract,
    TrafilaturaExtract,
    CANDIDATES,
)
from scrapler_eval.interface import ExtractResult, Task, Tier, WeightClass

_FIXTURE = (Path(__file__).resolve().parents[1]
            / "scrapler_eval" / "fixtures" / "pages" / "tier1_dynamic.html")


def _task(css=None):
    schema = {"fields": ["name", "price", "description"]}
    if css is not None:
        schema["css"] = css
    return Task(
        id="x-product-fields",
        tier=Tier.DYNAMIC,
        url=f"file://{_FIXTURE}",
        schema=schema,
        answer_key={"fields": {
            "name": "Anti-Detect Browser Pro",
            "price": "$0.00",
            "description": "A hardened browser that renders JavaScript and evades fingerprint checks.",
        }},
    )


class _RaiseIfCalled:
    """Stand-in for urlopen that fails the test if the network is touched."""
    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise AssertionError("urlopen must NOT be called without an LLM backend")


class ExtractorTestBase(unittest.TestCase):
    def setUp(self):
        self.html = _FIXTURE.read_text(encoding="utf-8")
        self.task = _task()


class TestTrafilatura(ExtractorTestBase):
    def test_registered_metadata(self):
        c = TrafilaturaExtract()
        self.assertEqual(c.name, "trafilatura-article")
        self.assertEqual(c.weight_class, WeightClass.EXTRACTOR)

    def test_available_true_via_fallback(self):
        self.assertTrue(TrafilaturaExtract().available())

    def test_fallback_returns_text_with_product_name(self):
        res = TrafilaturaExtract().extract(self.html, self.task)
        self.assertIsInstance(res, ExtractResult)
        self.assertTrue(res.ok)
        self.assertIn("Anti-Detect", res.text)

    def test_fallback_surfaces_description(self):
        res = TrafilaturaExtract().extract(self.html, self.task)
        self.assertIn("hardened browser that renders JavaScript", res.text)


class TestCssJson(ExtractorTestBase):
    def test_metadata_and_available(self):
        c = CssJsonExtract()
        self.assertEqual(c.name, "css-json")
        self.assertEqual(c.weight_class, WeightClass.EXTRACTOR)
        self.assertTrue(c.available())

    def test_infers_fields_from_json_blob(self):
        res = CssJsonExtract().extract(self.html, self.task)
        self.assertTrue(res.ok)
        self.assertEqual(res.fields["name"], "Anti-Detect Browser Pro")
        self.assertEqual(res.fields["price"], "$0.00")
        self.assertIn("hardened browser", res.fields["description"])

    def test_stdlib_css_selector_resolves(self):
        html = ('<html><body><h1 class="title">Widget</h1>'
                '<span class="price">$5.00</span></body></html>')
        task = _task(css={"name": "h1.title", "price": ".price"})
        # description has no css + no blob here -> just name/price resolve.
        task.schema["fields"] = ["name", "price"]
        res = CssJsonExtract().extract(html, task)
        self.assertEqual(res.fields["name"], "Widget")
        self.assertEqual(res.fields["price"], "$5.00")

    def test_no_fields_and_no_blob_is_not_ok(self):
        task = Task(id="empty", tier=Tier.STATIC, url="file://x", schema={})
        res = CssJsonExtract().extract("<html><body>hi</body></html>", task)
        self.assertFalse(res.ok)


class TestAdaptive(ExtractorTestBase):
    def test_metadata_and_available(self):
        c = AdaptiveExtract()
        self.assertEqual(c.name, "adaptive-selfheal")
        self.assertEqual(c.weight_class, WeightClass.EXTRACTOR)
        self.assertTrue(c.available())

    def test_recovers_fields_from_json_blob(self):
        res = AdaptiveExtract().extract(self.html, self.task)
        self.assertTrue(res.ok)
        self.assertEqual(res.fields["name"], "Anti-Detect Browser Pro")
        self.assertEqual(res.fields["description"],
                         "A hardened browser that renders JavaScript and evades fingerprint checks.")

    def test_self_heals_on_broken_selector(self):
        # A deliberately broken selector for `name` must NOT match; the extractor
        # repairs itself from the JSON payload and marks the field as healed.
        task = _task(css={"name": "h1.does-not-exist"})
        c = AdaptiveExtract()
        res = c.extract(self.html, task)
        self.assertEqual(res.fields["name"], "Anti-Detect Browser Pro")
        self.assertIn("name", c.healed_fields)

    def test_valid_selector_is_not_marked_healed(self):
        html = ('<html><body><h1 class="title">Anti-Detect Browser Pro</h1>'
                '</body></html>')
        task = _task(css={"name": "h1.title"})
        task.schema["fields"] = ["name"]
        c = AdaptiveExtract()
        res = c.extract(html, task)
        self.assertEqual(res.fields["name"], "Anti-Detect Browser Pro")
        self.assertNotIn("name", c.healed_fields)

    def test_healed_fields_reset_between_runs(self):
        c = AdaptiveExtract()
        c.extract(self.html, _task(css={"name": "h1.nope"}))
        self.assertIn("name", c.healed_fields)
        # A clean run with resolvable-from-blob fields records no broken selector.
        c.extract(self.html, _task(css={"name": "h1.title2"}))
        # name still heals from blob (selector invalid) — but list was reset first.
        self.assertEqual(c.healed_fields.count("name"), 1)


class TestLlm(ExtractorTestBase):
    def test_metadata(self):
        c = LlmExtract()
        self.assertEqual(c.name, "llm-extract")
        self.assertEqual(c.weight_class, WeightClass.EXTRACTOR)

    def test_unavailable_and_no_network_without_key(self):
        guard = _RaiseIfCalled()
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(ex, "urlopen", guard):
            c = LlmExtract()
            self.assertFalse(c.available())
            res = c.extract(self.html, self.task)
            self.assertFalse(res.ok)
            self.assertEqual(res.error, "no LLM backend")
        self.assertEqual(guard.calls, 0)  # network never touched

    def test_available_true_with_openai_key(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            self.assertTrue(LlmExtract().available())

    def test_available_true_with_ollama_url(self):
        with mock.patch.dict(os.environ, {"OLLAMA_URL": "http://localhost:11434"}, clear=True):
            self.assertTrue(LlmExtract().available())

    def test_with_key_parses_mocked_response(self):
        # Exercises the with-backend path against a FAKE endpoint (no real net).
        body = json.dumps({
            "choices": [{"message": {"content": json.dumps({
                "name": "Anti-Detect Browser Pro", "price": "$0.00",
                "description": "A hardened browser.",
            })}}],
            "usage": {"total_tokens": 42},
        }).encode("utf-8")

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True), \
                mock.patch.object(ex, "urlopen", return_value=_Resp(body)):
            res = LlmExtract().extract(self.html, self.task)
        self.assertTrue(res.ok)
        self.assertEqual(res.fields["name"], "Anti-Detect Browser Pro")
        self.assertIn("tokens=42", res.error)


class TestRegistration(unittest.TestCase):
    def test_candidates_export_all_four(self):
        names = {c.name for c in CANDIDATES}
        self.assertEqual(names, {
            "trafilatura-article", "css-json", "adaptive-selfheal", "llm-extract",
        })

    def test_all_are_extractor_class(self):
        for cls in CANDIDATES:
            self.assertEqual(cls().weight_class, WeightClass.EXTRACTOR)

    def test_autoregistered_in_registry(self):
        from scrapler_eval.adapters import REGISTRY
        for n in ("trafilatura-article", "css-json", "adaptive-selfheal", "llm-extract"):
            self.assertIn(n, REGISTRY)


if __name__ == "__main__":
    unittest.main()
