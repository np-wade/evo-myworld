"""Stage 4 — Extract: post-page HTML -> clean markdown. OFFLINE (runs on the
frozen fixture HTML; no network).

Candidates (available()-gated):

  css-rules    -- slice Substack's `available-content` container (stopping at
                  the paywall widget), convert with a stdlib html->md walker.
                  Pure stdlib baseline: always runnable.
  readability  -- readability-lxml Document.summary() -> same md walker.
  trafilatura  -- trafilatura.extract(output_format=markdown).

Score per FREE post that has RSS full-content gold: content fidelity
(normalized token Dice similarity vs the RSS body), title accuracy, latency.
Paid posts are excluded here (their RSS gold is a preview); paywall honesty is
scored at pipeline level.

Also home of detect_paywall() — the app path's honest-truncation signal,
read from the page itself (paywall widget markup / JSON-LD
isAccessibleForFree) — and extract_fields() for the report table.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from html.parser import HTMLParser
from pathlib import Path

from .oracle import DEFAULT_PUBS, Oracle, norm_text

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ---------- shared page-level helpers (normal scraping of the page itself) ---

def detect_paywall(html: str) -> bool:
    """Is this post page truncated by a paywall? Read from the page: Substack
    renders a `paywall` widget and stamps JSON-LD isAccessibleForFree=false."""
    if re.search(r'class="[^"]*\bpaywall\b', html) or "paywall-title" in html:
        return True
    m = re.search(r'"isAccessibleForFree"\s*:\s*(false|"False")', html)
    return bool(m)


def extract_fields(html: str) -> dict:
    """Table fields from the post page itself (JSON-LD + metas)."""
    out = {"title": "", "date": "", "author": "", "url": ""}
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                  html, re.S)
    if m:
        try:
            d = json.loads(m.group(1))
            out["title"] = d.get("headline", "") or ""
            out["date"] = (d.get("datePublished", "") or "")[:10]
            a = d.get("author") or []
            if isinstance(a, dict):
                a = [a]
            out["author"] = ", ".join(x.get("name", "") for x in a if x)
        except Exception:
            pass
    if not out["title"]:
        m = re.search(r'<meta property="og:title" content="([^"]*)"', html)
        out["title"] = m.group(1) if m else ""
    if not out["author"]:
        m = re.search(r'<meta name="author" content="([^"]*)"', html)
        out["author"] = m.group(1) if m else ""
    m = re.search(r'<link rel="canonical" href="([^"]*)"', html)
    out["url"] = m.group(1) if m else ""
    return out


# ---------- stdlib html -> markdown walker -----------------------------------

_SKIP = {"script", "style", "button", "svg", "form", "iframe", "audio",
         "video", "figcaption", "noscript"}
_SKIP_CLASS = ("subscription-widget", "subscribe-widget", "button-wrapper",
               "paywall", "share-dialog", "image-link-expand", "poll-embed")


class _MD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip_depth = 0
        self.skip_tag_depth = 0
        self.href = ""
        self.list_stack: list[str] = []
        self.in_pre = False

    def _cls(self, attrs) -> str:
        return dict(attrs).get("class", "") or ""

    def handle_starttag(self, tag, attrs):
        if self.skip_depth or self.skip_tag_depth:
            if tag not in ("br", "img", "hr", "input", "meta", "link"):
                if self.skip_depth: self.skip_depth += 1
                else: self.skip_tag_depth += 1
            return
        cls = self._cls(attrs)
        if tag in _SKIP:
            self.skip_tag_depth = 1
            return
        if any(c in cls for c in _SKIP_CLASS):
            self.skip_depth = 1
            return
        a = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self.out.append("\n\n")
        elif tag in ("ul", "ol"):
            self.list_stack.append(tag)
        elif tag == "li":
            mark = "1." if (self.list_stack and self.list_stack[-1] == "ol") \
                else "-"
            self.out.append(f"\n{'  ' * (len(self.list_stack) - 1)}{mark} ")
        elif tag == "blockquote":
            self.out.append("\n\n> ")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "a":
            self.href = a.get("href", "")
            self.out.append("[")
        elif tag == "img":
            src = a.get("src", "")
            if src:
                self.out.append(f"![{a.get('alt', '')}]({src})")
        elif tag == "br":
            self.out.append("\n")
        elif tag == "hr":
            self.out.append("\n\n---\n\n")
        elif tag == "pre":
            self.in_pre = True
            self.out.append("\n\n```\n")
        elif tag == "code" and not self.in_pre:
            self.out.append("`")

    def handle_endtag(self, tag):
        if self.skip_tag_depth:
            if tag not in ("br", "img", "hr", "input", "meta", "link"):
                self.skip_tag_depth -= 1
            return
        if self.skip_depth:
            if tag not in ("br", "img", "hr", "input", "meta", "link"):
                self.skip_depth -= 1
            return
        if tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "a":
            self.out.append(f"]({self.href})" if self.href else "]()")
            self.href = ""
        elif tag in ("ul", "ol") and self.list_stack:
            self.list_stack.pop()
        elif tag == "pre":
            self.in_pre = False
            self.out.append("\n```\n")
        elif tag == "code" and not self.in_pre:
            self.out.append("`")

    def handle_data(self, data):
        if self.skip_depth or self.skip_tag_depth:
            return
        self.out.append(data if self.in_pre else re.sub(r"\s+", " ", data))


def html_to_md(fragment: str) -> str:
    p = _MD()
    p.feed(fragment)
    md = "".join(p.out)
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


# ---------- extractor candidates ---------------------------------------------

_BODY = re.compile(
    r'class="available-content"[^>]*>(.*?)'
    r'(?:<div[^>]+class="[^"]*\bpaywall\b|</article>)', re.S)
_BODY_FALLBACK = re.compile(
    r'class="body markup"[^>]*>(.*?)</div>\s*</div>', re.S)


class Extractor:
    key = "?"
    def available(self) -> bool: return False
    def extract(self, html: str) -> dict: ...   # {"markdown", "title"}


class CssRules(Extractor):
    """Slice Substack's available-content container; stdlib md walker."""
    key = "css-rules"
    def available(self) -> bool: return True
    def extract(self, html: str) -> dict:
        m = _BODY.search(html) or _BODY_FALLBACK.search(html)
        frag = m.group(1) if m else ""
        return {"markdown": html_to_md(frag),
                "title": extract_fields(html)["title"]}


class Readability(Extractor):
    """readability-lxml main-content pick -> stdlib md walker."""
    key = "readability"
    def available(self) -> bool:
        try:
            import readability  # noqa: F401
            return True
        except Exception:
            return False
    def extract(self, html: str) -> dict:
        from readability import Document
        doc = Document(html)
        return {"markdown": html_to_md(doc.summary(html_partial=True)),
                "title": doc.short_title()}


class Trafilatura(Extractor):
    """trafilatura extraction straight to markdown."""
    key = "trafilatura"
    def available(self) -> bool:
        try:
            import trafilatura  # noqa: F401
            return True
        except Exception:
            return False
    def extract(self, html: str) -> dict:
        import trafilatura
        md = trafilatura.extract(html, output_format="markdown",
                                 include_comments=False,
                                 include_tables=True) or ""
        return {"markdown": md, "title": extract_fields(html)["title"]}


ALL_EXTRACTORS = [CssRules(), Readability(), Trafilatura()]


def extractor_by_key(key: str) -> Extractor:
    for e in ALL_EXTRACTORS:
        if e.key == key and e.available():
            return e
    return CssRules()


# ---------- the offline race -------------------------------------------------

def extract_race(pubs: list[str] | None = None, sample: int = 0) -> dict:
    """Race extractors over every fixture HTML of a FREE post with RSS gold."""
    cases = []   # (pub, slug, html, gold_rss)
    for pub in pubs or DEFAULT_PUBS:
        try:
            o = Oracle(pub)
        except FileNotFoundError:
            continue
        for slug, g in o.posts.items():
            if g.get("audience") == "only_paid":
                continue
            html = o.fixture_html(slug)
            gold = o.rss_html(slug)
            if html and gold:
                cases.append((pub, slug, html, gold))
    if sample:
        cases = cases[:sample]

    from .oracle import similarity
    rows, skipped = [], []
    for ex in ALL_EXTRACTORS:
        if not ex.available():
            skipped.append(ex.key)
            continue
        fids, lat, terr, fails, err = [], [], 0, 0, ""
        for pub, slug, html, gold in cases:
            t0 = time.perf_counter()
            try:
                out = ex.extract(html)
            except Exception as e:
                fails += 1
                err = f"{slug}: {type(e).__name__}: {e}"
                fids.append(0.0)
                lat.append((time.perf_counter() - t0) * 1000)
                continue
            lat.append((time.perf_counter() - t0) * 1000)
            fids.append(similarity(gold, out["markdown"]))
            gt = Oracle(pub).posts[slug]["title"]
            if norm_text(out["title"]) != norm_text(gt):
                terr += 1
        n = len(cases)
        rows.append({
            "extractor": ex.key, "posts": n, "fails": fails,
            "fidelity_mean": round(statistics.mean(fids), 4) if fids else 0.0,
            "fidelity_med": round(statistics.median(fids), 4) if fids else 0.0,
            "title_acc": round((n - terr) / n, 4) if n else 0.0,
            "p50_ms": round(statistics.median(lat), 1) if lat else 0.0,
            "error": err,
        })
    rows.sort(key=lambda r: (-r["fidelity_mean"], r["p50_ms"]))
    return {"pubs": pubs or DEFAULT_PUBS, "posts": len(cases),
            "extractors_skipped": skipped, "leaderboard": rows}


def format_extract_leaderboard(res: dict) -> str:
    L = [f"stage-4 extract race — {res['posts']} free fixture posts across "
         f"{', '.join(res['pubs'])} (fidelity = token-Dice vs RSS gold)", ""]
    hdr = (f"{'extractor':12} {'fid-mean':>9} {'fid-med':>8} {'title':>7} "
           f"{'p50ms':>8} {'fails':>6}")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        L.append(f"{r['extractor']:12} {r['fidelity_mean']:9.3f} "
                 f"{r['fidelity_med']:8.3f} {r['title_acc']:7.3f} "
                 f"{r['p50_ms']:8.1f} {r['fails']:6d}"
                 + (f"  err: {r['error'][:50]}" if r["error"] else ""))
    if res["extractors_skipped"]:
        L.append(f"skipped: {', '.join(res['extractors_skipped'])}")
    return "\n".join(L)
