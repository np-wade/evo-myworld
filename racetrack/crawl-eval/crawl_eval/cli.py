"""crawl-eval (T5) CLI.

  python3 -m crawl_eval list          # candidates + which deps/containers are up
  python3 -m crawl_eval build         # (re)render the authored fixtures
  python3 -m crawl_eval selftest      # offline: oracle math + JS-trap proof
  python3 -m crawl_eval crawl-race    [--runs N] [--json]
  python3 -m crawl_eval extract-race  [--json]
  python3 -m crawl_eval index-race    [--k N] [--json]
  python3 -m crawl_eval pipeline      [--crawler NAME] [--index NAME]
"""
from __future__ import annotations

import argparse
import json
import sys

from .crawl import build_candidates
from .extract import ALL_EXTRACTORS
from .index import ALL_INDEXES
from .oracle import Oracle


def cmd_list(_):
    print("crawl candidates (fetcher kind):")
    for c in build_candidates():
        print(f"  [{'x' if c.available() else ' '}] {c.name:18} kind={c.kind}")
    print("\nextractors:")
    for e in ALL_EXTRACTORS:
        print(f"  [{'x' if e.available() else ' '}] {e.name}")
    print("\nsearch engines:")
    for ix in ALL_INDEXES:
        print(f"  [{'x' if ix.available() else ' '}] {ix.name}")
    print("\n[x]=runnable now  [ ]=skipped (missing dep/container)")


def cmd_build(_):
    from .build_fixtures import build
    print(json.dumps(build(), indent=2))


def cmd_selftest(_):
    o = Oracle()
    assert o.gold_crawl, "empty inventory"
    # crawl scoring: perfect / empty / static-only (misses JS pages)
    perfect = o.score_crawl(o.gold_crawl)
    assert perfect.f1 == 1.0 and perfect.js_recall == 1.0, perfect
    empty = o.score_crawl(set())
    assert empty.f1 == 0.0, empty
    static_only = o.gold_crawl - o.js_only            # what a raw fetcher reaches
    so = o.score_crawl(static_only)
    assert so.js_recall == 0.0 and so.recall < 1.0, so
    # robots gate
    viol = o.score_crawl(o.gold_crawl | {"/private/secret"},
                         forbidden_hits=["/private/secret"])
    assert viol.robots_violations == 1, viol
    # dedup: a non-canonicalized dup URL is an extra
    dup = o.score_crawl(o.gold_crawl | {"/products?ref=home"})
    assert dup.extra == 1, dup
    # search scoring: perfect answers -> recall 1.0
    perfect_ans = {it["q"]: it["answers"] for it in o.queries}
    ss = o.score_search(perfect_ans)
    assert ss.recall == 1.0 and ss.mrr == 1.0, ss

    # JS-trap proof (offline, on the raw fixture HTML — no browser needed)
    from pathlib import Path
    from .crawl import parse_page
    from .build_fixtures import slug
    fix = Path(__file__).parent.parent / "fixtures" / "site1" / "pages"
    cat_html = (fix / f"{slug('/catalog')}.html").read_text()
    _, _, links, _ = parse_page(cat_html, "http://x/catalog")
    item_links = [l for l in links if "/item/" in l]
    assert not item_links, f"JS trap broken: raw catalog exposed {item_links}"

    print("selftest OK — crawl/search scoring verified (perfect/empty/static-"
          f"only/robots/dedup); JS trap holds (raw /catalog exposes 0 of "
          f"{len(o.js_only)} item links). gold={len(o.gold_crawl)} pages, "
          f"{len(o.queries)} queries.")


def cmd_crawl_race(a):
    from .race import crawl_race, format_crawl
    res = crawl_race(runs=a.runs)
    print(json.dumps(res, indent=2) if a.json else format_crawl(res))


def cmd_stealth_race(a):
    from .stealth import format_stealth, stealth_race
    res = stealth_race(runs=a.runs)
    print(json.dumps(res, indent=2) if a.json else format_stealth(res))


def cmd_http2_race(a):
    from .http2fp import format_http2, http2_race
    res = http2_race()
    print(json.dumps(res, indent=2) if a.json else format_http2(res))


def cmd_challenge_race(a):
    from .challenge import challenge_race, format_challenge
    res = challenge_race(runs=a.runs)
    print(json.dumps(res, indent=2) if a.json else format_challenge(res))


def cmd_behavioral_race(a):
    from .behavioral import behavioral_race, format_behavioral
    res = behavioral_race(runs=a.runs)
    print(json.dumps(res, indent=2) if a.json else format_behavioral(res))


def cmd_endurance_race(a):
    from .race import endurance_race, format_endurance
    res = endurance_race(seconds=a.seconds, max_pages=a.max_pages)
    print(json.dumps(res, indent=2) if a.json else format_endurance(res))


def cmd_extract_race(a):
    from .race import extract_race, format_extract
    res = extract_race()
    print(json.dumps(res, indent=2) if a.json else format_extract(res))


def cmd_index_race(a):
    from .race import format_index, index_race
    res = index_race(k=a.k)
    print(json.dumps(res, indent=2) if a.json else format_index(res))


def cmd_pipeline(a):
    from .pipeline import run_pipeline, score_pipeline
    res = run_pipeline(crawler=a.crawler or None, index=a.index or None)
    print(json.dumps(score_pipeline(res), indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="crawl_eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    cr = sub.add_parser("crawl-race")
    cr.add_argument("--runs", type=int, default=1)
    cr.add_argument("--json", action="store_true")
    cr.set_defaults(fn=cmd_crawl_race)
    st = sub.add_parser("stealth-race")
    st.add_argument("--runs", type=int, default=5)
    st.add_argument("--json", action="store_true")
    st.set_defaults(fn=cmd_stealth_race)
    h2 = sub.add_parser("http2-race")
    h2.add_argument("--json", action="store_true")
    h2.set_defaults(fn=cmd_http2_race)
    ch = sub.add_parser("challenge-race")
    ch.add_argument("--runs", type=int, default=3)
    ch.add_argument("--json", action="store_true")
    ch.set_defaults(fn=cmd_challenge_race)
    bh = sub.add_parser("behavioral-race")
    bh.add_argument("--runs", type=int, default=3)
    bh.add_argument("--json", action="store_true")
    bh.set_defaults(fn=cmd_behavioral_race)
    en = sub.add_parser("endurance-race")
    en.add_argument("--seconds", type=float, default=12.0)
    en.add_argument("--max-pages", dest="max_pages", type=int, default=200_000)
    en.add_argument("--json", action="store_true")
    en.set_defaults(fn=cmd_endurance_race)
    er = sub.add_parser("extract-race")
    er.add_argument("--json", action="store_true")
    er.set_defaults(fn=cmd_extract_race)
    ir = sub.add_parser("index-race")
    ir.add_argument("--k", type=int, default=3)
    ir.add_argument("--json", action="store_true")
    ir.set_defaults(fn=cmd_index_race)
    pl = sub.add_parser("pipeline")
    pl.add_argument("--crawler", default="")
    pl.add_argument("--index", default="")
    pl.set_defaults(fn=cmd_pipeline)
    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
