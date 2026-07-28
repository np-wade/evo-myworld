"""gate.py — baseline-safe guard for the T5 escalation benchmark.

A candidate policy must at least route a PLAIN page to a tier that reaches it
(any tier does). If a mutation can't even do that, it's broken -> exit 1, and
evo discards it before wasting a full benchmark run. Matches the gate contract in
tests/fixtures/auto_harness_demo/gate.py.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from crawl_eval.site_server import SiteServer   # noqa: E402
from benchmark import fetch_browser, fetch_impersonate, fetch_static  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    args = ap.parse_args()
    spec = importlib.util.spec_from_file_location("t5_policy_gate", args.agent)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    s = SiteServer()
    try:
        url = s.base + "/about"
        st = fetch_static(url)
        sig = {"status": 200, "reached": "About Acme" in st, "blocked": False,
               "js_hint": False}
        signals = {"static": sig, "impersonate": sig}
        tier = mod.solve(signals)
        # the chosen tier must actually reach the plain page
        text = {"static": st, "impersonate": fetch_impersonate(url)}.get(tier, st)
        ok = "About Acme" in text
    finally:
        s.stop()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
