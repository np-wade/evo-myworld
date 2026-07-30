"""substack-eval CLI.

  python3 -m substack_eval list           # candidates + available backends
  python3 -m substack_eval selftest       # OFFLINE: oracle, scoring, gate
  python3 -m substack_eval discover-race [--runs N] [--json]   # LIVE
  python3 -m substack_eval fetch-race [--per-pub N] [--json]   # LIVE
  python3 -m substack_eval extract-race [--sample N] [--json]  # OFFLINE
  python3 -m substack_eval pipeline [--pub P|all] [--backend B]
                                    [--extractor E]            # LIVE seed task
"""
from __future__ import annotations

import argparse
import json
import sys

from .discover import build_candidates
from .fetchers import ALL_BACKENDS, available_backends
from .oracle import DEFAULT_PUBS, Oracle


def cmd_list(_):
    avail = {b.name for b in available_backends()}
    print("fetch backends:")
    for b in ALL_BACKENDS:
        print(f"  [{'x' if b.name in avail else ' '}] {b.name}")
    print("\ndiscovery candidates (strategy/backend):")
    for c in build_candidates(ALL_BACKENDS, "https://example.substack.com"):
        print(f"  [{'x' if c.available() else ' '}] {c.name:24} "
              f"bracket={c.bracket}")
    from .extract_stage import ALL_EXTRACTORS
    print("\nextractors:")
    for e in ALL_EXTRACTORS:
        print(f"  [{'x' if e.available() else ' '}] {e.key}")
    print("\nfixture pubs:")
    for p in DEFAULT_PUBS:
        try:
            o = Oracle(p)
            paid = sum(1 for x in o.window_posts.values()
                       if x["audience"] == "only_paid")
            print(f"  [x] {p:16} window={o.window_start}..{o.ref_date} "
                  f"gold={len(o.gold_slugs)} posts ({paid} paid)")
        except FileNotFoundError:
            print(f"  [ ] {p:16} (fixtures missing — run fetch_fixtures.py)")
    print("\n[x]=runnable now  [ ]=skipped (missing dep/infra/risky-flag)")


def cmd_selftest(_):
    from .discover import DiscoverOut
    from .extract_stage import CssRules, html_to_md
    from .filter import FilterCandidate
    from .oracle import similarity

    checks = 0
    for pub in DEFAULT_PUBS:
        o = Oracle(pub)
        assert o.gold_slugs, f"{pub}: empty window gold"
        assert len(o.recent(10)) == 10, f"{pub}: <10 recent posts"
        full = o.score_posts(set(o.gold_slugs))
        assert full.recall == 1.0 and full.precision == 1.0, full
        empty = o.score_posts(set())
        assert empty.recall == 0.0 and empty.f1 == 0.0, empty
        half = set(list(o.gold_slugs)[: len(o.gold_slugs) // 2]) | {"no-such"}
        hs = o.score_posts(half)
        assert 0 < hs.recall < 1 and hs.extra == 1, hs
        checks += 1

    # similarity math
    assert similarity("alpha beta gamma", "alpha beta gamma") == 1.0
    assert similarity("alpha beta", "delta epsilon") == 0.0
    assert 0.4 < similarity("a b c d", "a b x y") < 0.6

    # date-window filter drops undated + out-of-window slugs
    o = Oracle("noahpinion")
    f = FilterCandidate("date-window", (o.window_start, o.ref_date))
    dout = DiscoverOut(True, {"in", "old", "nodate"},
                       slug_dates={"in": o.ref_date, "old": "2020-01-01"})
    assert f.apply(dout) == {"in"}, f.apply(dout)

    # PAYWALL HONESTY GATE on a paid pub: fabricated full content must FAIL,
    # honest truncation must PASS
    paid = [s for s, p in o.window_posts.items()
            if p["audience"] == "only_paid"]
    assert paid, "noahpinion fixture lost its paid posts?"
    fabricated = [{"slug": paid[0], "truncated": False,
                   "content_chars": 99_999}]
    g1 = o.paywall_gate(fabricated)
    assert not g1["pass"] and g1["violations"], g1
    padded = [{"slug": paid[0], "truncated": True, "content_chars": 99_999}]
    g2 = o.paywall_gate(padded)
    assert not g2["pass"], f"padded paid body must fail the gate: {g2}"
    honest = [{"slug": paid[0], "truncated": True, "content_chars": 500}]
    g3 = o.paywall_gate(honest)
    assert g3["pass"], g3
    free_slug = next(s for s, p in o.window_posts.items()
                     if p["audience"] == "everyone")
    g4 = o.paywall_gate([{"slug": free_slug, "truncated": False,
                          "content_chars": 50_000}])
    assert g4["pass"], f"free posts can never violate the gate: {g4}"

    # html->md walker basics
    md = html_to_md("<h2>Head</h2><p>Some <strong>bold</strong> and "
                    "<a href='http://x'>link</a>.</p><ul><li>one</li></ul>")
    assert "## Head" in md and "**bold**" in md and "- one" in md, md

    # css-rules extractor on a real frozen page (offline), scored vs RSS gold
    got_one = False
    for slug, p in o.posts.items():
        if p["audience"] != "everyone":
            continue
        html, gold = o.fixture_html(slug), o.rss_html(slug)
        if html and gold:
            out = CssRules().extract(html)
            sim = similarity(gold, out["markdown"])
            assert len(out["markdown"]) > 500, slug
            assert sim > 0.5, f"{slug}: css-rules fidelity {sim}"
            got_one = True
            break
    assert got_one, "no offline extract case found"

    print(f"selftest OK — {checks} pubs loaded "
          f"(gold windows: "
          + ", ".join(f"{p}={len(Oracle(p).gold_slugs)}" for p in DEFAULT_PUBS)
          + "); scoring verified (perfect/empty/noisy); paywall honesty gate "
            "fires on fabricated + padded, passes honest; extractor smoke ok.")


def cmd_discover_race(a):
    from .race import format_leaderboard, race
    res = race(runs=a.runs)
    print(json.dumps(res, indent=2) if a.json else format_leaderboard(res))


def cmd_fetch_race(a):
    from .fetch_stage import fetch_race, format_fetch_leaderboard
    res = fetch_race(per_pub=a.per_pub, backend=a.backend)
    print(json.dumps(res, indent=2) if a.json
          else format_fetch_leaderboard(res))


def cmd_extract_race(a):
    from .extract_stage import extract_race, format_extract_leaderboard
    res = extract_race(sample=a.sample)
    print(json.dumps(res, indent=2) if a.json
          else format_extract_leaderboard(res))


def cmd_pipeline(a):
    from .pipeline import run_pipeline, score_pipeline
    pubs = DEFAULT_PUBS if a.pub == "all" else [a.pub]
    cards = []
    for pub in pubs:
        res = run_pipeline(pub, backend=a.backend, extractor=a.extractor)
        card = score_pipeline(res)
        cards.append({"outdir": res["outdir"], **card})
    out = cards[0] if len(cards) == 1 else {
        "pubs": [c["pub"] for c in cards],
        "gate_all": "PASS" if all(c["hard"]["paywall_gate"] == "PASS"
                                  for c in cards) else "FAIL",
        "runs": cards}
    print(json.dumps(out, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="substack_eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    r = sub.add_parser("discover-race")
    r.add_argument("--runs", type=int, default=2)
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=cmd_discover_race)
    fe = sub.add_parser("fetch-race")
    fe.add_argument("--per-pub", type=int, default=2)
    fe.add_argument("--backend", default="")
    fe.add_argument("--json", action="store_true")
    fe.set_defaults(fn=cmd_fetch_race)
    ex = sub.add_parser("extract-race")
    ex.add_argument("--sample", type=int, default=0)
    ex.add_argument("--json", action="store_true")
    ex.set_defaults(fn=cmd_extract_race)
    pl = sub.add_parser("pipeline")
    pl.add_argument("--pub", default="all")
    pl.add_argument("--backend", default="curl_cffi")
    pl.add_argument("--extractor", default="css-rules")
    pl.set_defaults(fn=cmd_pipeline)
    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
