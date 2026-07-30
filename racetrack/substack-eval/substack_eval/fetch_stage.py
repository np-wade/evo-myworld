"""Stage 3 — Fetch: pull the post pages themselves.

Candidates = the fetch backends (urllib / curl_cffi / scrapling) racing on the
same post sample (mix of free + paid across the fixture pubs). Scored on:

  post_ok      -- page fetched and contains the gold title
  fields_ok    -- JSON-LD/meta fields on the fetched page match gold
                  (title + date) — proves we got the real article, not a shell
  paywall_ok   -- detect_paywall(page) agrees with the gold audience flag
  block rate + p50/p95 per page

Politeness: serial fetches with a delay; default samples 2 posts per pub so a
full 3-backend race stays ~18 requests.
"""
from __future__ import annotations

import statistics
import time

from .extract_stage import detect_paywall, extract_fields
from .fetchers import available_backends
from .oracle import DEFAULT_PUBS, Oracle, norm_text


def _sample_posts(pubs: list[str], per_pub: int) -> list[tuple[str, dict]]:
    """Most recent posts per pub, forcing at least one paid post in when the
    pub has any (the paywall-detect signal needs one)."""
    out = []
    for pub in pubs:
        try:
            o = Oracle(pub)
        except FileNotFoundError:
            continue
        recent = o.recent(20)
        pick = recent[:per_pub]
        if not any(p["audience"] == "only_paid" for p in pick):
            paid = next((p for p in recent
                         if p["audience"] == "only_paid"), None)
            if paid:
                pick = pick[:-1] + [paid]
        out.extend((pub, p) for p in pick)
    return out


def fetch_race(pubs: list[str] | None = None, per_pub: int = 2,
               polite_s: float = 1.5, backend: str = "") -> dict:
    pubs = pubs or DEFAULT_PUBS
    posts = _sample_posts(pubs, per_pub)
    backends = available_backends()
    if backend:
        backends = [b for b in backends if b.name == backend]

    rows = []
    for be in backends:
        lat, post_ok, fields_ok, pay_ok, blocks, err = [], 0, 0, 0, 0, ""
        for pub, g in posts:
            try:
                r = be.get(g["url"], timeout=60)
            except Exception as e:   # backend crash must not kill the race
                err = f"{type(e).__name__}: {e}"
                lat.append(0.0)
                time.sleep(polite_s)
                continue
            lat.append(r.latency_ms)
            if r.blocked:
                blocks += 1
            if r.ok and norm_text(g["title"])[:40] in norm_text(r.text):
                post_ok += 1
            elif r.error:
                err = r.error
            f = extract_fields(r.text) if r.text else {}
            if (f and norm_text(f.get("title", "")) == norm_text(g["title"])
                    and f.get("date", "") == g["date"]):
                fields_ok += 1
            if r.text and detect_paywall(r.text) == \
                    (g["audience"] == "only_paid"):
                pay_ok += 1
            time.sleep(polite_s)
        n = len(posts)
        rows.append({
            "backend": be.name, "posts": n,
            "post_ok": round(post_ok / n, 3) if n else 0.0,
            "fields_ok": round(fields_ok / n, 3) if n else 0.0,
            "paywall_ok": round(pay_ok / n, 3) if n else 0.0,
            "block_rate": round(blocks / n, 3) if n else 0.0,
            "p50_ms": round(statistics.median(lat), 1) if lat else 0.0,
            "p95_ms": round(sorted(lat)[max(0, int(len(lat) * .95) - 1)], 1)
                      if lat else 0.0,
            "error": err,
        })
    rows.sort(key=lambda r: (-(r["post_ok"] + r["fields_ok"] +
                               r["paywall_ok"]), r["p50_ms"]))
    return {"pubs": pubs,
            "sample": [f"{p}/{g['slug']}" for p, g in posts],
            "leaderboard": rows}


def format_fetch_leaderboard(res: dict) -> str:
    L = [f"stage-3 fetch race — {len(res['sample'])} posts across "
         f"{', '.join(res['pubs'])} (free+paid mix)", ""]
    hdr = (f"{'backend':12} {'post-ok':>8} {'fields':>7} {'paywall':>8} "
           f"{'block':>6} {'p50ms':>8} {'p95ms':>9}")
    L += [hdr, "-" * len(hdr)]
    for r in res["leaderboard"]:
        L.append(f"{r['backend']:12} {r['post_ok']:8.2f} {r['fields_ok']:7.2f} "
                 f"{r['paywall_ok']:8.2f} {r['block_rate']:6.2f} "
                 f"{r['p50_ms']:8.1f} {r['p95_ms']:9.1f}"
                 + (f"  err: {r['error'][:45]}" if r["error"] else ""))
    return "\n".join(L)
