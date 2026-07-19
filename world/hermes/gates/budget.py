#!/usr/bin/env python3
"""Budget gate — post-phase, per-stage spend cap.

The benchmark writes a side-channel budget.json (because gates do NOT
see EVO_* env — sdk-notes.md §3e; the result JSON is for scores, not
budget). This gate reads that file and exits 1 if any field exceeds a
per-stage ceiling.

Two modes, selected by flags (races ratchet vs absolute-cap, see
PRIOR-ART.md §2):

  --ceilings budgets.yaml   absolute cap: each field has a hard ceiling;
                            exceeding any one fails. (raven variant)
  --baseline baseline.json --toleration-percent P   ratchet: each
                            field has a frozen baseline; fails when
                            the current value rose by more than P%
                            above the baseline. (OmniRoute variant)

Both modes accept a missing field as a pass for that field (graceful
degrade — adk-rust BaselineStore pattern, baseline.rs:121-130).

Usage:
    python budget.py --stage intake \\
        --budget-file {worktree}/.evo/budget.json \\
        --ceiliers budgets.yaml

evo contract: post-phase gate. Reads the side-channel by an explicit
path, never EVO_* env. Exit 0 = pass, 1 = fail, 2 = misconfigured.

Prior art:
  - OmniRoute budgetGate.ts:46-62 (ratchet, % delta vs baseline)
  - raven before_iteration_hook.py:41-63 (absolute cap, byte/4 est)
See world/hermes/gates/PRIOR-ART.md §2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    if not path.is_file():
        print(f"budget: budget file not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"budget: malformed budget.json: {exc}", file=sys.stderr)
        sys.exit(2)


def load_ceilings_yaml(path: Path, stage: str) -> dict:
    """Minimal YAML reader for the flat mapping we need:
        stages:
          intake:
            tokens: 100000
            usd: 5.0
    No external dep — stdlib only (the lab avoids heavy imports,
    CHARTER gotcha on WSL2 RAM)."""
    if not path.is_file():
        print(f"budget: ceilings file not found: {path}", file=sys.stderr)
        sys.exit(2)
    text = path.read_text(encoding="utf-8")
    stages: dict[str, dict[str, float]] = {}
    cur_stage: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        body = line.strip()
        if indent == 0 and body.endswith(":"):
            cur_stage = body[:-1].strip()
            stages[cur_stage] = {}
            continue
        if indent == 0 and body == "stages:":
            continue
        if indent >= 2 and ":" in body and cur_stage is not None:
            key, _, val = body.partition(":")
            try:
                stages[cur_stage][key.strip()] = float(val.strip())
            except ValueError:
                continue
    return stages.get(stage, {})


def main() -> None:
    p = argparse.ArgumentParser(description="Budget gate")
    p.add_argument("--stage", required=True)
    p.add_argument("--budget-file", required=True,
                   help="JSON written by the benchmark: {field: value}")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--ceilings", help="YAML of per-stage hard ceilings")
    g.add_argument("--baseline",
                   help="JSON baseline for ratchet mode")
    p.add_argument("--toleration-percent", type=float, default=2.0,
                   help="Ratchet tolerance (%% above baseline allowed)")
    args = p.parse_args()

    current = load_json(Path(args.budget_file))
    if not isinstance(current, dict):
        print("budget: budget.json must be a JSON object", file=sys.stderr)
        sys.exit(2)

    if args.ceilings:
        ceilings = load_ceilings_yaml(Path(args.ceilings), args.stage)
        if not ceilings:
            print(f"budget: WARN no ceilings for stage={args.stage!r}; "
                  f"passing (no rule = no failure)", file=sys.stderr)
            sys.exit(0)
        for field, cap in ceilings.items():
            val = current.get(field)
            if val is None:
                continue
            if float(val) > cap:
                print(f"budget: FAIL stage={args.stage} field={field} "
                      f"value={val} ceiling={cap}", file=sys.stderr)
                sys.exit(1)
        print(f"budget: PASS stage={args.stage} "
              f"(checked {len(ceilings)} ceilings)", file=sys.stderr)
        sys.exit(0)

    # ratchet mode
    baseline = load_json(Path(args.baseline))
    if not isinstance(baseline, dict):
        print("budget: baseline must be a JSON object", file=sys.stderr)
        sys.exit(2)
    checked = 0
    for field, base in baseline.items():
        cur = current.get(field)
        if cur is None or base <= 0:
            continue
        checked += 1
        delta_pct = ((float(cur) - float(base)) / float(base)) * 100.0
        if delta_pct > args.toleration_percent:
            print(f"budget: FAIL stage={args.stage} field={field} "
                  f"baseline={base} current={cur} "
                  f"delta={delta_pct:.2f}% tol={args.toleration_percent}%",
                  file=sys.stderr)
            sys.exit(1)
    print(f"budget: PASS stage={args.stage} "
          f"(checked {checked} fields, ratchet {args.toleration_percent}%)",
          file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()