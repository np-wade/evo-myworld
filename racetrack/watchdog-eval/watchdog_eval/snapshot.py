"""Snapshot/normalize stage — what gets stored as the baseline and what the
differs compare. Raced dimension: raw bytes vs volatile-stripping.

  raw            -- identity; the differ sees the page exactly as served.
  strip-volatile -- generic (NOT fixture-tuned) noise removal: comments,
                    script/style blocks, meta tags, hidden inputs, and
                    cache-buster query strings on asset URLs.

Also home of the shared visible-text extraction the text differs use.
Pure stdlib.
"""
from __future__ import annotations

import re
from html import unescape

_WS = re.compile(r"\s+")


def norm_ws(s: str) -> str:
    return _WS.sub(" ", s or "").strip()


_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_META = re.compile(r"<meta\b[^>]*>", re.I)
_HIDDEN = re.compile(r"<input\b[^>]*type\s*=\s*[\"']?hidden[\"']?[^>]*>", re.I)
_CACHEBUST = re.compile(r"(\b(?:href|src)\s*=\s*[\"'][^\"'?]+)\?v=[\w.-]+",
                        re.I)


class Normalizer:
    key = "?"
    def available(self) -> bool: return True
    def normalize(self, html: str) -> str: ...


class RawNorm(Normalizer):
    key = "raw"
    def normalize(self, html: str) -> str:
        """identity — compare the page exactly as served"""
        return html


class StripVolatile(Normalizer):
    key = "strip"
    def normalize(self, html: str) -> str:
        """strip comments/script/style/meta/hidden-inputs/cache-busters"""
        h = _COMMENT.sub(" ", html)
        h = _SCRIPT.sub(" ", h)
        h = _META.sub(" ", h)
        h = _HIDDEN.sub(" ", h)
        h = _CACHEBUST.sub(r"\1", h)
        return h


ALL_NORMALIZERS = [RawNorm(), StripVolatile()]


_BLOCK_END = re.compile(
    r"</(?:p|li|h[1-6]|div|tr|td|th|section|article|header|footer|ul|ol|nav|"
    r"main|title|blockquote|pre|form|table)>", re.I)
_BR = re.compile(r"<br\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")


def visible_lines(html: str) -> list[str]:
    """Visible text as a list of block-level lines (whitespace-normalized)."""
    h = _COMMENT.sub(" ", html)
    h = _SCRIPT.sub(" ", h)
    h = _BLOCK_END.sub("\n", h)
    h = _BR.sub("\n", h)
    h = _TAG.sub(" ", h)
    h = unescape(h)
    return [ln for ln in (norm_ws(x) for x in h.split("\n")) if ln]
