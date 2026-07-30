"""Discovery candidates — normal-scraping paths that turn the prompt into a set
of arXiv IDs for 2026-07-14. Two sub-brackets:

  LISTING  -- scrape arxiv.org/list/<cat>/<YYYY-MM> HTML (paginate), keep IDs.
  SERP     -- scrape a search engine's result page for site:arxiv.org queries.

A candidate = strategy x fetch-backend, so "which engine/path pulls arXiv
fastest" is raced with the backend that carries it. available()-gated: a
candidate with no working backend / unreachable service SKIPS.

NO arXiv API is used here. The API is only in oracle.py (the grader).
"""
from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass, field

from .fetchers import Backend, FetchOut

CATS = ["cs.LG", "cs.AI", "cs.CL"]
MONTH = "2026-07"
DATE = "2026-07-14"
ID_RE = re.compile(r"(\d{4}\.\d{4,5})")


@dataclass
class DiscoverOut:
    ok: bool
    ids: set[str] = field(default_factory=set)
    latency_ms: float = 0.0
    bytes_down: int = 0
    requests: int = 0
    blocked: bool = False
    error: str = ""
    note: str = ""
    # id -> announcement date ("YYYY-MM-DD") when the source page exposes it
    # (listing pages group entries under day headings; SERPs don't).
    id_dates: dict[str, str] = field(default_factory=dict)
    # id -> {"title": ..., "authors": [...]} scraped from listing entries
    id_meta: dict[str, dict] = field(default_factory=dict)


def _ids_from(text: str) -> set[str]:
    # arXiv:2607.12345 / /abs/2607.12345 / /pdf/2607.12345
    out = set()
    for m in re.finditer(r"(?:arXiv:|/abs/|/pdf/)(\d{4}\.\d{4,5})", text):
        out.add(m.group(1))
    return out


_ENTRY = re.compile(
    r'<a href\s*=\s*"/abs/(\d{4}\.\d{4,5})".*?'
    r"list-title[^>]*><span[^>]*>Title:</span>\s*(.*?)\s*</div>.*?"
    r"list-authors[^>]*>(.*?)</div>", re.S)
_ANCHOR_TEXT = re.compile(r">([^<]+)</a>")
_TAG = re.compile(r"<[^>]+>")


def _entries_from(html: str) -> dict[str, dict]:
    """id -> {title, authors} from listing-page entry markup (dt/dd pairs)."""
    out = {}
    for m in _ENTRY.finditer(html):
        title = _TAG.sub("", m.group(2)).strip()
        authors = [a.strip() for a in _ANCHOR_TEXT.findall(m.group(3))]
        out[m.group(1)] = {"title": title, "authors": authors}
    return out


_DAY_HDR = re.compile(r"<h3>\s*\w{3},\s+(\d{1,2}\s+\w{3}\s+\d{4})")
_MONTHS = {m: i + 1 for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}


def _id_dates_from(html: str) -> dict[str, str]:
    """Listing pages group entries under '<h3>Mon, 14 Jul 2026 ...' headings.
    Map each ID to its announcement date (ISO). SERPs have no such structure."""
    out: dict[str, str] = {}
    marks = [(m.start(), m.group(1)) for m in _DAY_HDR.finditer(html)]
    for (start, day), (end, _) in zip(marks, marks[1:] + [(len(html), "")]):
        d, mon, y = day.split()
        iso = f"{y}-{_MONTHS[mon]:02d}-{int(d):02d}"
        for i in _ids_from(html[start:end]):
            out[i] = iso
    return out


class Candidate:
    bracket = "?"
    key = "?"
    def __init__(self, backend: Backend): self.backend = backend
    @property
    def name(self) -> str: return f"{self.key}/{self.backend.name}"
    def available(self) -> bool: return self.backend.available()
    def discover(self) -> DiscoverOut: ...


class ListingScrape(Candidate):
    """Scrape the monthly listing pages and keep every arXiv ID (high recall,
    low precision unless day-filtered). Paginates: show=2000 truncates months
    with >2000 entries per category (cost the first race 36% recall)."""
    bracket = "listing"
    key = "list-month"
    PAGE = 2000
    MAX_PAGES = 5  # safety: 10k entries/cat is beyond any month
    def discover(self) -> DiscoverOut:
        ids, dates, meta = set(), {}, {}
        total_ms, total_b, reqs, blocked, err = 0.0, 0, 0, False, ""
        for cat in CATS:
            for page in range(self.MAX_PAGES):
                url = (f"https://arxiv.org/list/{cat}/{MONTH}"
                       f"?skip={page * self.PAGE}&show={self.PAGE}")
                r: FetchOut = self.backend.get(url)
                reqs += 1; total_ms += r.latency_ms; total_b += r.bytes_down
                if r.blocked: blocked = True
                if not r.ok and not r.text:
                    err = err or r.error
                    break
                page_ids = _ids_from(r.text)
                new = page_ids - ids
                ids |= page_ids
                dates.update(_id_dates_from(r.text))
                meta.update(_entries_from(r.text))
                if len(page_ids) < self.PAGE // 2 or not new:
                    break  # short/duplicate page = past the end
        return DiscoverOut(bool(ids), ids, round(total_ms, 1), total_b, reqs,
                           blocked, err,
                           note="all month IDs + announce dates; stage-2 filters",
                           id_dates=dates, id_meta=meta)


class SerpScrape(Candidate):
    """Scrape a search engine result page for site:arxiv.org queries."""
    bracket = "serp"
    def __init__(self, backend, key, url_tmpl, risky=False, env=None):
        super().__init__(backend)
        self.key = key; self.url_tmpl = url_tmpl
        self.risky = risky; self.env = env
    def available(self) -> bool:
        if not self.backend.available(): return False
        if self.risky and os.environ.get("ARXIV_EVAL_RISKY") != "1": return False
        if self.env and not os.environ.get(self.env): return False
        return True
    def discover(self) -> DiscoverOut:
        q = f'site:arxiv.org {" OR ".join(CATS)} July 2026 local AI inference'
        base = (os.environ.get(self.env) if self.env else "")
        url = self.url_tmpl.format(q=urllib.parse.quote(q), base=base.rstrip("/"))
        r: FetchOut = self.backend.get(url)
        # SERP: pull arxiv links out of result hrefs (uddg= for ddg, plain for others)
        text = urllib.parse.unquote(r.text)
        ids = _ids_from(text)
        return DiscoverOut(r.ok and bool(ids or r.text), ids, round(r.latency_ms, 1),
                           r.bytes_down, 1, r.blocked, r.error,
                           note="SERP recall is inherently partial for exhaustive tasks")


def build_candidates(backends: list[Backend]) -> list[Candidate]:
    cands: list[Candidate] = []
    for b in backends:
        cands.append(ListingScrape(b))
        cands.append(SerpScrape(b, "ddg-serp",
                     "https://html.duckduckgo.com/html/?q={q}"))
        cands.append(SerpScrape(b, "searxng",
                     "{base}/search?q={q}&format=json", env="SEARXNG_URL"))
        cands.append(SerpScrape(b, "google-serp",
                     "https://www.google.com/search?q={q}&num=100", risky=True))
        cands.append(SerpScrape(b, "bing-serp",
                     "https://www.bing.com/search?q={q}&count=50", risky=True))
    return cands
