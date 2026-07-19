#!/usr/bin/env python3
"""Held-out gate — post-phase, generalization check.

Runs the stage's product on a held-out slice the benchmark never saw,
exits 1 if the held-out score drops below a threshold. This is the
overfitting check — the thing that deletes code that memorized the
benchmark instead of generalizing.

Design (races paired-overfit vs single-threshold, PRIOR-ART.md §4):
This script implements the single-threshold variant (ruvector
learned_weights_beat_chance_on_held_out, weight_learning.rs:460-487)
because it's the natural fit for the assembly line — the benchmark
already runs on the training set; this gate runs on a disjoint slice
and asserts one scalar threshold. The paired-overfit variant
(Lightning-AI overfit_batches) needs a separate training run and only
pays off when we explicitly suspect memorization; the README documents
how to wire that as a separate gate if needed.

Usage:
    python held_out.py \\
        --held-out golden/<stage>.held_out.jsonl \\
        --solver "python {target}/solve.py" \\
        --input-field input --expected-field expected \\
        --threshold 0.7

Each held-out case is one JSONL line {id, input, expected}. The
solver gets the case input on stdin and prints its answer on stdout
(99s timeout per case — held-out sets should be small). Score =
fraction of cases where stripped(stdout) == stripped(expected).
--threshold is the minimum score required to pass (default 0.7,
ruvector's value). Exit 1 if score < threshold.

evo contract: post-phase gate. No EVO_* env. {target} is filled by
evo when the gate command runs. Writes nothing. Pure exit code.

Prior art:
  - ruvector learned_weights_beat_chance_on_held_out,
    weight_learning.rs:460-487 (train/val split, AUC > 0.7 assert)
  - Lightning-AI overfit_batches, test_overfit_batches.py:175-200
    (paired overfit + disjoint eval)
See world/hermes/gates/PRIOR-ART.md §4.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="Held-out generalization gate")
    p.add_argument("--held-out", required=True,
                   help="JSONL of held-out cases {id, input, expected}")
    p.add_argument("--solver", required=True,
                   help="Shell command; case input on stdin, "
                        "stdout = prediction")
    p.add_argument("--input-field", default="input")
    p.add_argument("--expected-field", default="expected")
    p.add_argument("--id-field", default="id")
    p.add_argument("--threshold", type=float, default=0.7,
                   help="Minimum fraction of cases that must pass "
                        "(default 0.7)")
    p.add_argument("--per-case-timeout", type=float, default=99.0,
                   help="Per-case solver timeout seconds (default 99)")
    args = p.parse_args()

    if not 0.0 <= args.threshold <= 1.0:
        print(f"held_out: --threshold must be in [0,1], got "
              f"{args.threshold}", file=sys.stderr)
        sys.exit(2)

    held_path = Path(args.held_out)
    if not held_path.is_file():
        print(f"held_out: held-out file not found: {held_path}",
              file=sys.stderr)
        sys.exit(2)

    n_total = 0
    n_pass = 0
    failures: list[str] = []
    with held_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            case = json.loads(line)
            case_id = case.get(args.id_field, str(n_total))
            inp = case.get(args.input_field, "")
            expected = str(case.get(args.expected_field, "")).strip()
            n_total += 1
            try:
                proc = subprocess.run(
                    args.solver, shell=True, input=inp,
                    capture_output=True, text=True,
                    timeout=args.per_case_timeout,
                )
            except subprocess.TimeoutExpired:
                failures.append(f"{case_id}: timeout")
                continue
            if proc.returncode != 0:
                failures.append(f"{case_id}: solver_rc={proc.returncode}")
                continue
            if proc.stdout.strip() == expected:
                n_pass += 1
            else:
                failures.append(f"{case_id}: got={proc.stdout.strip()!r} "
                                f"expected={expected!r}")

    score = (n_pass / n_total) if n_total else 0.0
    if n_total == 0:
        print("held_out: FAIL — no cases in held-out set", file=sys.stderr)
        sys.exit(2)
    if score < args.threshold:
        head = "; ".join(failures[:5])
        more = f" (+{len(failures)-5} more)" if len(failures) > 5 else ""
        print(f"held_out: FAIL score={score:.4f} threshold={args.threshold:.4f} "
              f"({n_pass}/{n_total}); first failures: {head}{more}",
              file=sys.stderr)
        sys.exit(1)
    print(f"held_out: PASS score={score:.4f} threshold={args.threshold:.4f} "
          f"({n_pass}/{n_total})", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()