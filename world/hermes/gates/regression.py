#!/usr/bin/env python3
"""Regression gate — pre-phase, parent-score comparison.

Compares a cheap proxy metric on the stage's worktree against the
parent's committed proxy score; if worse beyond a tolerance, exits 1
BEFORE the benchmark runs (pre-phase saves benchmark spend,
sdk-notes.md §3d). This is the recursive-testing cull hook — the
"which code deserves to live" discipline the charter wants.

Two shapes (race: absolute-delta vs percentage-drop, PRIOR-ART.md §3):

  --mode absolute    fail when parent - current > tolerance
                     (adk-rust BaselineStore::check_regressions,
                      baseline.rs:138-147)
  --mode percent     fail when (parent - current) / parent > tolerance
                     (repowise density_regression, kg_checks.py:347-367)

Default --mode percent, --tolerance 0.0 (any regression fails; raise
to allow small regressions through).

The parent's proxy score is read from a JSON file the caller passes
explicitly (typically written by the previous winning experiment's
benchmark). evo records scores in the experiment graph node; the run
config can dump the parent's committed score to a sidecar before this
gate runs. We do NOT read EVO_* env (gates don't see it, sdk-notes.md
§3e).

Usage:
    python regression.py \\
        --parent-score parent_proxy.json \\
        --current-score {worktree}/proxy_score.json \\
        --field score --mode percent --tolerance 0.0

parent_proxy.json / proxy_score.json: {"score": <float>, ...}
A missing file on the parent side = no baseline = pass (graceful,
adk-rust pattern). A missing file on the current side = misconfigured
= exit 2.

Prior art:
  - adk-rust BaselineStore::check_regressions, baseline.rs:116-154
  - repowise density_regression, kg_checks.py:347-367
See world/hermes/gates/PRIOR-ART.md §3.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def read_score(path: Path, field: str) -> float | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"regression: malformed score file {path}: {exc}",
              file=sys.stderr)
        sys.exit(2)
    val = data.get(field) if isinstance(data, dict) else None
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        print(f"regression: field {field!r} in {path} is not a number",
              file=sys.stderr)
        sys.exit(2)


def main() -> None:
    p = argparse.ArgumentParser(description="Regression gate")
    p.add_argument("--parent-score", required=True,
                   help="JSON with parent's committed proxy score")
    p.add_argument("--current-score", required=True,
                   help="JSON with current stage's proxy score")
    p.add_argument("--field", default="score",
                   help="JSON key holding the score (default: score)")
    p.add_argument("--mode", choices=["absolute", "percent"],
                   default="percent")
    p.add_argument("--tolerance", type=float, default=0.0,
                   help="Allowed regression: absolute points (absolute) or "
                        "fraction (percent, 0.05 = 5%%). Default 0.0.")
    args = p.parse_args()

    parent = read_score(Path(args.parent_score), args.field)
    if parent is None:
        # No baseline → no regression (adk-rust graceful-skip pattern).
        print("regression: PASS (no parent baseline — skipping)",
              file=sys.stderr)
        sys.exit(0)

    current_path = Path(args.current_score)
    if not current_path.is_file():
        print(f"regression: current score file missing: {current_path}",
              file=sys.stderr)
        sys.exit(2)
    current = read_score(current_path, args.field)
    if current is None:
        print(f"regression: field {args.field!r} missing from "
              f"{current_path}", file=sys.stderr)
        sys.exit(2)

    delta = parent - current  # positive = current is worse

    if args.mode == "absolute":
        failed = delta > args.tolerance
        metric = f"delta={delta:.6f} tol={args.tolerance:.6f} (absolute)"
    else:  # percent
        if parent <= 0:
            # parent 0 or negative: percent is undefined; fall back to
            # absolute with the same tolerance value so a 0-parent isn't
            # an automatic pass. (repowise skips zero baselines; we don't
            # because a zero parent is itself a signal worth failing on
            # if the current also regressed.)
            failed = delta > args.tolerance
            metric = (f"delta={delta:.6f} parent<=0 → absolute fallback, "
                      f"tol={args.tolerance:.6f}")
        else:
            pct = delta / parent
            failed = pct > args.tolerance
            metric = (f"parent={parent:.6f} current={current:.6f} "
                      f"delta={delta:.6f} ({pct*100:.2f}%) "
                      f"tol={args.tolerance*100:.2f}%")

    if failed:
        print(f"regression: FAIL {metric}", file=sys.stderr)
        sys.exit(1)
    print(f"regression: PASS {metric}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()