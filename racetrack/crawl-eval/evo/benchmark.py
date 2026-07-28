"""benchmark.py — the T5 evo benchmark: optimize the fetch-ESCALATION policy.

Contract (matches tests/fixtures/*/benchmark.py):
    python benchmark.py --agent <path/to/policy.py>
      -> loads solve() from the agent, scores it on the scenario tasks,
         writes per-task traces to $EVO_TRACES_DIR/task_<id>.json,
         prints {"score": float, "tasks": {id: reward}} to stdout.

Unlike a toy benchmark, each task stands up a REAL crawl-eval server and runs the
REAL fetch tiers, so the score reflects actual scraping behavior:

    plain         a normal static page            -> minimal tier: static
    ja3_wall      the JA3 TLS wall (hardened.py)   -> minimal tier: impersonate
    js_nav        fetch()-injected links (/store)  -> minimal tier: browser
    js_challenge  JA3 wall + JS challenge          -> minimal tier: browser

The policy sees two cheap probe results (static + impersonate) and must pick the
cheapest tier that actually reaches content. Reward = 1.0 minimal / 0.7 over-
provisioned / 0.0 miss. MUST run under crawl-eval/.venv (needs curl_cffi +
playwright); missing a tool degrades that tier, not the harness.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))            # import the crawl_eval package

from crawl_eval.hardened import HardenedServer          # noqa: E402
from crawl_eval.site_server import SiteServer           # noqa: E402

TIER_COST = {"static": 1, "impersonate": 2, "browser": 3}
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/125.0 Safari/537.36")


def _unverified():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


# ---- the four scenarios; each returns (server, url, content_marker) ----
def _plain():
    s = SiteServer(); return s, s.base + "/about", "About Acme"


def _js_nav():
    s = SiteServer(); return s, s.base + "/store", "/product/"


def _ja3():
    s = HardenedServer(); return s, s.base + "/", "passed the bot wall"


def _js_challenge():
    s = HardenedServer(js_challenge=True); return s, s.base + "/", "/human-only"


TASKS = [
    {"id": "plain", "make": _plain, "minimal": "static"},
    {"id": "ja3_wall", "make": _ja3, "minimal": "impersonate"},
    {"id": "js_nav", "make": _js_nav, "minimal": "browser"},
    {"id": "js_challenge", "make": _js_challenge, "minimal": "browser"},
]


# ---- fetch tiers (return response text, "" on failure) ----
def fetch_static(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        r = urllib.request.urlopen(req, timeout=8, context=_unverified())
        return r.read().decode("utf-8", "replace")
    except Exception:
        return ""


def fetch_impersonate(url):
    try:
        from curl_cffi import requests as cr
        r = cr.get(url, impersonate="chrome", verify=False, timeout=8)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def fetch_browser(url, renderer):
    try:
        out = renderer.fetch(url)
        return out.text if out.ok else ""
    except Exception:
        return ""


def _signal(text, marker):
    reached = marker in text
    return {"status": 200 if text else 403,
            "reached": reached, "blocked": text == "",
            "js_hint": bool(text) and ("<script" in text) and not reached}


def load_solve(agent_path):
    spec = importlib.util.spec_from_file_location("t5_policy", agent_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.solve


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    args = ap.parse_args()
    solve = load_solve(Path(args.agent))

    traces = os.environ.get("EVO_TRACES_DIR")
    if traces:
        Path(traces).mkdir(parents=True, exist_ok=True)

    # one browser for the whole run (opened lazily; may be unavailable)
    renderer = None
    try:
        from crawl_eval.crawl import PlaywrightRenderer
        r = PlaywrightRenderer()
        if r.available():
            r.open(); renderer = r
    except Exception:
        renderer = None

    results = {}
    try:
        for task in TASKS:
            srv, url, marker = task["make"]()
            try:
                st_text = fetch_static(url)
                im_text = fetch_impersonate(url)
                signals = {"static": _signal(st_text, marker),
                           "impersonate": _signal(im_text, marker)}
                try:
                    tier = solve(signals)
                except Exception as e:
                    tier = f"error:{e}"
                # execute the chosen tier for real
                if tier == "static":
                    text = st_text
                elif tier == "impersonate":
                    text = im_text
                elif tier == "browser":
                    text = fetch_browser(url, renderer) if renderer else ""
                else:
                    text = ""
                reached = marker in text
                minimal = task["minimal"]
                if not reached:
                    reward = 0.0
                elif tier == minimal:
                    reward = 1.0
                else:
                    reward = 0.7          # reached but over-provisioned
                results[task["id"]] = reward
                if traces:
                    Path(traces, f"task_{task['id']}.json").write_text(json.dumps({
                        "experiment_id": "t5_escalation",
                        "task_id": task["id"],
                        "status": "passed" if reward >= 0.7 else "failed",
                        "score": reward,
                        "summary": f"chose={tier} minimal={minimal} reached={reached}",
                        "failure_reason": None if reached else "did_not_reach_content",
                        "events": [{"name": "route", "attributes": {
                            "tier": tier, "minimal": minimal,
                            "cost": TIER_COST.get(tier, 0), "signals": signals}}],
                    }, indent=2))
            finally:
                srv.stop()
    finally:
        if renderer:
            renderer.close()

    score = sum(results.values()) / len(results) if results else 0.0
    print(json.dumps({"score": round(score, 4), "tasks": results}, indent=2))


if __name__ == "__main__":
    main()
