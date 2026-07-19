#!/usr/bin/env python3
"""Self-tests for the gate library. Pure stdlib, fast.

Run:  python3 test_gates.py
Exit 0 = all gates behave under their evo contract.

Tests cover the load-bearing behaviors only:
  - exit codes (0 pass / 1 fail / 2 misconfig)
  - graceful degrade on missing baseline (regression)
  - ratchet vs absolute-cap (budget)
  - per-case solver invocation (correctness, held_out)
  - threshold semantics (held_out)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def run(script: str, *args: str, stdin: str | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        [PY, str(HERE / script), *args],
        capture_output=True, text=True, timeout=30, input=stdin,
    )
    return proc.returncode, proc.stdout, proc.stderr


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_correctness_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        golden = td / "g.jsonl"
        write_jsonl(golden, [
            {"id": "0", "input": "hi", "expected": "ok"},
            {"id": "1", "input": "bye", "expected": "ok"},
        ])
        solver = f"{PY} -c \"import sys; print('ok')\""
        rc, _, err = run("correctness.py", "--golden", str(golden),
                         "--solver", solver)
        assert rc == 0, f"expected pass, got rc={rc} err={err}"


def test_correctness_fails_on_mismatch() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        golden = td / "g.jsonl"
        write_jsonl(golden, [{"id": "0", "input": "x", "expected": "ok"}])
        solver = f"{PY} -c \"import sys; print('wrong')\""
        rc, _, err = run("correctness.py", "--golden", str(golden),
                         "--solver", solver)
        assert rc == 1, f"expected fail, got rc={rc} err={err}"


def test_correctness_missing_golden_exit2() -> None:
    rc, _, _ = run("correctness.py", "--golden", "/no/such.jsonl",
                   "--solver", "true")
    assert rc == 2, f"expected 2, got {rc}"


def test_budget_absolute_pass() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        b = td / "b.json"
        write_json(b, {"tokens": 50, "usd": 0.1})
        ceil = td / "c.yaml"
        ceil.write_text(textwrap.dedent("""\
            stages:
              intake:
                tokens: 100000
                usd: 5.0
            """), encoding="utf-8")
        rc, _, err = run("budget.py", "--stage", "intake",
                         "--budget-file", str(b), "--ceilings", str(ceil))
        assert rc == 0, f"expected pass, got rc={rc} err={err}"


def test_budget_absolute_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        b = td / "b.json"
        write_json(b, {"tokens": 200000})
        ceil = td / "c.yaml"
        ceil.write_text("stages:\n  intake:\n    tokens: 100000\n",
                        encoding="utf-8")
        rc, _, err = run("budget.py", "--stage", "intake",
                         "--budget-file", str(b), "--ceilings", str(ceil))
        assert rc == 1, f"expected fail, got rc={rc} err={err}"


def test_budget_ratchet_pass_on_improvement() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cur = td / "cur.json"
        base = td / "base.json"
        write_json(cur, {"tokens": 80})
        write_json(base, {"tokens": 100})
        rc, _, err = run("budget.py", "--stage", "intake",
                         "--budget-file", str(cur), "--baseline", str(base),
                         "--toleration-percent", "2.0")
        assert rc == 0, f"expected pass (cost fell), got rc={rc} err={err}"


def test_budget_ratchet_fail_on_regression() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cur = td / "cur.json"
        base = td / "base.json"
        write_json(cur, {"tokens": 110})
        write_json(base, {"tokens": 100})
        rc, _, err = run("budget.py", "--stage", "intake",
                         "--budget-file", str(cur), "--baseline", str(base),
                         "--toleration-percent", "2.0")
        assert rc == 1, f"expected fail (10%% > 2%% tol), got rc={rc} err={err}"


def test_budget_missing_field_passes() -> None:
    # Graceful: a field absent in budget.json must not fail.
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        b = td / "b.json"
        write_json(b, {"tokens": 50})  # no `usd`
        ceil = td / "c.yaml"
        ceil.write_text("stages:\n  intake:\n    tokens: 100\n    usd: 1.0\n",
                        encoding="utf-8")
        rc, _, err = run("budget.py", "--stage", "intake",
                         "--budget-file", str(b), "--ceilings", str(ceil))
        assert rc == 0, f"expected pass, got rc={rc} err={err}"


def test_regression_no_parent_passes() -> None:
    # No parent baseline = pass (adk-rust graceful-skip).
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cur = td / "cur.json"
        write_json(cur, {"score": 0.5})
        rc, _, err = run("regression.py",
                         "--parent-score", str(td / "nope.json"),
                         "--current-score", str(cur))
        assert rc == 0, f"expected pass (no baseline), got rc={rc} err={err}"


def test_regression_percent_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cur = td / "cur.json"
        par = td / "par.json"
        write_json(cur, {"score": 0.80})
        write_json(par, {"score": 1.00})
        rc, _, err = run("regression.py",
                         "--parent-score", str(par),
                         "--current-score", str(cur),
                         "--mode", "percent", "--tolerance", "0.05")
        assert rc == 1, f"expected fail (20%% > 5%%), got rc={rc} err={err}"


def test_regression_percent_pass_within_tol() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cur = td / "cur.json"
        par = td / "par.json"
        write_json(cur, {"score": 0.97})
        write_json(par, {"score": 1.00})
        rc, _, err = run("regression.py",
                         "--parent-score", str(par),
                         "--current-score", str(cur),
                         "--mode", "percent", "--tolerance", "0.05")
        assert rc == 0, f"expected pass (3%% < 5%%), got rc={rc} err={err}"


def test_regression_missing_current_exit2() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        par = td / "par.json"
        write_json(par, {"score": 1.0})
        rc, _, _ = run("regression.py",
                       "--parent-score", str(par),
                       "--current-score", str(td / "nope.json"))
        assert rc == 2, f"expected 2 (misconfig), got {rc}"


def test_held_out_pass() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        held = td / "h.jsonl"
        write_jsonl(held, [
            {"id": "0", "input": "a", "expected": "ok"},
            {"id": "1", "input": "b", "expected": "ok"},
        ])
        solver = f"{PY} -c \"import sys; print('ok')\""
        rc, _, err = run("held_out.py", "--held-out", str(held),
                         "--solver", solver, "--threshold", "1.0")
        assert rc == 0, f"expected pass, got rc={rc} err={err}"


def test_held_out_fail_below_threshold() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        held = td / "h.jsonl"
        write_jsonl(held, [
            {"id": "0", "input": "a", "expected": "ok"},
            {"id": "1", "input": "b", "expected": "ok"},
        ])
        # Solver prints 'wrong' — 0/2 pass.
        solver = f"{PY} -c \"import sys; print('wrong')\""
        rc, _, err = run("held_out.py", "--held-out", str(held),
                         "--solver", solver, "--threshold", "0.5")
        assert rc == 1, f"expected fail (0 < 0.5), got rc={rc} err={err}"


def test_held_out_empty_set_exit2() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        held = td / "h.jsonl"
        held.write_text("", encoding="utf-8")
        solver = f"{PY} -c \"import sys; print('ok')\""
        rc, _, err = run("held_out.py", "--held-out", str(held),
                         "--solver", solver)
        assert rc == 2, f"expected 2 (empty set), got rc={rc} err={err}"


def main() -> None:
    tests = [v for k, v in sorted(globals().items())
            if k.startswith("test_") and callable(v)]
    n_fail = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as exc:
            n_fail += 1
            print(f"  FAIL  {t.__name__}  {exc}")
        except Exception as exc:  # noqa: BLE001
            n_fail += 1
            print(f" ERROR  {t.__name__}  {type(exc).__name__}: {exc}")
    print(f"\n{len(tests)-n_fail}/{len(tests)} passed")
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()