"""Extract stage — page HTML -> {title, body_text}. A light bracket (trafilatura
already won T2's extract race); kept so T5 scores extract fidelity uniformly and
the pipeline has a real extractor slot to optimize.

  rule        : stdlib regex strip (baseline, always available)
  trafilatura : main-content extraction (gated)
  css-json    : title from <title>, body from <p> text (gated on nothing; stdlib)
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


class Extractor:
    name = "base"
    def available(self) -> bool: return False
    def extract(self, html: str) -> dict: return {"title": "", "body_text": ""}


class RuleExtractor(Extractor):
    name = "rule"
    def available(self) -> bool: return True
    def extract(self, html: str) -> dict:
        m = _TITLE.search(html)
        title = _WS.sub(" ", m.group(1)).strip() if m else ""
        body = _WS.sub(" ", _TAG.sub(" ", html)).strip().lower()
        return {"title": title, "body_text": body}


class _PTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.body: list[str] = []
        self._t = self._p = False
    def handle_starttag(self, tag, attrs):
        if tag == "title": self._t = True
        if tag in ("p", "h1"): self._p = True
    def handle_endtag(self, tag):
        if tag == "title": self._t = False
        if tag in ("p", "h1"): self._p = False
    def handle_data(self, d):
        if self._t: self.title += d
        elif self._p: self.body.append(d)


class CssJsonExtractor(Extractor):
    name = "css-json"
    def available(self) -> bool: return True
    def extract(self, html: str) -> dict:
        p = _PTextParser()
        try: p.feed(html)
        except Exception: pass
        return {"title": p.title.strip(),
                "body_text": _WS.sub(" ", " ".join(p.body)).strip().lower()}


class TrafilaturaExtractor(Extractor):
    name = "trafilatura"
    def available(self) -> bool:
        try:
            import trafilatura  # noqa: F401
            return True
        except Exception:
            return False
    def extract(self, html: str) -> dict:
        import trafilatura
        txt = trafilatura.extract(html) or ""
        m = _TITLE.search(html)
        title = _WS.sub(" ", m.group(1)).strip() if m else ""
        return {"title": title, "body_text": _WS.sub(" ", txt).strip().lower()}


ALL_EXTRACTORS = [RuleExtractor(), CssJsonExtractor(), TrafilaturaExtractor()]


def available_extractors() -> list[Extractor]:
    return [e for e in ALL_EXTRACTORS if e.available()]
