"""Oracle — the grader's answer key, derived from the authored site (we own it).

The app never calls this. It loads the frozen gold and scores a candidate on
three machinery tracks (all hard, deterministic, offline-rerunnable):

  crawl   — P/R/F1 of the discovered URL set vs the canonical inventory, PLUS
            js_recall (did it reach the JS-nav-only /item pages?) and a robots
            gate (fetching a Disallow:'d path is a hard fail).
  extract — per-page title exact-match + body token-F1 vs the page gold.
  search  — precision@k / recall / MRR of answer-pages vs the query gold.

Judgment (snippet readability, etc.) is advisory-only and never enters these.
Pure stdlib.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

FIX = Path(__file__).parent.parent / "fixtures" / "site1"
_WORD = re.compile(r"[a-z0-9]+")


def norm_path(url: str) -> str:
    """Strip scheme/host, keep path (+query, so a non-deduped ?ref= URL shows as
    a distinct extra). Trailing slash normalized away."""
    sp = urlsplit(url)
    p = sp.path or "/"
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return p + (f"?{sp.query}" if sp.query else "")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _f1(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    tp = len(a & b)
    prec = tp / len(a) if a else 0.0
    rec = tp / len(b) if b else 0.0
    return (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0


@dataclass
class CrawlScore:
    found: int
    gold: int
    true_pos: int
    precision: float
    recall: float
    f1: float
    js_recall: float          # recall over the JS-nav-only pages (the money metric)
    extra: int                # discovered URLs not in gold (dup/query leakage)
    robots_violations: int    # forbidden paths fetched — >0 is a hard fail
    depth_ok: bool            # did it reach the depth-4 deep page?


@dataclass
class ExtractScore:
    pages_scored: int
    title_acc: float
    body_f1: float


@dataclass
class SearchScore:
    queries: int
    recall: float
    precision_at_k: float
    mrr: float
    k: int
    by_tier: dict = field(default_factory=dict)   # tier -> recall@k


class Oracle:
    def __init__(self, site: str = "site1"):
        base = Path(__file__).parent.parent / "fixtures" / site
        self.inv = json.loads((base / "gold" / "inventory.json").read_text())
        self.gold_crawl: set[str] = set(self.inv["crawlable"])
        self.js_only: set[str] = set(self.inv["js_only"])
        self.forbidden_prefixes: list[str] = self.inv["robots_disallow"]
        self.queries = json.loads((base / "gold" / "queries.json").read_text())
        self.page_gold: dict[str, dict] = {}
        for f in (base / "gold" / "pages").glob("*.json"):
            g = json.loads(f.read_text())
            self.page_gold[g["path"]] = g

    # ---- crawl ----
    def score_crawl(self, found_urls, forbidden_hits=None) -> CrawlScore:
        found = {norm_path(u) for u in found_urls}
        tp = len(found & self.gold_crawl)
        prec = tp / len(found) if found else 0.0
        rec = tp / len(self.gold_crawl) if self.gold_crawl else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        js_rec = (len(found & self.js_only) / len(self.js_only)
                  if self.js_only else 1.0)
        viol = forbidden_hits if forbidden_hits is not None else \
            [p for p in found if self._forbidden(p)]
        return CrawlScore(
            found=len(found), gold=len(self.gold_crawl), true_pos=tp,
            precision=round(prec, 4), recall=round(rec, 4), f1=round(f1, 4),
            js_recall=round(js_rec, 4), extra=len(found - self.gold_crawl),
            robots_violations=len(viol),
            depth_ok="/depth/deep" in found,
        )

    def _forbidden(self, path: str) -> bool:
        bare = path.split("?", 1)[0]
        return any(bare.startswith(pre) for pre in self.forbidden_prefixes)

    # ---- extract ----
    def score_extract(self, pages: dict) -> ExtractScore:
        """pages: {path: {"title":..., "body_text":...}} for reached pages."""
        titles, bodies, n = 0.0, 0.0, 0
        for path, got in pages.items():
            g = self.page_gold.get(norm_path(path))
            if not g:
                continue
            n += 1
            if (got.get("title") or "").strip() == g["title"].strip():
                titles += 1
            bodies += _f1(_tokens(got.get("body_text", "")),
                          _tokens(g["body_text"]))
        return ExtractScore(
            pages_scored=n,
            title_acc=round(titles / n, 4) if n else 0.0,
            body_f1=round(bodies / n, 4) if n else 0.0,
        )

    # ---- search ----
    def score_search(self, results: dict, k: int = 3) -> SearchScore:
        """results: {query_string: [ranked answer paths]}"""
        rec_hits, p_at_k, rr, n = 0, 0.0, 0.0, 0
        tier_hit: dict = {}
        tier_tot: dict = {}
        for item in self.queries:
            q, gold = item["q"], {norm_path(a) for a in item["answers"]}
            tier = item.get("tier", "lexical")
            got = [norm_path(u) for u in results.get(q, [])]
            n += 1
            topk = got[:k]
            hit = 1 if (gold & set(topk)) else 0
            rec_hits += hit
            tier_hit[tier] = tier_hit.get(tier, 0) + hit
            tier_tot[tier] = tier_tot.get(tier, 0) + 1
            p_at_k += len(gold & set(topk)) / k
            rank = next((i + 1 for i, u in enumerate(got) if u in gold), 0)
            rr += (1 / rank) if rank else 0.0
        by_tier = {t: round(tier_hit[t] / tier_tot[t], 3) for t in tier_tot}
        return SearchScore(
            queries=n,
            recall=round(rec_hits / n, 4) if n else 0.0,
            precision_at_k=round(p_at_k / n, 4) if n else 0.0,
            mrr=round(rr / n, 4) if n else 0.0, k=k, by_tier=by_tier,
        )
