"""End-to-end pipeline — the seed task, ONE prompt -> report, normal scraping
only, chained from each stage's race winners:

  1 Discover  sitemap (coverage) MERGED with archive-html (true post dates +
              titles for the recent slice) — both cheap static scrapes
  2 Filter    date-window (PINNED 60-day window from the fixture meta)
  3 Table     every in-window post (slug, url, date)
  4 Fetch     the 10 most recent post pages via the chosen backend
  5 Extract   winner extractor -> clean markdown; paywall honesty read from
              the page (detect_paywall) and flagged, never padded
  6 Report    out/<pub>/report.{json,md} + md/ + manifest w/ sha256

Then scores the run against the oracle: post-set F1, field accuracy, content
fidelity (free posts), PAYWALL HONESTY GATE (hard fail), save integrity (hard
track) and pick-3-about-X overlap (advisory track). Substack's API/RSS are
never touched here.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .discover import ArchiveHtmlScrape, SitemapScrape
from .extract_stage import detect_paywall, extract_fields, extractor_by_key
from .fetchers import available_backends
from .filter import FilterCandidate
from .oracle import DEFAULT_PUBS, Oracle, norm_text

OUT = Path(__file__).parent.parent / "out"

# advisory pick-3 rubric: "the 3 best posts about AI" — keyword proxy, never
# part of the hard score
TOPIC_TERMS = ["ai", "llm", "gpt", "model", "openai", "anthropic", "claude",
               "gemini", "agent", "intelligence", "machine learning",
               "deep learning", "chatbot", "transformer"]


def _relevance(text: str) -> int:
    t = f" {norm_text(text)} "
    return sum(1 for k in TOPIC_TERMS if f" {k} " in t)


def run_pipeline(pub: str, backend: str = "curl_cffi",
                 extractor: str = "css-rules", n_save: int = 10,
                 polite_s: float = 1.5, outdir: str = "") -> dict:
    t0 = time.perf_counter()
    o = Oracle(pub)  # config only: base_url + pinned window (no gold reads)
    out = Path(outdir) if outdir else OUT / pub
    (out / "md").mkdir(parents=True, exist_ok=True)
    names = [b.name for b in available_backends()]
    be = next(b for b in available_backends()
              if b.name == (backend if backend in names else names[0]))
    ex = extractor_by_key(extractor)

    # 1 discover: sitemap for coverage + archive page for true dates/titles
    sm = SitemapScrape(be, o.base_url).discover()
    time.sleep(polite_s)
    ar = ArchiveHtmlScrape(be, o.base_url).discover()
    slugs = sm.slugs | ar.slugs
    dates = dict(sm.slug_dates)
    dates.update(ar.slug_dates)          # archive <time> beats lastmod
    titles = {s: m.get("title", "") for s, m in ar.slug_meta.items()}
    requests = sm.requests + ar.requests

    # 2 filter: pinned window
    filt = FilterCandidate("date-window", (o.window_start, o.ref_date))
    from .discover import DiscoverOut
    window = filt.apply(DiscoverOut(True, slugs, slug_dates=dates))

    # 3 table: every in-window post, newest first
    rows = sorted(({"slug": s, "url": f"{o.base_url}/p/{s}",
                    "date": dates.get(s, ""),
                    "title": titles.get(s, "")} for s in window),
                  key=lambda r: r["date"], reverse=True)

    # 4+5 fetch + extract the n most recent; save markdown
    delivered, manifest = [], []
    for r in rows[:n_save]:
        time.sleep(polite_s)
        resp = be.get(r["url"], timeout=60)
        requests += 1
        if not resp.ok or not resp.text:
            delivered.append({**r, "fetched": False, "truncated": False,
                              "content_chars": 0, "error": resp.error})
            continue
        fields = extract_fields(resp.text)
        truncated = detect_paywall(resp.text)
        try:
            got = ex.extract(resp.text)
        except Exception as e:
            got = {"markdown": "", "title": fields.get("title", "")}
            r["extract_error"] = f"{type(e).__name__}: {e}"
        md_body = got["markdown"]
        head = [f"# {fields['title'] or r['title']}", "",
                f"- url: {fields['url'] or r['url']}",
                f"- date: {fields['date'] or r['date']}",
                f"- author: {fields['author']}",
                f"- truncated: {str(truncated).lower()}"
                + (" (paywalled — free preview only, not padded)"
                   if truncated else ""), "", "---", ""]
        md_text = "\n".join(head) + md_body + "\n"
        md_path = out / "md" / f"{r['slug']}.md"
        md_path.write_text(md_text, encoding="utf-8")
        entry = {"slug": r["slug"], "url": fields["url"] or r["url"],
                 "title": fields["title"] or r["title"],
                 "date": fields["date"] or r["date"],
                 "author": fields["author"], "fetched": True,
                 "truncated": truncated,
                 "content_chars": len(norm_text(md_body)),
                 "blocked": resp.blocked}
        delivered.append(entry)
        manifest.append({"file": f"md/{r['slug']}.md",
                         "bytes": md_path.stat().st_size,
                         "sha256": hashlib.sha256(
                             md_text.encode()).hexdigest(),
                         "truncated": truncated})

    # advisory pick-3 about the topic
    pool = [{**r, "title": titles.get(r["slug"], r["title"])} for r in rows]
    picks = sorted(pool, key=lambda r: -_relevance(
        r["title"] or r["slug"].replace("-", " ")))[:3]

    report = {
        "prompt": f"Find every post from {pub} published in the last "
                  f"{o.meta['window_days']} days (window pinned "
                  f"{o.window_start}..{o.ref_date}); save the {n_save} most "
                  f"recent as clean markdown; deliver a table + files.",
        "pub": pub, "base_url": o.base_url, "backend": be.name,
        "extractor": ex.key, "window": [o.window_start, o.ref_date],
        "n_posts": len(rows), "table": rows, "delivered": delivered,
        "picks_about_topic": [{"slug": p["slug"], "title": p["title"]}
                              for p in picks],
        "manifest": manifest, "requests": requests,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2),
                                     encoding="utf-8")
    md = [f"# {pub} — last-{o.meta['window_days']}-days archive crawl", "",
          report["prompt"], "",
          f"{len(rows)} posts in window; {len(manifest)} saved as markdown.",
          "", "| date | title/slug | saved | truncated |", "|---|---|---|---|"]
    saved = {e["slug"]: e for e in delivered}
    for r in rows:
        e = saved.get(r["slug"])
        md.append(f"| {r['date']} | {(r['title'] or r['slug'])[:70]} | "
                  f"{'x' if e and e.get('fetched') else ''} | "
                  f"{'PAYWALL' if e and e.get('truncated') else ''} |")
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return {"report": report, "outdir": str(out)}


def score_pipeline(res: dict) -> dict:
    """Hard-score the machinery vs gold; advisory-score the pick-3."""
    report = res["report"]
    o = Oracle(report["pub"])
    table_slugs = {r["slug"] for r in report["table"]}
    disc = o.score_posts(table_slugs)

    delivered = [e for e in report["delivered"] if e.get("fetched")]
    gold_recent = {p["slug"] for p in o.recent(len(report["delivered"]) or 10)}
    recent_hit = sum(1 for e in report["delivered"]
                     if e["slug"] in gold_recent)

    # field accuracy over delivered posts that exist in gold
    acc = {"title": 0, "date": 0, "author": 0, "url": 0}
    n_gold = 0
    for e in delivered:
        g = o.gold_fields(e["slug"])
        if not g:
            continue
        n_gold += 1
        if norm_text(e.get("title", "")) == norm_text(g["title"]):
            acc["title"] += 1
        if e.get("date", "") == g["date"]:
            acc["date"] += 1
        if norm_text(e.get("author", "")) == norm_text(
                ", ".join(g["authors"])):
            acc["author"] += 1
        if e.get("url", "").rstrip("/") == g["url"].rstrip("/"):
            acc["url"] += 1

    # content fidelity: free posts only, vs RSS gold, from the saved md files
    fids = []
    outdir = Path(res["outdir"])
    for e in delivered:
        md_p = outdir / "md" / f"{e['slug']}.md"
        if not md_p.exists():
            continue
        body = md_p.read_text(encoding="utf-8").split("\n---\n", 1)[-1]
        f = o.content_fidelity(e["slug"], body)
        if f is not None:
            fids.append(f)

    gate = o.paywall_gate(report["delivered"])

    hard = {
        "discovery_f1": disc.f1, "recall": disc.recall,
        "precision": disc.precision, "found": disc.found, "gold": disc.gold,
        "recent10_hit": f"{recent_hit}/{len(report['delivered'])}",
        "saved_ok": f"{len(report['manifest'])}/{len(report['delivered'])}",
        "title_acc": round(acc["title"] / n_gold, 4) if n_gold else 0.0,
        "date_acc": round(acc["date"] / n_gold, 4) if n_gold else 0.0,
        "author_acc": round(acc["author"] / n_gold, 4) if n_gold else 0.0,
        "url_acc": round(acc["url"] / n_gold, 4) if n_gold else 0.0,
        "content_fidelity": round(sum(fids) / len(fids), 4) if fids else None,
        "fidelity_posts": len(fids),
        "paywall_gate": "PASS" if gate["pass"] else "FAIL",
        "paywall_violations": gate["violations"],
        "paid_delivered": gate["paid_delivered"],
        "requests": report["requests"], "wall_s": report["wall_s"],
    }
    # advisory: pick-3 overlap with the grader's own keyword ranking over gold
    gold_ranked = sorted(
        o.window_posts.values(),
        key=lambda p: -_relevance(f"{p['title']} {p['description']}"))
    gold_pool = {p["slug"] for p in gold_ranked[:6]}
    picks = {p["slug"] for p in report["picks_about_topic"]}
    advisory = {"pick3_pool_overlap": f"{len(picks & gold_pool)}/{len(picks)}"}
    return {"pub": report["pub"], "hard": hard, "advisory": advisory}
