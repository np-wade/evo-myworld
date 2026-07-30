"""arxiv-eval CLI.

  python3 -m arxiv_eval list       # candidates + which backends are available
  python3 -m arxiv_eval selftest   # offline: oracle loads + scoring math
  python3 -m arxiv_eval race [--runs N] [--json]   # LIVE discovery race
"""
from __future__ import annotations

import argparse
import json
import sys

from .discover import build_candidates
from .fetchers import ALL_BACKENDS, available_backends
from .oracle import Oracle
from .race import format_leaderboard, race


def cmd_list(_):
    avail = {b.name for b in available_backends()}
    print("fetch backends:")
    for b in ALL_BACKENDS:
        print(f"  [{'x' if b.name in avail else ' '}] {b.name}")
    print("\ndiscovery candidates (strategy/backend):")
    for c in build_candidates(ALL_BACKENDS):
        print(f"  [{'x' if c.available() else ' '}] {c.name:28} bracket={c.bracket}")
    print("\n[x]=runnable now  [ ]=skipped (missing dep/infra/risky-flag)")


def cmd_selftest(_):
    o = Oracle()
    assert o.gold_ids, "gold listing empty"
    # perfect, empty, and noisy inputs
    full = o.score_discovery(set(o.gold_ids))
    assert full.recall == 1.0 and full.precision == 1.0, full
    empty = o.score_discovery(set())
    assert empty.recall == 0.0 and empty.f1 == 0.0, empty
    half = set(list(o.gold_ids)[: len(o.gold_ids) // 2]) | {"9999.99999"}
    hs = o.score_discovery(half)
    assert 0 < hs.recall < 1 and hs.extra == 1, hs
    print(f"selftest OK — gold={len(o.gold_ids)} papers; "
          f"scoring verified (perfect/empty/noisy).")


def cmd_race(a):
    res = race(runs=a.runs)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(format_leaderboard(res))


def cmd_filter_race(a):
    from .filter import filter_race, format_filter_leaderboard
    res = filter_race(runs=a.runs, backend=a.backend)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(format_filter_leaderboard(res))


def cmd_pipeline(a):
    from .pipeline import run_pipeline, score_pipeline
    res = run_pipeline(backend=a.backend)
    score = score_pipeline(res)
    print(json.dumps({"outdir": res["outdir"], **score}, indent=2))


def cmd_parse_race(a):
    from .parse_stage import format_parse_leaderboard, parse_race
    res = parse_race(sample=a.sample)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(format_parse_leaderboard(res))


def cmd_fetch_race(a):
    from .fetch_stage import fetch_race, format_fetch_leaderboard
    res = fetch_race(sample=a.sample, backend=a.backend)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(format_fetch_leaderboard(res))


def main(argv=None):
    p = argparse.ArgumentParser(prog="arxiv_eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    r = sub.add_parser("race"); r.add_argument("--runs", type=int, default=5)
    r.add_argument("--json", action="store_true"); r.set_defaults(fn=cmd_race)
    fr = sub.add_parser("filter-race")
    fr.add_argument("--runs", type=int, default=3)
    fr.add_argument("--backend", default="")
    fr.add_argument("--json", action="store_true")
    fr.set_defaults(fn=cmd_filter_race)
    fe = sub.add_parser("fetch-race")
    fe.add_argument("--sample", type=int, default=5)
    fe.add_argument("--backend", default="")
    fe.add_argument("--json", action="store_true")
    fe.set_defaults(fn=cmd_fetch_race)
    pa = sub.add_parser("parse-race")
    pa.add_argument("--sample", type=int, default=0)
    pa.add_argument("--json", action="store_true")
    pa.set_defaults(fn=cmd_parse_race)
    pl = sub.add_parser("pipeline")
    pl.add_argument("--backend", default="curl_cffi")
    pl.set_defaults(fn=cmd_pipeline)
    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
