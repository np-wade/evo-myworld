#!/usr/bin/env python3
"""Correctness gate — post-phase, golden-case assertion.

Reads a golden set (JSONL: one {id, input, expected} per line), runs
the stage's product against each case via a user-supplied solver
command, exits 1 on the first mismatch.

Usage:
    python correctness.py \\
        --golden golden/<stage>.jsonl \\
        --solver "python {target}/solve.py" \\
        --input-field input --expected-field expected

The solver command is invoked once per golden case with the case's
`input` on stdin. The solver's stdout (stripped) must equal the case's
`expected` (stripped). A non-zero exit from the solver itself counts
as a failure of that case.

evo contract (sdk-notes.md §3a): this is a gate, not a benchmark. It
must NOT read any EVO_* env var (cli.py:3232 strips them anyway). It
gets the worktree path via the {target} template that `evo` fills in
when the gate command runs. It writes nothing — pure exit code.

Prior art:
  - tests/fixtures/auto_harness_demo/gate.py:35-44 (case-list variant)
  - nocodb docker-compose/.../helpers.bash:58 (file-snapshot variant)
See world/hermes/gates/PRIOR-ART.md §1.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_solver(solver_cmd: str, case_input: str) -> tuple[int, str]:
    proc = subprocess.run(
        solver_cmd, shell=True, input=case_input,
        capture_output=True, text=True, timeout=120,
    )
    return proc.returncode, proc.stdout.strip()


def main() -> None:
    p = argparse.ArgumentParser(description="Correctness gate")
    p.add_argument("--golden", required=True, help="JSONL file of golden cases")
    p.add_argument("--solver", required=True,
                   help="Shell command; case input is piped to stdin, "
                        "stdout must equal the expected field")
    p.add_argument("--input-field", default="input")
    p.add_argument("--expected-field", default="expected")
    p.add_argument("--id-field", default="id")
    args = p.parse_args()

    golden_path = Path(args.golden)
    if not golden_path.is_file():
        print(f"correctness: golden file not found: {golden_path}",
              file=sys.stderr)
        sys.exit(2)

    n = 0
    with golden_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            case = json.loads(line)
            case_id = case.get(args.id_field, str(n))
            inp = case.get(args.input_field, "")
            expected = str(case.get(args.expected_field, "")).strip()
            n += 1

            try:
                rc, got = run_solver(args.solver, inp)
            except subprocess.TimeoutExpired:
                print(f"correctness: FAIL case={case_id} reason=timeout",
                      file=sys.stderr)
                sys.exit(1)
            if rc != 0:
                print(f"correctness: FAIL case={case_id} solver_rc={rc} "
                      f"expected={expected!r}", file=sys.stderr)
                sys.exit(1)
            if got != expected:
                print(f"correctness: FAIL case={case_id} got={got!r} "
                      f"expected={expected!r}", file=sys.stderr)
                sys.exit(1)

    print(f"correctness: PASS ({n} cases)", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()