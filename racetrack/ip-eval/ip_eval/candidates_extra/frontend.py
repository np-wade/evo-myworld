"""Frontend family — F11 candidates.

- ip-frontend-playwright: drives the incumbent Vite/React app with a
  hermetic Playwright chromium (browser installed inside the candidate venv
  via PLAYWRIGHT_BROWSERS_PATH=0 so it is purged with the venv).
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import (  # noqa: E402
    Candidate,
    IP_PROJECT,
    VENVS,
    provision_venv,
)

BASE_URL = "http://localhost:3000"
# Discovered from information-processer/src/App.jsx STAGES table (the app is a
# pushState-based SPA; "/" falls back to stage 1 via stageFromPath).
ROUTES = [
    "/",
    "/stage1-vault",
    "/stage2-split",
    "/stage3-tabilify",
    "/stage4-research",
    "/stage5-graph",
    "/stage6-writeup",
    "/stage7-combine",
    "/stage8-export",
]

# Playwright probe runner. Executed inside the candidate venv as
# `python -c RUNNER <probe>`; prints one JSON line {"pass", "detail"}.
_RUNNER = r'''
import json
import re
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
ROUTES = %r
DEEP_ROUTE = "/stage4-research"
DEEP_TAB_TEXT = "Research"


def _result(ok, detail):
    return {"pass": bool(ok), "detail": str(detail)[:400]}


def _root_text(page):
    text = page.locator("#root").inner_text(timeout=10000)
    return re.sub(r"\s+", " ", text).strip()


def routes_render(pw):
    browser = pw.chromium.launch(headless=True)
    try:
        page = browser.new_page()
        bad = []
        for route in ROUTES:
            resp = page.goto(BASE + route, wait_until="load", timeout=30000)
            status = resp.status if resp else None
            if status != 200:
                bad.append(f"{route}:status={status}")
                continue
            page.wait_for_selector("#root", timeout=10000)
            if not page.locator("#root").is_visible():
                bad.append(f"{route}:root-hidden")
                continue
            if not _root_text(page):
                bad.append(f"{route}:empty-root")
        if bad:
            return _result(False, "routes failed: " + ", ".join(bad))
        return _result(True, f"{len(ROUTES)}/{len(ROUTES)} routes 200 + non-empty #root")
    finally:
        browser.close()


def console_clean(pw):
    errors = []
    browser = pw.chromium.launch(headless=True)
    try:
        page = browser.new_page()
        current = {"route": "/"}

        def on_console(msg):
            if msg.type == "error":
                errors.append(f"console[{current['route']}]: {msg.text}")

        def on_pageerror(exc):
            errors.append(f"pageerror[{current['route']}]: {exc}")

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        for route in ROUTES:
            current["route"] = route
            page.goto(BASE + route, wait_until="load", timeout=30000)
            page.wait_for_timeout(800)
        real = [e for e in errors if "favicon" not in e.lower()]
        if real:
            return _result(False, f"{len(real)} console/page errors; first: {real[0]}")
        return _result(True, f"0 errors across {len(ROUTES)} routes"
                             + (f" ({len(errors) - len(real)} favicon whitelisted)"
                                if len(errors) != len(real) else ""))
    finally:
        browser.close()


def keyboard_focus(pw):
    browser = pw.chromium.launch(headless=True)
    try:
        page = browser.new_page()
        page.goto(BASE + "/stage1-vault", wait_until="load", timeout=30000)
        page.wait_for_selector("#root", timeout=10000)
        probe = """() => {
            const el = document.activeElement;
            if (!el || el === document.body || el === document.documentElement) return null;
            const cs = getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return {
                tag: el.tagName.toLowerCase(),
                cls: (el.className || '').toString().slice(0, 60),
                visible: r.width > 0 && r.height > 0
                         && cs.visibility !== 'hidden' && cs.display !== 'none',
                outlineStyle: cs.outlineStyle,
                outlineWidth: cs.outlineWidth,
                boxShadow: cs.boxShadow,
            };
        }"""
        for _ in range(8):
            page.keyboard.press("Tab")
            info = page.evaluate(probe)
            if info and info["visible"]:
                has_indicator = (
                    (info["outlineStyle"] != "none" and info["outlineWidth"] != "0px")
                    or info["boxShadow"] != "none"
                )
                if has_indicator:
                    return _result(True, f"focus on <{info['tag']} class={info['cls']!r}> "
                                         f"outline={info['outlineStyle']} {info['outlineWidth']} "
                                         f"shadow={info['boxShadow'][:40]!r}")
                return _result(False, f"focus moved to visible <{info['tag']} "
                                      f"class={info['cls']!r}> but no focus indicator "
                                      f"(outline={info['outlineStyle']}/{info['outlineWidth']}, "
                                      f"shadow={info['boxShadow'][:40]!r})")
        return _result(False, "Tab never landed on a visible focusable element (8 presses)")
    finally:
        browser.close()


def responsive_no_overflow(pw):
    browser = pw.chromium.launch(headless=True)
    try:
        bad = []
        for width, height in ((320, 800), (1440, 900)):
            page = browser.new_page(viewport={"width": width, "height": height})
            for route in ROUTES:
                page.goto(BASE + route, wait_until="load", timeout=30000)
                page.wait_for_selector("#root", timeout=10000)
                page.wait_for_timeout(300)
                m = page.evaluate("""() => ({
                    scroll: document.documentElement.scrollWidth,
                    client: document.documentElement.clientWidth,
                })""")
                if m["scroll"] > m["client"] + 1:
                    bad.append(f"{route}@{width}px: scrollWidth={m['scroll']} > clientWidth={m['client']}")
            page.close()
        if bad:
            return _result(False, "horizontal overflow: " + "; ".join(bad))
        return _result(True, f"no overflow on {len(ROUTES)} routes at 320x800 and 1440x900")
    finally:
        browser.close()


def deep_link_refresh(pw):
    browser = pw.chromium.launch(headless=True)
    try:
        page = browser.new_page()
        # fresh direct load of the deep route
        resp = page.goto(BASE + DEEP_ROUTE, wait_until="load", timeout=30000)
        if not resp or resp.status != 200:
            return _result(False, f"direct load of {DEEP_ROUTE} returned "
                                  f"{resp.status if resp else None}")
        page.wait_for_selector("#root", timeout=10000)
        page.wait_for_timeout(500)
        direct = _root_text(page)
        # client-side navigation from the entry point
        page.goto(BASE + "/", wait_until="load", timeout=30000)
        page.wait_for_selector("#root", timeout=10000)
        page.click(f"button.stage-tab:has-text('{DEEP_TAB_TEXT}')", timeout=10000)
        page.wait_for_url(f"**{DEEP_ROUTE}", timeout=10000)
        page.wait_for_timeout(500)
        navigated = _root_text(page)
        if not direct:
            return _result(False, f"{DEEP_ROUTE} rendered empty on direct load")
        if direct == navigated:
            return _result(True, f"{DEEP_ROUTE}: direct load == client-side nav "
                                 f"({len(direct)} chars)")
        return _result(False, f"{DEEP_ROUTE}: direct load differs from client nav "
                              f"(direct {len(direct)} chars vs nav {len(navigated)} chars)")
    finally:
        browser.close()


PROBES = {
    "routes_render": routes_render,
    "console_clean": console_clean,
    "keyboard_focus": keyboard_focus,
    "responsive_no_overflow": responsive_no_overflow,
    "deep_link_refresh": deep_link_refresh,
}

name = sys.argv[1]
fn = PROBES.get(name)
if fn is None:
    print(json.dumps(_result(False, f"unknown probe {name!r}")))
    raise SystemExit(0)
try:
    with sync_playwright() as pw:
        print(json.dumps(fn(pw)))
except Exception as exc:
    print(json.dumps(_result(False, f"{type(exc).__name__}: {exc}")))
''' % (ROUTES,)


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


class IpFrontendPlaywright(Candidate):
    name = "ip-frontend-playwright"
    stages = {"frontend"}

    def __init__(self):
        self._python: Path | None = None
        self._dev_proc: subprocess.Popen | None = None
        self._app_up = False

    # --- provisioning ------------------------------------------------------

    def available(self):
        python, reason = provision_venv("playwright", ["playwright"])
        if python is None:
            return False, reason
        install = subprocess.run(
            [str(python), "-m", "playwright", "install", "chromium"],
            capture_output=True, timeout=900,
            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": "0"},
        )
        if install.returncode != 0:
            shutil.rmtree(VENVS / "playwright", ignore_errors=True)
            return False, ("chromium install failed (purged): "
                           + install.stderr.decode()[-300:])
        self._python = python
        return True, ""

    # --- app lifecycle -----------------------------------------------------

    def _teardown(self):
        proc, self._dev_proc, self._app_up = self._dev_proc, None, False
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass

    def _ensure_app(self):
        if self._app_up and self._dev_proc and self._dev_proc.poll() is None:
            return
        if _http_ok(BASE_URL):
            raise RuntimeError(
                "port 3000 already serves HTTP before startup; "
                "not killing a foreign process, aborting probes")
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm not on PATH")
        self._dev_proc = subprocess.Popen(
            [npm, "run", "dev"], cwd=IP_PROJECT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
        atexit.register(self._teardown)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            code = self._dev_proc.poll()
            if code is not None:
                self._teardown()
                raise RuntimeError(f"npm run dev exited early (code {code})")
            if _http_ok(BASE_URL):
                self._app_up = True
                return
            time.sleep(0.5)
        self._teardown()
        raise RuntimeError("app did not respond 200 on :3000 within 90s")

    # --- probes ------------------------------------------------------------

    def frontend_probe(self, probe: str) -> dict:
        try:
            self._ensure_app()
        except Exception as exc:
            return {"pass": False, "detail": f"app startup: {exc}"[:200]}
        if probe not in ("routes_render", "console_clean", "keyboard_focus",
                         "responsive_no_overflow", "deep_link_refresh"):
            return {"pass": False, "detail": f"unknown probe {probe}"}
        try:
            proc = subprocess.run(
                [str(self._python), "-c", _RUNNER, probe],
                capture_output=True, timeout=300,
                env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": "0"},
            )
            lines = [l for l in proc.stdout.decode().splitlines() if l.strip()]
            if proc.returncode != 0 or not lines:
                return {"pass": False,
                        "detail": f"runner exit {proc.returncode}: "
                                  f"{proc.stderr.decode()[-300:]}"[:400]}
            out = json.loads(lines[-1])
            return {"pass": bool(out.get("pass")),
                    "detail": str(out.get("detail", ""))[:400]}
        except Exception as exc:
            return {"pass": False, "detail": f"{type(exc).__name__}: {exc}"[:400]}


CANDIDATES = [IpFrontendPlaywright]
