"""Diff-stage candidates — given (baseline_html, current_html) for one watched
page, emit Detections: what's new, what's gone, what moved, what changed.
available()-gated; a differ with a missing dep SKIPS the race, never crashes.

  content-hash -- sha256 of the (normalized) document. Page-level "something
                  changed" only; the toy baseline every watcher must beat.
  line-diff    -- difflib over visible text lines; emits changed line pairs.
                  Detects moved-but-identical lines.
  dom-diff     -- stdlib html.parser tree; compares elements keyed by id attr
                  (nested-id content excluded), detects added/removed/modified/
                  reordered elements. The element-localized contender.
  css-scope    -- changedetection.io approach: watch only the main content
                  regions (main/article/#content/.content), line-diff inside.
  soup-diff    -- BeautifulSoup id-keyed element diff (gated on bs4 install).

All pure stdlib except soup-diff.
"""
from __future__ import annotations

import difflib
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .snapshot import norm_ws, visible_lines


@dataclass
class Detection:
    page: str
    change_type: str          # added | removed | modified | moved | page-changed
    element_id: str = ""      # id attr of the changed element, when known
    before: str = ""
    after: str = ""
    context: str = ""         # class attr / region hint for the classifier
    label: str = "real"       # set by the classify stage: real | churn


# ---------------------------------------------------------------- tree parser

_VOID = {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "area",
         "base", "col", "embed", "track"}


class _Node:
    __slots__ = ("tag", "attrs", "children")
    def __init__(self, tag: str, attrs: dict):
        self.tag = tag
        self.attrs = attrs
        self.children: list = []  # _Node | str


class _TreeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if data:
            self.stack[-1].children.append(data)


def parse_tree(html: str) -> _Node:
    p = _TreeParser()
    p.feed(html)
    return p.root


def _own_text(node: _Node) -> str:
    """Text of node + descendants, EXCLUDING any descendant that has its own
    id (those are separate blocks)."""
    parts: list[str] = []
    def walk(n: _Node):
        for c in n.children:
            if isinstance(c, str):
                parts.append(c)
            elif not c.attrs.get("id"):
                walk(c)
    walk(node)
    return norm_ws(" ".join(parts))


def id_blocks(root: _Node) -> tuple[dict, dict, str]:
    """(blocks, child_seqs, rest_text): blocks = id -> {tag, class, text};
    child_seqs = id -> tuple of id'd-child ids in order; rest_text = all text
    living under no id'd element."""
    blocks: dict[str, dict] = {}
    seqs: dict[str, tuple] = {}
    rest: list[str] = []

    def walk(n: _Node, under_id: bool):
        for c in n.children:
            if isinstance(c, str):
                if not under_id:
                    rest.append(c)
                continue
            cid = c.attrs.get("id")
            if cid:
                blocks[cid] = {"tag": c.tag, "class": c.attrs.get("class", ""),
                               "text": _own_text(c)}
                seqs[cid] = tuple(g.attrs.get("id") for g in c.children
                                  if isinstance(g, _Node) and g.attrs.get("id"))
                walk(c, True)
            else:
                walk(c, under_id)
    walk(root, False)
    return blocks, seqs, norm_ws(" ".join(rest))


# -------------------------------------------------------------------- differs

class Differ:
    key = "?"
    def available(self) -> bool: return True
    def diff(self, page: str, v1: str, v2: str) -> list[Detection]: ...


class HashDiff(Differ):
    key = "content-hash"
    def diff(self, page, v1, v2):
        """sha256 of the doc — page-level changed/unchanged only"""
        h1 = hashlib.sha256(v1.encode()).hexdigest()
        h2 = hashlib.sha256(v2.encode()).hexdigest()
        if h1 == h2:
            return []
        return [Detection(page, "page-changed",
                          before=h1[:12], after=h2[:12])]


def _pair_lines(old: list[str], new: list[str]
                ) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """Pair each removed line with its most-similar added line (ratio >= .5),
    greedily best-first — a positional zip mispairs when lines shift."""
    scored = sorted(
        ((difflib.SequenceMatcher(None, o, n, autojunk=False).ratio(), i, j)
         for i, o in enumerate(old) for j, n in enumerate(new)),
        reverse=True)
    used_o: set[int] = set()
    used_n: set[int] = set()
    pairs: list[tuple[str, str]] = []
    for r, i, j in scored:
        if r < 0.5:
            break
        if i in used_o or j in used_n:
            continue
        used_o.add(i); used_n.add(j)
        pairs.append((old[i], new[j]))
    rest_o = [o for i, o in enumerate(old) if i not in used_o]
    rest_n = [n for j, n in enumerate(new) if j not in used_n]
    return pairs, rest_o, rest_n


def _line_detections(page: str, l1: list[str], l2: list[str],
                     context: str = "") -> list[Detection]:
    """Shared difflib-over-lines core (line-diff and css-scope)."""
    dets: list[Detection] = []
    removed: list[str] = []
    added: list[str] = []
    sm = difflib.SequenceMatcher(None, l1, l2, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        pairs, rest_o, rest_n = _pair_lines(l1[i1:i2], l2[j1:j2])
        for old_ln, new_ln in pairs:
            dets.append(Detection(page, "modified", before=old_ln,
                                  after=new_ln, context=context))
        removed += rest_o
        added += rest_n
    # moved: a removed line that reappears verbatim among the added lines
    add_pool = Counter(added)
    for ln in removed:
        if add_pool[ln] > 0:
            add_pool[ln] -= 1
            dets.append(Detection(page, "moved", before=ln, after=ln,
                                  context=context))
        else:
            dets.append(Detection(page, "removed", before=ln, context=context))
    for ln, k in add_pool.items():
        for _ in range(k):
            dets.append(Detection(page, "added", after=ln, context=context))
    return dets


class LineDiff(Differ):
    key = "line-diff"
    def diff(self, page, v1, v2):
        """difflib over visible text lines of the whole document"""
        return _line_detections(page, visible_lines(v1), visible_lines(v2))


class DomDiff(Differ):
    key = "dom-diff"
    def diff(self, page, v1, v2):
        """id-keyed element tree diff (stdlib html.parser)"""
        b1, s1, r1 = id_blocks(parse_tree(v1))
        b2, s2, r2 = id_blocks(parse_tree(v2))
        dets: list[Detection] = []
        for i in b2.keys() - b1.keys():
            dets.append(Detection(page, "added", element_id=i,
                                  after=b2[i]["text"],
                                  context=b2[i]["class"]))
        for i in b1.keys() - b2.keys():
            dets.append(Detection(page, "removed", element_id=i,
                                  before=b1[i]["text"],
                                  context=b1[i]["class"]))
        for i in b1.keys() & b2.keys():
            t1, t2 = b1[i]["text"], b2[i]["text"]
            if t1 != t2:
                kind = ("moved" if Counter(t1.split()) == Counter(t2.split())
                        else "modified")
                dets.append(Detection(page, kind, element_id=i, before=t1,
                                      after=t2, context=b1[i]["class"]))
            elif s1.get(i) != s2.get(i) and \
                    set(s1.get(i, ())) == set(s2.get(i, ())):
                dets.append(Detection(page, "moved", element_id=i,
                                      before=" ".join(s1[i]),
                                      after=" ".join(s2[i]),
                                      context=b1[i]["class"]))
        if r1 != r2:
            dets.append(Detection(page, "modified", before=r1, after=r2,
                                  context="#unkeyed"))
        return dets


_MAIN_RE = re.compile(r"<main\b.*?</main\s*>", re.S | re.I)
_ARTICLE_RE = re.compile(r"<article\b.*?</article\s*>", re.S | re.I)
_CONTENT_RE = re.compile(
    r"<(?:div|section)\b[^>]*(?:id|class)\s*=\s*[\"'][^\"']*content[^\"']*"
    r"[\"'].*?</(?:div|section)\s*>", re.S | re.I)


class CssScope(Differ):
    key = "css-scope"
    def diff(self, page, v1, v2):
        """watch only main-content regions (main/article/*content*)"""
        def regions(html: str) -> str:
            for rx in (_MAIN_RE, _ARTICLE_RE, _CONTENT_RE):
                m = rx.findall(html)
                if m:
                    return "\n".join(m)
            return html  # no recognizable region -> watch everything
        return _line_detections(page, visible_lines(regions(v1)),
                                visible_lines(regions(v2)),
                                context="css-scope")


class SoupDiff(Differ):
    key = "soup-diff"
    def available(self) -> bool:
        try:
            import bs4  # noqa: F401
            return True
        except Exception:
            return False
    def diff(self, page, v1, v2):
        """BeautifulSoup id-keyed element text diff (full subtree text)"""
        from bs4 import BeautifulSoup
        def blocks(html: str) -> dict:
            soup = BeautifulSoup(html, "html.parser")
            return {el.get("id"): {"text": norm_ws(el.get_text(" ")),
                                   "class": " ".join(el.get("class", []))}
                    for el in soup.find_all(attrs={"id": True})}
        b1, b2 = blocks(v1), blocks(v2)
        dets: list[Detection] = []
        for i in b2.keys() - b1.keys():
            dets.append(Detection(page, "added", element_id=i,
                                  after=b2[i]["text"], context=b2[i]["class"]))
        for i in b1.keys() - b2.keys():
            dets.append(Detection(page, "removed", element_id=i,
                                  before=b1[i]["text"], context=b1[i]["class"]))
        for i in b1.keys() & b2.keys():
            t1, t2 = b1[i]["text"], b2[i]["text"]
            if t1 != t2:
                kind = ("moved" if Counter(t1.split()) == Counter(t2.split())
                        else "modified")
                dets.append(Detection(page, kind, element_id=i, before=t1,
                                      after=t2, context=b1[i]["class"]))
        return dets


ALL_DIFFERS = [HashDiff(), LineDiff(), DomDiff(), CssScope(), SoupDiff()]
