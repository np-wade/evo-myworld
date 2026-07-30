"""Racetrack results reader — surfaces the scraper/search benchmark suite
(racetrack/) inside the evo dashboard, so results show up natively in the app
instead of a standalone HTML.

Zero new storage: it reads what the eval packages already emit —
`racetrack/results/*-suite.md` cards + each package's `results-*.json` and
`pipeline-*.json` leaderboards — and returns structured data the Racetrack
page charts/tabulates. Read-only.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# suites in display order; package dir under racetrack/, card under results/
SUITES = [
    ("T1", "arxiv", "arxiv-eval", "arxiv-suite.md"),
    ("T2", "substack", "substack-eval", "substack-suite.md"),
    ("T3", "video", "video-eval", "video-suite.md"),
    ("T4", "watchdog", "watchdog-eval", "watchdog-suite.md"),
    ("T5", "crawl", "crawl-eval", None),
    ("T6", "ip", "ip-eval", "ip-suite.md"),
]


def find_racetrack_dir(root: Path) -> Path | None:
    """Locate racetrack/. Honors $EVO_RACETRACK_DIR, else searches the
    workspace root, this module's repo, and their parents."""
    env = os.environ.get("EVO_RACETRACK_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    seeds = [root, Path(__file__).resolve()]
    seen: set[Path] = set()
    for seed in seeds:
        for cand in (seed, *seed.parents):
            if cand in seen:
                continue
            seen.add(cand)
            rt = cand / "racetrack"
            if (rt / "results").is_dir() or (rt / "RACETRACK.md").exists():
                return rt
    return None


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _leaderboards_for(pkg_dir: Path) -> list[dict[str, Any]]:
    """Every results-*.json / pipeline-*.json in a package, newest run first,
    normalized to {name, kind, mode, meta, columns, rows}."""
    out: list[dict[str, Any]] = []
    files = sorted(pkg_dir.glob("results-*.json")) + sorted(pkg_dir.glob("pipeline-*.json"))
    for f in files:
        data = _load_json(f)
        if data is None:
            continue
        # results-<stage>-run<N>.json  ->  stage + run number
        m = re.match(r"(?:results-)?(.*?)-?run(\d+)\.json$", f.name)
        run = int(m.group(2)) if m else 0
        if f.name.startswith("pipeline"):
            stage = "pipeline"          # end-to-end scorecard
        else:
            stage = (m.group(1) if m else f.stem) or "overall"
        lb = data.get("leaderboard")
        entry: dict[str, Any] = {
            "file": f.name,
            "stage": stage or "pipeline",
            "run": run,
            "mode": data.get("mode", ""),
            "meta": {k: v for k, v in data.items()
                     if k not in ("leaderboard",) and not isinstance(v, (list, dict))},
        }
        if isinstance(lb, list) and lb and isinstance(lb[0], dict):
            cols: list[str] = []
            for row in lb:
                for k in row:
                    if k not in cols:
                        cols.append(k)
            entry["columns"] = cols
            entry["rows"] = lb
        else:
            # pipeline scorecards etc. — keep the raw object for display
            entry["raw"] = data
        out.append(entry)
    # newest stage-run pairing first
    out.sort(key=lambda e: (-e["run"], e["stage"]))
    return out


def _index_rows(results_dir: Path) -> dict[str, dict[str, str]]:
    """Parse the INDEX.md table so each suite carries its one-line situation +
    status straight from the card the lab already maintains."""
    idx = results_dir / "INDEX.md"
    rows: dict[str, dict[str, str]] = {}
    if not idx.exists():
        return rows
    for line in idx.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and re.match(r"T\d", cells[0]):
            rows[cells[0]] = {
                "suite": cells[1],
                "situation": cells[2],
                "package": cells[3].strip("`"),
                "status": cells[5],
            }
    return rows


def build_racetrack(root: Path) -> dict[str, Any]:
    rt = find_racetrack_dir(root)
    if rt is None:
        return {"available": False,
                "error": "racetrack/ not found (set EVO_RACETRACK_DIR)"}
    results_dir = rt / "results"
    idx = _index_rows(results_dir)
    status_line = ""
    status_file = rt / "STATUS"
    if status_file.exists():
        status_line = status_file.read_text(encoding="utf-8").strip()[:400]

    suites = []
    for tid, key, pkg, card in SUITES:
        pkg_dir = rt / pkg
        meta = idx.get(tid, {})
        card_md = ""
        if card and (results_dir / card).exists():
            card_md = (results_dir / card).read_text(encoding="utf-8")
        suites.append({
            "id": tid,
            "key": key,
            "title": meta.get("suite", key),
            "situation": meta.get("situation", ""),
            "status": meta.get("status", ""),
            "package": pkg,
            "built": pkg_dir.is_dir(),
            "card_md": card_md,
            "leaderboards": _leaderboards_for(pkg_dir) if pkg_dir.is_dir() else [],
        })

    return {
        "available": True,
        "racetrack_dir": str(rt),
        "status": status_line,
        "suites": suites,
    }
