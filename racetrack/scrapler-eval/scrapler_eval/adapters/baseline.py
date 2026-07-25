"""Baseline / control candidates — pure stdlib, always available().

These are the control group the real tools must beat:
- RawFetch      : class-1 no-JS fetch (reads the fixture / a real URL via urllib),
                  strips tags to text. The "httpx baseline" from candidates-scraping.md.
- JsonBlobExtract: class-4 extractor that parses an embedded __DATA__ JSON blob.
- RegexArticleExtract: class-4 naive article/markdown extractor (weaker — for contrast).

Real heavy adapters (curl-impersonate, Scrapling, playwright, crawl4ai, ...)
live in sibling modules and gate on their own deps via available().
"""

from __future__ import annotations

import html as htmlmod
import json
import re
import time
import urllib.request
from pathlib import Path

from ..interface import Candidate, ExtractResult, FetchResult, Task, WeightClass

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_SCRIPT_STYLE = re.compile(r"<(script|style|template)[^>]*>.*?</\1>", re.S | re.I)


def strip_to_text(html: str, keep_hidden: bool = True) -> str:
    """HTML -> visible text. keep_hidden=True leaves <template>/<script> JSON in
    (a no-JS fetcher genuinely sees markup content); False mimics a renderer that
    only shows rendered/visible text."""
    doc = html if keep_hidden else _SCRIPT_STYLE.sub(" ", html)
    doc = _TAG.sub(" ", doc)
    return _WS.sub(" ", htmlmod.unescape(doc)).strip()


def _read(task: Task) -> str:
    if task.url.startswith("file://"):
        return Path(task.url[len("file://"):]).read_text(encoding="utf-8")
    with urllib.request.urlopen(task.url, timeout=20) as r:  # live fallback
        return r.read().decode("utf-8", "replace")


class RawFetch(Candidate):
    name = "raw-fetch-baseline"
    weight_class = WeightClass.FETCHER
    requires: list[str] = []

    def available(self) -> bool:
        return True

    def fetch(self, task: Task) -> FetchResult:
        t0 = time.perf_counter()
        try:
            html = _read(task)
        except Exception as exc:
            return FetchResult(ok=False, error=str(exc), blocked=False,
                               latency_ms=(time.perf_counter() - t0) * 1000)
        text = strip_to_text(html, keep_hidden=True)
        return FetchResult(
            ok=True, html=html, text=text, status=200, blocked=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
            bytes_down=len(html.encode("utf-8")),
        )


class JsonBlobExtract(Candidate):
    """Parses an embedded <script id="__DATA__" type="application/json"> blob —
    the strong extractor for JSON-in-HTML pages."""
    name = "json-blob-extractor"
    weight_class = WeightClass.EXTRACTOR
    requires: list[str] = []

    def available(self) -> bool:
        return True

    def extract(self, html: str, task: Task) -> ExtractResult:
        m = re.search(r'<script[^>]*id="__DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return ExtractResult(ok=False, error="no __DATA__ blob", text=strip_to_text(html))
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            return ExtractResult(ok=False, error=f"bad json: {exc}")
        product = data.get("product", data)
        wanted = task.schema.get("fields", list(product.keys()))
        fields = {k: product.get(k) for k in wanted if k in product}
        text = " ".join(str(v) for v in fields.values())
        return ExtractResult(ok=True, fields=fields, text=text)


class RegexArticleExtract(Candidate):
    """Naive readability-style extractor: longest <p> run as text, <h1> as title.
    Deliberately weak on structured fields — the contrast candidate."""
    name = "regex-article-extractor"
    weight_class = WeightClass.EXTRACTOR
    requires: list[str] = []

    def available(self) -> bool:
        return True

    def extract(self, html: str, task: Task) -> ExtractResult:
        title = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        paras = re.findall(r"<p[^>]*>(.*?)</p>", html, re.S)
        text = strip_to_text(" ".join(paras))
        fields = {}
        if title:
            fields["name"] = strip_to_text(title.group(1))
        return ExtractResult(ok=True, fields=fields, text=text or strip_to_text(html))


# Registry the CLI/tests build brackets from.
BASELINE_CANDIDATES = [RawFetch, JsonBlobExtract, RegexArticleExtract]
