#!/usr/bin/env python3
"""Build the frozen Substack fixture set for the archive-crawl benchmark.

Seed task (Nicholas): "Find every post from <newsletter>.substack.com published
in the last 60 days; save the 10 most recent as clean markdown; deliver a
table + files."

GRADER-ONLY. This script uses the privileged channels (JSON archive API + RSS)
that the app path is forbidden to touch. It freezes, per newsletter:

  fixtures/<pub>/meta.json        -- pub, base_url, PINNED ref_date + window
  fixtures/<pub>/gold.json        -- definitive post list (API truth): slug,
                                     title, subtitle, post_date, audience
                                     (everyone|only_paid), authors, url
  fixtures/<pub>/feed.xml         -- raw RSS
  fixtures/<pub>/rss/<slug>.html  -- RSS content:encoded per item (content gold;
                                     full for free posts, preview for paid)
  fixtures/<pub>/html/<slug>.html -- saved post-page HTML (~30 recent posts;
                                     the OFFLINE extract-race corpus)

Pure stdlib. Polite (2s sleeps). Re-runnable: skips files already downloaded.
The 60-day window is pinned to REF_DATE below — never a live "now" — so every
scored run is reproducible.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

# ---- PINNED WINDOW (recorded in meta.json; the scored path never uses "now")
REF_DATE = "2026-07-26"
WINDOW_DAYS = 60
WINDOW_START = (dt.date.fromisoformat(REF_DATE)
                - dt.timedelta(days=WINDOW_DAYS)).isoformat()   # 2026-05-27

# name -> canonical base URL. thezvi is native substack.com; the other two are
# Substack pubs on custom domains (<pub>.substack.com 301s there — verified).
PUBS = {
    "thezvi": "https://thezvi.substack.com",
    "astralcodexten": "https://www.astralcodexten.com",
    "noahpinion": "https://www.noahpinion.blog",
}

N_HTML = 30          # saved post pages per pub (extract-race corpus)
POLITE_S = 2.0
FIX = Path(__file__).parent / "fixtures"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"}


def get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


def slug_of(url: str) -> str:
    m = re.search(r"/p/([^/?#]+)", url)
    return m.group(1) if m else ""


def fetch_archive(base: str) -> list[dict]:
    """Paginate the archive API (newest first) until well past the window."""
    posts, offset = [], 0
    stop = (dt.date.fromisoformat(WINDOW_START)
            - dt.timedelta(days=14)).isoformat()  # margin past the edge
    for _ in range(12):  # hard cap (Substack serves ~25/request max)
        url = f"{base}/api/v1/archive?sort=new&offset={offset}&limit=50"
        batch = json.loads(get(url).decode("utf-8", "replace"))
        if not batch:
            break
        posts.extend(batch)
        oldest = min((p.get("post_date") or "9999")[:10] for p in batch)
        print(f"    archive offset={offset}: +{len(batch)} (oldest {oldest})")
        offset += len(batch)
        time.sleep(POLITE_S)
        if oldest < stop:
            break
    return posts


def gold_row(p: dict) -> dict:
    return {
        "slug": p.get("slug") or slug_of(p.get("canonical_url", "")),
        "title": p.get("title", ""),
        "subtitle": p.get("subtitle", ""),
        "post_date": p.get("post_date", ""),          # ISO w/ time
        "date": (p.get("post_date") or "")[:10],      # ISO day
        "audience": p.get("audience", ""),            # everyone | only_paid
        "authors": [b.get("name", "") for b in p.get("publishedBylines", [])],
        "url": p.get("canonical_url", ""),
        "description": p.get("description", ""),
        "word_count": p.get("wordcount", 0),
        "type": p.get("type", ""),
    }


_ITEM = re.compile(r"<item>(.*?)</item>", re.S)
_LINK = re.compile(r"<link>(.*?)</link>")
_CONTENT = re.compile(
    r"<content:encoded>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</content:encoded>", re.S)


def save_rss(base: str, d: Path) -> int:
    feed_p = d / "feed.xml"
    if not feed_p.exists():
        feed_p.write_bytes(get(f"{base}/feed"))
        time.sleep(POLITE_S)
    xml = feed_p.read_text(encoding="utf-8", errors="replace")
    (d / "rss").mkdir(exist_ok=True)
    n = 0
    for it in _ITEM.finditer(xml):
        link = _LINK.search(it.group(1))
        content = _CONTENT.search(it.group(1))
        slug = slug_of(link.group(1)) if link else ""
        if slug and content:
            (d / "rss" / f"{slug}.html").write_text(
                content.group(1), encoding="utf-8")
            n += 1
    return n


def save_html(rows: list[dict], d: Path) -> None:
    (d / "html").mkdir(exist_ok=True)
    for r in rows[:N_HTML]:
        p = d / "html" / f"{r['slug']}.html"
        if p.exists() or not r["url"]:
            continue
        try:
            p.write_bytes(get(r["url"]))
            print(f"    html {r['slug']} ({p.stat().st_size // 1024} KB)")
        except Exception as ex:
            print(f"    html {r['slug']} FAIL {ex}")
        time.sleep(POLITE_S)


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    for pub, base in PUBS.items():
        if only and pub != only:
            continue
        d = FIX / pub
        d.mkdir(parents=True, exist_ok=True)
        print(f"[{pub}] archive API ...")
        gold_p = d / "gold.json"
        if gold_p.exists():
            rows = json.loads(gold_p.read_text())["posts"]
            print(f"    gold.json exists ({len(rows)} posts) — skip")
        else:
            posts = fetch_archive(base)
            rows = [gold_row(p) for p in posts]
            rows = [r for r in rows if r["slug"] and r["type"] != "thread"]
            gold_p.write_text(json.dumps({
                "pub": pub, "base_url": base, "n_posts": len(rows),
                "posts": rows}, indent=2), encoding="utf-8")
            print(f"    wrote gold.json ({len(rows)} posts)")
        (d / "meta.json").write_text(json.dumps({
            "pub": pub, "base_url": base,
            "ref_date": REF_DATE, "window_days": WINDOW_DAYS,
            "window_start": WINDOW_START,
            "note": "window pinned at fixture-freeze; scored path never uses "
                    "a live now()",
        }, indent=2), encoding="utf-8")
        print(f"[{pub}] RSS ...")
        n = save_rss(base, d)
        print(f"    {n} rss content items")
        print(f"[{pub}] post-page HTML (first {N_HTML}) ...")
        save_html(rows, d)
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
