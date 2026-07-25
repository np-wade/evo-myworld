"""Class-3 (full engine / orchestrator) adapters, weight_class = ENGINE.

Four candidates, each wrapping a real donor engine faithfully:

- Crawl4aiEngine (name="crawl4ai")
    Donor: unclecode/crawl4ai
      .../repos/unclecode_crawl4ai/code/crawl4ai/async_webcrawler.py
        -> `class AsyncWebCrawler`; `async def arun(self, url, config=None, **kw)
           -> CrawlResultContainer` (proxies CrawlResult: `.html`, `.markdown`,
           `.success`, `.status_code`). Usage per README:
             `async with AsyncWebCrawler() as crawler:
                  result = await crawler.arun(url=...); print(result.markdown)`
      .../repos/unclecode_crawl4ai/code/crawl4ai/models.py
        -> `MarkdownGenerationResult(raw_markdown, fit_markdown, ...)`;
           `CrawlResult.markdown` is that object (str(...) == raw_markdown),
           `CrawlResult.cleaned_html`. We run the coroutine via `asyncio.run`.

- HeadlessXEngine (name="headlessx") — HTTP service
    Donor: saifyxpro/HeadlessX
      .../repos/saifyxpro_HeadlessX/code/apps/api/src/routes/v1.ts
        -> `router.post('/html', ScrapeController.getHtml)` (also /html-js,
           /content); mounted under /api. Auth via ApiKeyGuard.
      .../repos/saifyxpro_HeadlessX/code/apps/api/src/controllers/scrape/ScrapeControllerV2.ts
        -> body `{ url }` (zod ScrapeRequestSchema), response JSON
           `{ url, html, metadata: { statusCode } }`.

- BrowserlessEngine (name="browserless") — HTTP service
    Donor: browserless/browserless
      .../repos/browserless_browserless/code/src/shared/content.http.ts
        -> POST /content (path [chromiumContent, content]); body `{ url | html }`;
           `description = 'Given a "url" or "html" field, runs and returns HTML
           content after the page has loaded'`; `ResponseSchema = string`
           (contentTypes = [html]) — the body IS the rendered HTML.
      .../repos/browserless_browserless/code/src/shared/scrape.http.ts
        -> POST /scrape (elements selector -> JSON) — the alt endpoint.

- ScrapegraphEngine (name="scrapegraph-ai")
    Donor: ScrapeGraphAI/Scrapegraph-ai
      .../repos/ScrapeGraphAI_Scrapegraph-ai/code/scrapegraphai/graphs/smart_scraper_graph.py
        -> `class SmartScraperGraph`; `run() -> str` executes the graph and
           returns `final_state["answer"]` (the extracted structure).
      .../repos/ScrapeGraphAI_Scrapegraph-ai/code/scrapegraphai/graphs/abstract_graph.py
        -> constructor `SmartScraperGraph(prompt=, source=, config=)` (source is a
           URL *or* already-downloaded HTML), `get_execution_info()`.
      .../repos/ScrapeGraphAI_Scrapegraph-ai/code/scrapegraphai/graphs/base_graph.py
        -> execution_info rows carry `total_tokens` / `prompt_tokens` (the cost
           axis). ScrapegraphEngine is really an extractor too, so it also
           implements `extract(html, task)` (source=html) — but its weight_class
           stays ENGINE and fetch() is the primary path.

Offline / available() policy (per build brief + Hard rule #4)
-------------------------------------------------------------
* crawl4ai / scrapegraph-ai gate available() on importing their python package
  (absent on this box -> available() == False, candidate skipped & recorded).
* headlessx / browserless are HTTP services: available() returns True iff their
  base-URL env var (HEADLESSX_URL / BROWSERLESS_URL) is set. Reachability is NOT
  required at available()-time; an actual reach failure at fetch() yields a clean
  FetchResult(ok=False), never a crash.
* Every fixture `file://` URL is handled first, needs zero third-party deps: read
  the file, strip to text, artifacts={"engine": <name>}. This lets the frozen
  tiers exercise each adapter regardless of what's installed.
* All live calls are funnelled through module-level `_live_*` indirections so the
  tests can monkeypatch them (or sys.modules) with no network / no heavy deps.
"""

from __future__ import annotations

import asyncio
import html as htmlmod
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from ..interface import (
    Candidate,
    ExtractResult,
    FetchResult,
    Task,
    WeightClass,
)

# --- pure-stdlib tag stripping / block heuristics (local to this module) -------
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_SCRIPT_STYLE = re.compile(r"<(script|style|template)[^>]*>.*?</\1>", re.S | re.I)

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
    """HTML -> visible text (pure stdlib): drop <script>/<style>/<template>
    bodies, remove remaining tags, unescape entities, collapse whitespace."""
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


def _file_result(url: str, engine: str, t0: float) -> FetchResult:
    """Shared file:// path: read fixture, strip, tag with the engine. Zero deps."""
    try:
        html = _read_file_url(url)
    except Exception as exc:  # unreadable fixture is a fetch failure, not a crash
        return FetchResult(ok=False, error=str(exc), blocked=False,
                           latency_ms=(time.perf_counter() - t0) * 1000,
                           artifacts={"engine": engine})
    text = _strip_to_text(html)
    return FetchResult(
        ok=True, html=html, text=text, status=200,
        blocked=_is_blocked(200, html),
        latency_ms=(time.perf_counter() - t0) * 1000,
        bytes_down=len(html.encode("utf-8")),
        artifacts={"engine": engine},
    )


def _pkg_importable(module: str) -> bool:
    """True iff `module` can be imported right now. Never raises."""
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def _md_to_str(md) -> str:
    """crawl4ai `result.markdown` may be a MarkdownGenerationResult (with
    .raw_markdown / .fit_markdown) or a plain str. Normalise to str."""
    if md is None:
        return ""
    if isinstance(md, str):
        return md
    for attr in ("raw_markdown", "fit_markdown"):
        val = getattr(md, attr, None)
        if val:
            return val
    return str(md)


def _sum_tokens(exec_info) -> int:
    """Sum `total_tokens` across a scrapegraph execution_info (list of per-node
    dicts, or a single dict). Defensive: unknown shapes -> 0."""
    total = 0
    rows = exec_info if isinstance(exec_info, list) else [exec_info]
    for row in rows:
        if isinstance(row, dict):
            try:
                total += int(row.get("total_tokens") or 0)
            except (TypeError, ValueError):
                continue
    return total


# --- live-call indirections (import deps lazily; tests monkeypatch these) ------
def _make_crawl4ai_crawler():
    """Construct a crawl4ai AsyncWebCrawler. Imported lazily so the module loads
    without the dep; tests monkeypatch this to inject a fake crawler."""
    from crawl4ai import AsyncWebCrawler  # noqa: WPS433 (lazy heavy dep)

    return AsyncWebCrawler()


async def _acrawl(url: str):
    """Faithful crawl4ai usage: `async with AsyncWebCrawler() as c: await c.arun`."""
    crawler = _make_crawl4ai_crawler()
    async with crawler as c:
        return await c.arun(url=url)


def _live_crawl4ai_fetch(url: str, timeout: float):
    """Drive the crawl4ai coroutine to completion via asyncio.run and return the
    CrawlResult(-like) object (`.html`, `.markdown`, `.success`, `.status_code`)."""
    return asyncio.run(_acrawl(url))


def _http_post_json(base_url: str, path: str, payload: dict, token: str,
                    token_param: str, timeout: float):
    """POST JSON to base_url+path with an optional `?<token_param>=<token>` query.
    Returns (status:int, body:str). Isolated so tests fake urlopen / this fn."""
    url = base_url.rstrip("/") + path
    if token:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{token_param}={token}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "Accept": "*/*"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # live call
        status = int(getattr(resp, "status", 0) or resp.getcode() or 0)
        body = resp.read().decode("utf-8", "replace")
    return status, body


def _live_headlessx_fetch(base_url: str, url: str, token: str, timeout: float):
    """HeadlessX: POST /api/html {url} -> JSON {url, html, metadata:{statusCode}}."""
    return _http_post_json(base_url, "/api/html", {"url": url}, token, "token", timeout)


def _live_browserless_fetch(base_url: str, url: str, token: str, timeout: float):
    """browserless: POST /content {url} -> rendered HTML (response body is HTML)."""
    return _http_post_json(base_url, "/content", {"url": url}, token, "token", timeout)


def _live_scrapegraph_run(prompt: str, source: str, config: dict):
    """Build a SmartScraperGraph(prompt, source, config), run it, and return
    (answer, execution_info). `source` is a URL (fetch path) or HTML (extract)."""
    from scrapegraphai.graphs import SmartScraperGraph  # noqa: WPS433 (lazy dep)

    graph = SmartScraperGraph(prompt=prompt, source=source, config=config)
    answer = graph.run()
    return answer, graph.get_execution_info()


def _scrapegraph_prompt(task: Task) -> str:
    """Turn a task.schema into a SmartScraper prompt. Explicit `prompt` wins;
    else name the requested fields; else fall back to the query / a generic ask."""
    schema = task.schema or {}
    if schema.get("prompt"):
        return str(schema["prompt"])
    fields = schema.get("fields")
    if fields:
        return "Extract the following fields as JSON: " + ", ".join(map(str, fields))
    if task.query:
        return task.query
    return "Extract the main structured content of the page as JSON."


def _scrapegraph_config(task: Task) -> dict:
    """LLM config for SmartScraperGraph. task.meta['scrapegraph_config'] wins;
    else a minimal openai config from env (api_key may be empty on this box)."""
    cfg = task.meta.get("scrapegraph_config")
    if isinstance(cfg, dict) and cfg:
        return cfg
    return {
        "llm": {
            "model": os.getenv("SCRAPEGRAPH_MODEL", "openai/gpt-4o-mini"),
            "api_key": os.getenv("OPENAI_API_KEY", ""),
        },
        "verbose": False,
    }


def _answer_to_fields(answer) -> dict:
    """Normalise a SmartScraper answer into a fields dict."""
    if isinstance(answer, dict):
        return answer
    return {"answer": answer}


def _timeout(task: Task) -> float:
    return float(task.meta.get("timeout", 30))


# --------------------------------------------------------------------------- #
# crawl4ai
# --------------------------------------------------------------------------- #
class Crawl4aiEngine(Candidate):
    """Full crawl+markdown engine (unclecode/crawl4ai AsyncWebCrawler)."""

    name = "crawl4ai"
    weight_class = WeightClass.ENGINE
    requires: list[str] = ["crawl4ai"]

    def available(self) -> bool:
        return _pkg_importable("crawl4ai")

    def fetch(self, task: Task) -> FetchResult:
        t0 = time.perf_counter()
        if task.url.startswith("file://"):
            return _file_result(task.url, self.name, t0)

        try:
            result = _live_crawl4ai_fetch(task.url, timeout=_timeout(task))
        except ImportError:
            return FetchResult(ok=False, blocked=False,
                               error="crawl4ai not installed",
                               latency_ms=(time.perf_counter() - t0) * 1000,
                               artifacts={"engine": self.name})
        except Exception as exc:
            return FetchResult(ok=False, error=str(exc), blocked=False,
                               latency_ms=(time.perf_counter() - t0) * 1000,
                               artifacts={"engine": self.name})

        html = getattr(result, "html", None) or getattr(result, "cleaned_html", "") or ""
        markdown = _md_to_str(getattr(result, "markdown", None))
        text = markdown or _strip_to_text(html)
        status = int(getattr(result, "status_code", 0) or 200)
        success = getattr(result, "success", True)
        return FetchResult(
            ok=bool(success),
            html=html, text=text, status=status,
            blocked=_is_blocked(status, html),
            latency_ms=(time.perf_counter() - t0) * 1000,
            bytes_down=len(html.encode("utf-8")),
            artifacts={"engine": self.name, "markdown": markdown},
        )


# --------------------------------------------------------------------------- #
# HeadlessX (HTTP service)
# --------------------------------------------------------------------------- #
class HeadlessXEngine(Candidate):
    """Headless browser API service (saifyxpro/HeadlessX), POST /api/html."""

    name = "headlessx"
    weight_class = WeightClass.ENGINE
    requires: list[str] = ["http-service"]

    def available(self) -> bool:
        # Env presence only; reachability is proven (or not) at fetch time.
        return bool(os.getenv("HEADLESSX_URL"))

    def fetch(self, task: Task) -> FetchResult:
        t0 = time.perf_counter()
        if task.url.startswith("file://"):
            return _file_result(task.url, self.name, t0)

        base = os.getenv("HEADLESSX_URL")
        if not base:
            return FetchResult(ok=False, blocked=False,
                               error="HEADLESSX_URL not set",
                               latency_ms=(time.perf_counter() - t0) * 1000,
                               artifacts={"engine": self.name})
        token = os.getenv("HEADLESSX_TOKEN", "")
        try:
            status, body = _live_headlessx_fetch(base, task.url, token, _timeout(task))
        except Exception as exc:  # unreachable / bad response -> ok=False, no crash
            return FetchResult(ok=False, error=str(exc), blocked=False,
                               latency_ms=(time.perf_counter() - t0) * 1000,
                               artifacts={"engine": self.name})

        html, inner_status = self._parse(body, status)
        eff_status = inner_status or status
        return FetchResult(
            ok=True, html=html, text=_strip_to_text(html), status=eff_status,
            blocked=_is_blocked(eff_status, html),
            latency_ms=(time.perf_counter() - t0) * 1000,
            bytes_down=len(html.encode("utf-8")),
            artifacts={"engine": self.name},
        )

    @staticmethod
    def _parse(body: str, http_status: int):
        """HeadlessX returns JSON {html, metadata:{statusCode}}; tolerate a raw
        HTML body too. Returns (html, inner_status)."""
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return body, 0
        if isinstance(data, dict):
            html = data.get("html", "") or ""
            meta = data.get("metadata") or {}
            inner = int(meta.get("statusCode") or 0) if isinstance(meta, dict) else 0
            return html, inner
        return body, 0


# --------------------------------------------------------------------------- #
# browserless (HTTP service)
# --------------------------------------------------------------------------- #
class BrowserlessEngine(Candidate):
    """headless-chrome-as-a-service (browserless/browserless), POST /content."""

    name = "browserless"
    weight_class = WeightClass.ENGINE
    requires: list[str] = ["http-service"]

    def available(self) -> bool:
        return bool(os.getenv("BROWSERLESS_URL"))

    def fetch(self, task: Task) -> FetchResult:
        t0 = time.perf_counter()
        if task.url.startswith("file://"):
            return _file_result(task.url, self.name, t0)

        base = os.getenv("BROWSERLESS_URL")
        if not base:
            return FetchResult(ok=False, blocked=False,
                               error="BROWSERLESS_URL not set",
                               latency_ms=(time.perf_counter() - t0) * 1000,
                               artifacts={"engine": self.name})
        token = os.getenv("BROWSERLESS_TOKEN", "")
        try:
            status, body = _live_browserless_fetch(base, task.url, token, _timeout(task))
        except Exception as exc:
            return FetchResult(ok=False, error=str(exc), blocked=False,
                               latency_ms=(time.perf_counter() - t0) * 1000,
                               artifacts={"engine": self.name})

        # /content's ResponseSchema is `string` — the body IS the rendered HTML.
        html = body
        return FetchResult(
            ok=True, html=html, text=_strip_to_text(html), status=status,
            blocked=_is_blocked(status, html),
            latency_ms=(time.perf_counter() - t0) * 1000,
            bytes_down=len(html.encode("utf-8")),
            artifacts={"engine": self.name},
        )


# --------------------------------------------------------------------------- #
# Scrapegraph-ai (LLM extraction engine; also an extractor)
# --------------------------------------------------------------------------- #
class ScrapegraphEngine(Candidate):
    """SmartScraperGraph LLM extraction pipeline (ScrapeGraphAI/Scrapegraph-ai).

    fetch() is the primary path (source=URL); extract() reuses the same graph on
    already-downloaded HTML. Extracted fields land in artifacts['fields'] and the
    LLM token spend on FetchResult.llm_tokens (the cost axis)."""

    name = "scrapegraph-ai"
    weight_class = WeightClass.ENGINE
    requires: list[str] = ["scrapegraphai"]

    def available(self) -> bool:
        return _pkg_importable("scrapegraphai")

    def fetch(self, task: Task) -> FetchResult:
        t0 = time.perf_counter()
        if task.url.startswith("file://"):
            # Fixture path: read + strip so frozen tiers still exercise the adapter.
            return _file_result(task.url, self.name, t0)

        prompt = _scrapegraph_prompt(task)
        config = _scrapegraph_config(task)
        try:
            answer, exec_info = _live_scrapegraph_run(prompt, task.url, config)
        except ImportError:
            return FetchResult(ok=False, blocked=False,
                               error="scrapegraphai not installed",
                               latency_ms=(time.perf_counter() - t0) * 1000,
                               artifacts={"engine": self.name})
        except Exception as exc:
            return FetchResult(ok=False, error=str(exc), blocked=False,
                               latency_ms=(time.perf_counter() - t0) * 1000,
                               artifacts={"engine": self.name})

        fields = _answer_to_fields(answer)
        tokens = _sum_tokens(exec_info)
        text = json.dumps(fields, ensure_ascii=False) if isinstance(answer, dict) else str(answer)
        return FetchResult(
            ok=True, html="", text=text, status=200, blocked=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
            llm_tokens=tokens,
            artifacts={"engine": self.name, "fields": fields},
        )

    def extract(self, html: str, task: Task) -> ExtractResult:
        """Run SmartScraperGraph over already-downloaded HTML (source=html)."""
        prompt = _scrapegraph_prompt(task)
        config = _scrapegraph_config(task)
        try:
            answer, _exec_info = _live_scrapegraph_run(prompt, html, config)
        except ImportError:
            return ExtractResult(ok=False, error="scrapegraphai not installed",
                                 text=_strip_to_text(html))
        except Exception as exc:
            return ExtractResult(ok=False, error=str(exc), text=_strip_to_text(html))

        fields = _answer_to_fields(answer)
        text = json.dumps(fields, ensure_ascii=False) if isinstance(answer, dict) else str(answer)
        return ExtractResult(ok=True, fields=fields, text=text)


# Bulk-registered by adapters._autodiscover() via this module-level list.
CANDIDATES = [Crawl4aiEngine, HeadlessXEngine, BrowserlessEngine, ScrapegraphEngine]
