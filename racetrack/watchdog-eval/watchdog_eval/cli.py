"""watchdog-eval CLI.

  python3 -m watchdog_eval list          # candidate matrix + availability
  python3 -m watchdog_eval selftest      # OFFLINE green gate: oracle + scoring
                                         # math + one differ recovers the truth
  python3 -m watchdog_eval gen-fixtures [--force]   # (grader) author set1
  python3 -m watchdog_eval diff-race [--runs N] [--json]
  python3 -m watchdog_eval pipeline [--differ K] [--norm K]
"""
from __future__ import annotations

import argparse
import json
import sys

from .differs import ALL_DIFFERS
from .snapshot import ALL_NORMALIZERS


def cmd_list(_):
    print("normalizers (snapshot stage):")
    for n in ALL_NORMALIZERS:
        doc = (n.normalize.__doc__ or "").strip()
        print(f"  [{'x' if n.available() else ' '}] {n.key:14} {doc}")
    print("\ndiffers (raced stage):")
    for d in ALL_DIFFERS:
        doc = (d.diff.__doc__ or "").strip()
        print(f"  [{'x' if d.available() else ' '}] {d.key:14} {doc}")
    combos = [f"{d.key}/{n.key}" for n in ALL_NORMALIZERS for d in ALL_DIFFERS
              if d.available() and n.available()]
    print(f"\nrace grid: {len(combos)} combos — {', '.join(combos)}")
    print("[x]=runnable now  [ ]=skipped (missing dep)")


def cmd_selftest(_):
    from .differs import DomDiff
    from .fixtures_gen import generate
    from .oracle import FIXTURES, Oracle
    from .race import run_combo
    from .snapshot import StripVolatile
    from dataclasses import asdict

    generate()  # deterministic authorship; no-op if fixtures already exist

    # 1) fixtures + oracle load
    o = Oracle("set1")
    assert len(o.pages) >= 10, f"only {len(o.pages)} pages"
    assert len(o.real) >= 8 and len(o.churn) >= 15, \
        f"real={len(o.real)} churn={len(o.churn)}"
    root = FIXTURES / "set1"
    for p in o.pages:
        v1 = (root / "v1" / p["file"]).read_text()
        v2 = (root / "v2" / p["file"]).read_text()
        assert v1 and v2 and v1 != v2, f"{p['page']}: v1/v2 missing or equal"
    pages = {p["page"] for p in o.pages}
    assert all(c["page"] in pages for c in o.changes), "change on unknown page"

    # 2) scoring math on perfect / empty / noisy detection sets
    def det(ch, label="real"):
        return {"page": ch["page"], "change_type": "modified",
                "element_id": ch["element_id"], "before": ch["v1_text"],
                "after": ch["v2_text"], "label": label}
    perfect = o.score_detections([det(c) for c in o.real])
    assert perfect.recall == 1.0 and perfect.precision == 1.0 \
        and perfect.f1 == 1.0 and perfect.false_alarm_rate == 0.0 \
        and perfect.localization == 1.0, perfect
    empty = o.score_detections([])
    assert empty.recall == 0.0 and empty.f1 == 0.0 \
        and empty.false_alarm_rate == 0.0, empty
    noisy = o.score_detections(
        [det(c) for c in o.real[: len(o.real) // 2]]
        + [det(c) for c in o.churn])  # flags every trap as a real change
    assert 0 < noisy.recall < 1 and noisy.precision < 1 \
        and noisy.false_alarm_rate == 1.0, noisy

    # 3) at least one differ perfectly recovers the injected-change set
    dets, lat, errs = run_combo(DomDiff(), StripVolatile(), "set1")
    assert not errs, errs
    live = o.score_detections([asdict(d) for d in dets])
    assert live.recall == 1.0 and live.precision == 1.0 \
        and live.false_alarm_rate == 0.0 and live.localization == 1.0, live

    print(f"selftest OK — {len(o.pages)} page pairs; {len(o.real)} real "
          f"changes + {len(o.churn)} churn traps; scoring verified "
          f"(perfect/empty/noisy); dom-diff/strip recovers the full injected "
          f"set (F1 {live.f1}, FAR {live.false_alarm_rate}, "
          f"loc {live.localization}).")


def cmd_gen(a):
    from .fixtures_gen import generate
    root = generate(force=a.force)
    print(f"fixtures at {root}")


def cmd_diff_race(a):
    from .race import diff_race, format_leaderboard
    res = diff_race(runs=a.runs)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(format_leaderboard(res))


def cmd_pipeline(a):
    from .pipeline import run_pipeline, score_pipeline
    res = run_pipeline(differ=a.differ, norm=a.norm)
    score = score_pipeline(res)
    print(json.dumps({"outdir": res["outdir"],
                      "combo": f"{a.differ}/{a.norm}", **score}, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="watchdog_eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    g = sub.add_parser("gen-fixtures")
    g.add_argument("--force", action="store_true")
    g.set_defaults(fn=cmd_gen)
    r = sub.add_parser("diff-race")
    r.add_argument("--runs", type=int, default=3)
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=cmd_diff_race)
    pl = sub.add_parser("pipeline")
    pl.add_argument("--differ", default="dom-diff")
    pl.add_argument("--norm", default="strip")
    pl.set_defaults(fn=cmd_pipeline)
    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
