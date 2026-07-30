"""Discovery candidates — normal-scraping paths that turn the prompt into the
set of post slugs for a newsletter. Three sub-brackets:

  ARCHIVE  -- scrape the /archive HTML page. It is LAZY-LOADED: the static
              HTML carries only the first ~12-20 posts (with <time datetime>
              stamps); scrolling loads more via the archive API, which is
              FORBIDDEN to the app. So a static fetch is inherently partial on
              high-volume pubs — exactly the headless-vs-static question this
              test exists to ask.
  SITEMAP  -- parse /sitemap.xml (urlset or sitemapindex). Full history with
              per-URL <lastmod> dates (lastmod ~= publish date for recent
              posts; an edited old post can leak into the window — precision
              noise, not a bug).
  SERP     -- scrape a search engine's result page for site: queries.

A candidate = strategy x fetch-backend. available()-gated: a candidate with no
working backend / unreachable service SKIPS.

NO Substack API/RSS here. Those live only in oracle.py / fetch_fixtures.py.
"""
from __future__ import annotations

import os
import re
import time
import urllib.parse
from dataclasses import dataclass, field

from .fetchers import Backend, FetchOut

SLUG_RE = re.compile(r"/p/([a-zA-Z0-9_-]+)")


@dataclass
class DiscoverOut:
    ok: bool
    slugs: set[str] = field(default_factory=set)
    latency_ms: float = 0.0
    bytes_down: int = 0
    requests: int = 0
    blocked: bool = False
    error: str = ""
    note: str = ""
    # slug -> "YYYY-MM-DD" when the source exposes a date (archive <time> tags,
    # sitemap <lastmod>); SERPs don't.
    slug_dates: dict[str, str] = field(default_factory=dict)
    # slug -> {"title": ...} when the source exposes it (archive anchor text)
    slug_meta: dict[str, dict] = field(default_factory=dict)


def _post_slugs(text: str) -> set[str]:
    return {m.group(1) for m in SLUG_RE.finditer(text)
            if not m.group(0).endswith("/comments")}


class Candidate:
    bracket = "?"
    key = "?"
    def __init__(self, backend: Backend, base_url: str):
        self.backend = backend
        self.base = base_url.rstrip("/")
    @property
    def name(self) -> str: return f"{self.key}/{self.backend.name}"
    def available(self) -> bool: return self.backend.available()
    def discover(self) -> DiscoverOut: ...


_A_POST = re.compile(r'<a[^>]+href="[^"]*/p/([a-zA-Z0-9_-]+)"[^>]*>(.*?)</a>',
                     re.S)
_TIME = re.compile(r'<time datetime="(\d{4}-\d{2}-\d{2})[^"]*"')
_TAG = re.compile(r"<[^>]+>")


class ArchiveHtmlScrape(Candidate):
    """Static scrape of the lazy-loaded /archive page: first ~12-20 posts with
    dates + titles. Deeper history needs a headless scroller (future cand)."""
    bracket = "archive"
    key = "archive-html"

    def discover(self) -> DiscoverOut:
        r: FetchOut = self.backend.get(f"{self.base}/archive?sort=new")
        slugs, dates, meta = set(), {}, {}
        if r.text:
            # pair each post link with the nearest <time datetime> stamp
            times = [(m.start(), m.group(1)) for m in _TIME.finditer(r.text)]
            for m in _A_POST.finditer(r.text):
                slug = m.group(1)
                if "/comments" in m.group(0):
                    continue
                slugs.add(slug)
                title = " ".join(_TAG.sub(" ", m.group(2)).split())
                if title and slug not in meta:
                    meta[slug] = {"title": title}
                if times and slug not in dates:
                    dates[slug] = min(times,
                                      key=lambda t: abs(t[0] - m.start()))[1]
        return DiscoverOut(bool(slugs), slugs, round(r.latency_ms, 1),
                           r.bytes_down, 1, r.blocked, r.error,
                           note="static slice of a lazy-loaded page — "
                                "partial by construction on busy pubs",
                           slug_dates=dates, slug_meta=meta)


_SM_URL = re.compile(r"<url>\s*<loc>([^<]+)</loc>\s*"
                     r"(?:<lastmod>([^<]+)</lastmod>)?", re.S)
_SM_CHILD = re.compile(r"<sitemap>\s*<loc>([^<]+)</loc>", re.S)


class SitemapScrape(Candidate):
    """Parse /sitemap.xml (handles urlset and sitemapindex): every /p/ URL +
    its <lastmod> date. Exhaustive history in 1-4 requests."""
    bracket = "sitemap"
    key = "sitemap"
    MAX_CHILDREN = 3

    def discover(self) -> DiscoverOut:
        total_ms, total_b, reqs, blocked, err = 0.0, 0, 0, False, ""
        r: FetchOut = self.backend.get(f"{self.base}/sitemap.xml")
        total_ms += r.latency_ms; total_b += r.bytes_down; reqs += 1
        blocked |= r.blocked; err = r.error
        pages = [r.text] if r.text else []
        kids = _SM_CHILD.findall(r.text or "")
        for kid in kids[: self.MAX_CHILDREN]:
            time.sleep(1.5)
            rk = self.backend.get(kid)
            total_ms += rk.latency_ms; total_b += rk.bytes_down; reqs += 1
            blocked |= rk.blocked
            if rk.text:
                pages.append(rk.text)
        slugs, dates = set(), {}
        for page in pages:
            for loc, lastmod in _SM_URL.findall(page):
                m = SLUG_RE.search(loc)
                if not m:
                    continue
                slugs.add(m.group(1))
                if lastmod:
                    dates[m.group(1)] = lastmod[:10]
        return DiscoverOut(bool(slugs), slugs, round(total_ms, 1), total_b,
                           reqs, blocked, err,
                           note="full history + lastmod dates; lastmod of an "
                                "edited old post can leak into the window",
                           slug_dates=dates)


class SerpScrape(Candidate):
    """Scrape a search engine result page for site:<host>/p/ links."""
    bracket = "serp"
    def __init__(self, backend, base_url, key, url_tmpl, risky=False):
        super().__init__(backend, base_url)
        self.key = key; self.url_tmpl = url_tmpl; self.risky = risky
    def available(self) -> bool:
        if not self.backend.available(): return False
        if self.risky and os.environ.get("SUBSTACK_EVAL_RISKY") != "1":
            return False
        return True
    def discover(self) -> DiscoverOut:
        host = urllib.parse.urlparse(self.base).netloc
        q = f"site:{host} inurl:/p/"
        url = self.url_tmpl.format(q=urllib.parse.quote(q))
        r: FetchOut = self.backend.get(url)
        text = urllib.parse.unquote(r.text)  # uddg= wrapped hrefs on ddg
        slugs = _post_slugs(text)
        return DiscoverOut(r.ok and bool(slugs or r.text), slugs,
                           round(r.latency_ms, 1), r.bytes_down, 1,
                           r.blocked, r.error,
                           note="SERP recall is inherently partial for "
                                "exhaustive tasks; no dates")


def build_candidates(backends: list[Backend], base_url: str) -> list[Candidate]:
    cands: list[Candidate] = []
    for b in backends:
        cands.append(ArchiveHtmlScrape(b, base_url))
        cands.append(SitemapScrape(b, base_url))
        cands.append(SerpScrape(b, base_url, "ddg-serp",
                     "https://html.duckduckgo.com/html/?q={q}"))
        cands.append(SerpScrape(b, base_url, "bing-serp",
                     "https://www.bing.com/search?q={q}&count=50", risky=True))
    return cands
