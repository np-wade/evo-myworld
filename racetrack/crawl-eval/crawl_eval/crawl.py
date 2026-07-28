"""Crawl stage — the candidate crawlers + one shared BFS driver.

The driver is identical for every candidate; candidates differ in ONE thing:
how a URL is fetched. Static backends return RAW HTML (JS never runs → the
/item links are invisible). Browser renderers return the POST-JS DOM (the
injected /item links appear). That isolates the exact variable T5 exists to
measure: does executing JS earn its cost?

Politeness, canonicalization, depth-limit and dedup live in the driver so every
candidate is judged on the same rules. One deliberately-impolite candidate
(`*-greedy`) ignores robots.txt to prove the politeness gate bites.

Candidate classes:
  static   : stdlib-bfs (urllib) · curl_cffi-bfs · scrapling-bfs · stdlib-greedy
  browser  : playwright-crawl · crawl4ai-crawl · selenium-crawl   (available()-gated)
Pure stdlib except the gated browser adapters.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
import urllib.robotparser
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .fetchers import ALL_BACKENDS, Backend, backend_by_name

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


# ---------- HTML parsing ----------
class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.canonical: str | None = None
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "a" and d.get("href"):
            self.links.append(d["href"])
        elif tag == "link" and (d.get("rel") or "").lower() == "canonical":
            self.canonical = d.get("href")
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse_page(html: str, base_url: str):
    p = _PageParser()
    try:
        p.feed(html)
    except Exception:
        pass
    links = [urljoin(base_url, h) for h in p.links]
    canon = urljoin(base_url, p.canonical) if p.canonical else None
    body_text = _WS.sub(" ", _TAG.sub(" ", html)).strip().lower()
    return p.title.strip(), body_text, links, canon


# ---------- fetch protocol ----------
@dataclass
class FetchLike:
    ok: bool
    text: str = ""
    error: str = ""


class StaticFetcher:
    """Wraps a raw-HTML Backend."""
    kind = "static"
    def __init__(self, backend: Backend):
        self.backend = backend
        self.name = backend.name
    def available(self) -> bool: return self.backend.available()
    def open(self): pass
    def close(self): pass
    def fetch(self, url: str) -> FetchLike:
        r = self.backend.get(url)
        return FetchLike(r.ok and not r.error, r.text, r.error)


class PlaywrightRenderer:
    """Executes JS. Holds one Chromium page across the whole crawl."""
    kind = "browser"
    name = "playwright"
    def __init__(self):
        self._pw = self._browser = self._page = None
    def available(self) -> bool:
        try:
            import playwright  # noqa: F401
            from playwright.sync_api import sync_playwright  # noqa: F401
            return True
        except Exception:
            return False
    def open(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._ctx = self._browser.new_context(ignore_https_errors=True)
        self._page = self._ctx.new_page()
    def close(self):
        try:
            if self._browser: self._browser.close()
            if self._pw: self._pw.stop()
        except Exception:
            pass
    def fetch(self, url: str) -> FetchLike:
        try:
            self._page.goto(url, wait_until="networkidle", timeout=15000)
            return FetchLike(True, self._page.content())
        except Exception as e:
            return FetchLike(False, "", str(e))


class Crawl4aiRenderer:
    """crawl4ai single-URL render (its DOM output feeds our uniform driver)."""
    kind = "browser"
    name = "crawl4ai"
    def __init__(self):
        self._loop = self._crawler = None
    def available(self) -> bool:
        try:
            import crawl4ai  # noqa: F401
            return True
        except Exception:
            return False
    def open(self):
        import asyncio
        from crawl4ai import AsyncWebCrawler, BrowserConfig
        self._loop = asyncio.new_event_loop()
        self._crawler = AsyncWebCrawler(
            config=BrowserConfig(headless=True, verbose=False,
                                 ignore_https_errors=True))
        self._loop.run_until_complete(self._crawler.__aenter__())
    def close(self):
        try:
            if self._crawler:
                self._loop.run_until_complete(
                    self._crawler.__aexit__(None, None, None))
            if self._loop:
                self._loop.close()
        except Exception:
            pass
    def fetch(self, url: str) -> FetchLike:
        # word_count_threshold=0 + verbose off: don't let crawl4ai's small-page
        # "bot detection" flag our tiny authored pages; we still get raw .html.
        try:
            from crawl4ai import CacheMode, CrawlerRunConfig
            cfg = CrawlerRunConfig(word_count_threshold=0,
                                   cache_mode=CacheMode.BYPASS, verbose=False)
            res = self._loop.run_until_complete(
                self._crawler.arun(url=url, config=cfg))
            html = getattr(res, "html", "") or getattr(res, "cleaned_html", "")
            return FetchLike(bool(html), html)
        except Exception as e:
            return FetchLike(False, "", str(e))


class JsdomRenderer:
    """Pure-JS DOM engine via Node + jsdom. Executes page scripts (so the
    JS-nav links appear) WITHOUT a real browser or system libs — the
    space-light way to put a JS-executing engine on the track."""
    kind = "browser"
    name = "jsdom"
    _script = Path(__file__).parent / "render_jsdom.js"
    _root = Path(__file__).parent.parent          # holds node_modules/
    def available(self) -> bool:
        return bool(shutil.which("node")) and self._script.exists() and \
            (self._root / "node_modules" / "jsdom").exists()
    def open(self): pass
    def close(self): pass
    def fetch(self, url: str) -> FetchLike:
        try:
            import os
            env = {**os.environ, "NODE_TLS_REJECT_UNAUTHORIZED": "0"}
            p = subprocess.run(["node", "--no-warnings", str(self._script), url],
                               cwd=str(self._root), capture_output=True,
                               timeout=30, env=env)
            if p.returncode != 0:
                return FetchLike(False, "", p.stderr.decode()[:200])
            return FetchLike(True, p.stdout.decode("utf-8", "replace"))
        except Exception as e:
            return FetchLike(False, "", str(e))


class SeleniumRenderer:
    kind = "browser"
    name = "selenium"
    def __init__(self):
        self._drv = None
    def available(self) -> bool:
        try:
            import selenium  # noqa: F401
            from selenium import webdriver  # noqa: F401
            return True
        except Exception:
            return False
    def open(self):
        from selenium import webdriver
        opts = webdriver.ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--allow-insecure-localhost")
        self._drv = webdriver.Chrome(options=opts)
    def close(self):
        try:
            if self._drv: self._drv.quit()
        except Exception:
            pass
    def fetch(self, url: str) -> FetchLike:
        try:
            self._drv.get(url)
            time.sleep(0.3)  # let injectors run
            return FetchLike(True, self._drv.page_source)
        except Exception as e:
            return FetchLike(False, "", str(e))


# ---------- candidate = fetcher + crawl policy ----------
@dataclass
class CrawlCandidate:
    name: str
    fetcher: object
    canonicalize: bool = True
    respect_robots: bool = True
    def available(self) -> bool: return self.fetcher.available()
    @property
    def kind(self) -> str: return self.fetcher.kind


def build_candidates() -> list[CrawlCandidate]:
    cands: list[CrawlCandidate] = []
    for b in ALL_BACKENDS:
        cands.append(CrawlCandidate(f"{b.name}-bfs", StaticFetcher(b)))
    # impolite variant of the baseline: ignores robots + doesn't dedup
    cands.append(CrawlCandidate("stdlib-greedy",
                                StaticFetcher(backend_by_name("urllib")),
                                canonicalize=False, respect_robots=False))
    for r in (PlaywrightRenderer(), JsdomRenderer(), Crawl4aiRenderer(),
              SeleniumRenderer()):
        cands.append(CrawlCandidate(f"{r.name}-crawl", r))
    return cands


# ---------- the shared BFS driver ----------
@dataclass
class CrawlOut:
    found: set = field(default_factory=set)      # canonical identities
    pages: dict = field(default_factory=dict)     # identity -> {title, body_text}
    depth_reached: int = 0
    requests: int = 0
    forbidden_hits: list = field(default_factory=list)
    latency_ms: float = 0.0
    pages_crawled: int = 0        # successful fetches = "turns" completed
    stop_reason: str = ""         # exhausted | budget | timeout | error
    error: str = ""


def crawl_site(cand: CrawlCandidate, base: str, server, max_depth: int = 6,
               max_pages: int = 100, polite_s: float = 0.0, seed: str = "/",
               max_seconds: float | None = None) -> CrawlOut:
    out = CrawlOut()
    server.reset()
    # robots
    rp = urllib.robotparser.RobotFileParser()
    try:
        import urllib.request as u
        rp.parse(u.urlopen(base + "/robots.txt", timeout=5)
                 .read().decode().splitlines())
    except Exception:
        rp = None

    same_host = urlsplit(base).netloc
    t0 = time.perf_counter()
    try:
        cand.fetcher.open()
    except Exception as e:
        out.error = f"open: {type(e).__name__}: {e}"
        return out

    seed_url = base + seed if seed.startswith("/") else seed
    queue = [(seed_url, 0)]
    visited: set[str] = set()
    fetched = 0
    out.stop_reason = "exhausted"
    try:
        while queue:
            if len(visited) >= max_pages:
                out.stop_reason = "budget"
                break
            if max_seconds and (time.perf_counter() - t0) >= max_seconds:
                out.stop_reason = "timeout"
                break
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            path = urlsplit(url).path or "/"
            if cand.respect_robots and rp and not rp.can_fetch("*", url):
                continue  # polite: don't fetch a disallowed path
            r = cand.fetcher.fetch(url)
            if polite_s:
                time.sleep(polite_s)
            if not r.ok:
                if not out.error:
                    out.error = r.error
                continue
            fetched += 1
            title, body, links, canon = parse_page(r.text, url)
            identity = canon if (cand.canonicalize and canon) else url
            out.found.add(identity)
            out.pages[identity] = {"title": title, "body_text": body}
            out.depth_reached = max(out.depth_reached, depth)
            if depth < max_depth:
                for l in links:
                    if urlsplit(l).netloc == same_host and l not in visited:
                        queue.append((l, depth + 1))
    except Exception as e:
        out.stop_reason = "error"
        out.error = out.error or f"{type(e).__name__}: {e}"
    finally:
        cand.fetcher.close()

    out.pages_crawled = fetched
    out.latency_ms = (time.perf_counter() - t0) * 1000
    out.requests = server.request_count()
    out.forbidden_hits = server.forbidden_hits()
    return out
