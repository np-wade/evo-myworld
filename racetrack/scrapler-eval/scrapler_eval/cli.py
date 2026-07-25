"""scrapler_eval CLI — run a bracket, print + write the leaderboard.

Usage:
  python -m scrapler_eval race [--bracket B.json] [--ladder L.json] [--out R.md]
  python -m scrapler_eval list          # show registered candidates
  python -m scrapler_eval selftest      # run the built-in baselines on the fixtures

A bracket file (json) is optional; without it, all registered candidates race
the default ladder. Bracket schema:
  {"name": "...", "candidates": ["raw-fetch-baseline", ...],
   "gates": {"retrieved_content": {"min_chars": 100}, "budget": {...}},
   "weights": {"quality": 0.5, ...}, "retries": 1}
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import adapters
from .harness import run_bracket, render_result_md
from .ladder import DEFAULT_LADDER, load_config, load_ladder
from .provenance import Heartbeat, result_header, stamp
from .store import RunStore


def _heartbeat_cb(hb: Heartbeat):
    def cb(kind: str, data: dict):
        hb.beat(f"{kind}: {data}", time.time())
    return cb


def cmd_race(args) -> int:
    ladder_path = Path(args.ladder) if args.ladder else DEFAULT_LADDER
    tasks = load_ladder(ladder_path)
    cfg = load_config(ladder_path)

    if args.bracket:
        spec = json.loads(Path(args.bracket).read_text())
        name = spec.get("name", "bracket")
        cands = adapters.build(spec.get("candidates", list(adapters.REGISTRY)))
        gate_spec = spec.get("gates", {"retrieved_content": {"min_chars": 100}})
        weights = spec.get("weights")
        retries = int(spec.get("retries", 1))
    else:
        name = "all-registered"
        cands = adapters.all_candidates()
        gate_spec = {"retrieved_content": {"min_chars": 100}}
        weights = None
        retries = 1

    out = Path(args.out) if args.out else Path(f"result-{name}.md")
    store_dir = out.parent / f".store-{name}"
    store = RunStore(store_dir)
    hb = Heartbeat(str(store_dir / "heartbeat.txt"), name)

    result = run_bracket(cands, tasks, gate_spec, cfg, store=store,
                         weights=weights, retries=retries,
                         on_event=_heartbeat_cb(hb))

    header = result_header(stamp(time.time()), name, len(cands), len(tasks))
    body = render_result_md(result, name)
    out.write_text(header + "\n\n" + body, encoding="utf-8")

    board = result["leaderboard"]
    print(f"\nRace '{name}': {len(cands)} candidates × {len(tasks)} tasks")
    for i, row in enumerate(board, 1):
        mark = " WINNER" if i == 1 else ""
        print(f"  {i}. {row.candidate:28s} lb={row.leaderboard:+.3f} "
              f"norm={row.normalized:5.1f} gate={row.gate_pass_rate:.0%}{mark}")
    print(f"\nfull result -> {out}")
    return 0


def cmd_list(args) -> int:
    for n, cls in sorted(adapters.REGISTRY.items()):
        inst = cls()
        print(f"  {n:28s} class={int(inst.weight_class)} "
              f"available={inst.available()} requires={inst.requires}")
    return 0


def cmd_selftest(args) -> int:
    args.bracket = None
    args.ladder = None
    args.out = str(Path(__file__).parent.parent / "result-selftest.md")
    return cmd_race(args)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scrapler_eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("race"); r.add_argument("--bracket"); r.add_argument("--ladder"); r.add_argument("--out")
    sub.add_parser("list")
    sub.add_parser("selftest")
    args = p.parse_args(argv)
    return {"race": cmd_race, "list": cmd_list, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
