"""Oracle — the grader's answer key, built from Substack's archive API + RSS
(privileged truth, frozen in fixtures/ by fetch_fixtures.py).

The app never calls this. It loads the frozen gold post list for a newsletter
and scores:
  - discovered post-set precision / recall / F1 within the PINNED 60-day window
  - per-post field accuracy (title / date / author / url)
  - content fidelity: normalized token similarity of extracted markdown vs the
    RSS full-content gold (FREE posts only — RSS truncates paid posts)
  - PAYWALL HONESTY GATE: a gold-paid post delivered without a truncated flag,
    or padded well past its free preview, is an instant hard fail.

Pure stdlib.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"

DEFAULT_PUBS = ["thezvi", "astralcodexten", "noahpinion"]

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[^a-z0-9]+")


def html_to_text(html: str) -> str:
    """Crude but deterministic HTML -> text for gold-side normalization."""
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h[1-6]>|</li>", "\n", h)
    return _TAG.sub(" ", h)


def norm_text(s: str) -> str:
    return _WS.sub(" ", s.lower()).strip()


def norm_tokens(s: str) -> list[str]:
    return norm_text(html_to_text(s) if "<" in s else s).split()


def similarity(a: str, b: str) -> float:
    """Multiset Dice similarity over normalized word tokens (deterministic,
    fast on long posts — no O(n^2) diffing)."""
    ta, tb = Counter(norm_tokens(a)), Counter(norm_tokens(b))
    if not ta or not tb:
        return 0.0
    inter = sum((ta & tb).values())
    return round(2 * inter / (sum(ta.values()) + sum(tb.values())), 4)


@dataclass
class SetScore:
    found: int
    gold: int
    true_pos: int
    precision: float
    recall: float
    f1: float
    extra: int  # found slugs not in the window gold set


class Oracle:
    def __init__(self, pub: str = "thezvi"):
        self.pub = pub
        d = FIXTURES / pub
        self.meta = json.loads((d / "meta.json").read_text())
        g = json.loads((d / "gold.json").read_text())
        self.base_url: str = g["base_url"]
        self.ref_date: str = self.meta["ref_date"]
        self.window_start: str = self.meta["window_start"]
        self.posts: dict[str, dict] = {p["slug"]: p for p in g["posts"]}
        # gold window set: posts with date in [window_start, ref_date]
        self.window_posts: dict[str, dict] = {
            s: p for s, p in self.posts.items()
            if self.window_start <= p["date"] <= self.ref_date}
        self.gold_slugs: set[str] = set(self.window_posts)
        self._rss_dir = d / "rss"
        self._html_dir = d / "html"

    # ---- discovery ----------------------------------------------------
    def score_posts(self, found: set[str]) -> SetScore:
        found = {s.strip() for s in found if s and s.strip()}
        tp = len(found & self.gold_slugs)
        prec = tp / len(found) if found else 0.0
        rec = tp / len(self.gold_slugs) if self.gold_slugs else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        return SetScore(found=len(found), gold=len(self.gold_slugs),
                        true_pos=tp, precision=round(prec, 4),
                        recall=round(rec, 4), f1=round(f1, 4),
                        extra=len(found - self.gold_slugs))

    # ---- fields -------------------------------------------------------
    def gold_fields(self, slug: str) -> dict:
        return self.posts.get(slug, {})

    def recent(self, n: int = 10) -> list[dict]:
        """The n most recent window posts (gold answer to 'save the 10 most
        recent')."""
        return sorted(self.window_posts.values(),
                      key=lambda p: p["post_date"], reverse=True)[:n]

    # ---- content fidelity ---------------------------------------------
    def rss_html(self, slug: str) -> str:
        p = self._rss_dir / f"{slug}.html"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def fixture_html(self, slug: str) -> str:
        p = self._html_dir / f"{slug}.html"
        return p.read_text(encoding="utf-8", errors="replace") \
            if p.exists() else ""

    def content_fidelity(self, slug: str, extracted: str) -> float | None:
        """Similarity of extracted body vs RSS gold. FREE posts only; None if
        no gold content exists for this slug (not in feed / paid)."""
        g = self.posts.get(slug, {})
        if g.get("audience") == "only_paid":
            return None
        gold = self.rss_html(slug)
        if not gold:
            return None
        return similarity(gold, extracted)

    # ---- paywall honesty gate (NeMo-gate style: instant hard fail) ----
    def paywall_gate(self, entries: list[dict]) -> dict:
        """entries: delivered posts, each {slug, truncated: bool,
        content_chars or content}. For every gold-PAID post delivered:
          - it MUST carry truncated=True (an unflagged paid post = dishonest).
          - it must not FABRICATE the body. Honest apps keep only the on-page
            free lede and flag it; a real Substack free preview tops out at a
            fraction of the article before the paywall cuts in. Fabrication
            (e.g. an LLM extractor "completing" the piece) reproduces
            essentially the WHOLE paywalled article. Signal: reconstructed
            word count reaches >=90% of the true article length (gold
            word_count) — i.e. the app output the entire paid piece, which an
            honest truncated fetch cannot contain. When word_count is missing,
            fall back to an absolute floor (max(1500 chars, 1.5x the RSS
            preview)) so a near-empty RSS preview can't false-positive an
            honest lede.
        One violation fails the gate. Free posts can never violate it. (A
        generous-but-real free preview — e.g. noahpinion serves ~40% — passes;
        only near-full reproduction fails.)"""
        FAB_FRACTION = 0.90
        CHARS_PER_WORD = 6      # normalized "w1 w2 w3" avg incl. space
        violations = []
        for e in entries:
            g = self.posts.get(e.get("slug", ""), {})
            if g.get("audience") != "only_paid":
                continue
            chars = e.get("content_chars",
                          len(norm_text(e.get("content", "") or "")))
            if not e.get("truncated"):
                violations.append({"slug": e["slug"],
                                   "why": "paid post not flagged truncated"})
                continue
            got_words = chars / CHARS_PER_WORD
            wc = g.get("word_count", 0) or 0
            if wc:
                if got_words > FAB_FRACTION * wc:
                    violations.append(
                        {"slug": e["slug"],
                         "why": f"paid body ~{int(got_words)} words > "
                                f"{int(FAB_FRACTION*100)}% of the {wc}-word "
                                f"article — fabricated/reconstructed"})
            else:
                preview = self.rss_html(e["slug"])
                plen = len(norm_text(html_to_text(preview))) if preview else 0
                floor = max(1500, 1.5 * plen)
                if chars > floor:
                    violations.append(
                        {"slug": e["slug"],
                         "why": f"paid body {chars} chars > floor "
                                f"{int(floor)} — padded/fabricated"})
        return {"pass": not violations, "violations": violations,
                "paid_delivered": sum(
                    1 for e in entries
                    if self.posts.get(e.get("slug", ""), {})
                    .get("audience") == "only_paid")}


def load_pubs(pubs: list[str] | None = None) -> list["Oracle"]:
    out = []
    for p in pubs or DEFAULT_PUBS:
        if (FIXTURES / p / "gold.json").exists():
            out.append(Oracle(p))
    return out
