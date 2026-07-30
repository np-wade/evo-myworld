#!/usr/bin/env python3
"""Render one leaderboard chart per ip-eval stage, each in a different visual
style, as PNG screenshots into a Desktop folder.

Usage: python3 make_charts.py [outdir]
Defaults to the Windows OneDrive Desktop via /mnt/c when present.
"""
import glob
import html
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TODAY = date.today().isoformat()
SHELL_BIN = (Path.home() / ".cache/ms-playwright/chromium_headless_shell-1234"
             "/chrome-headless-shell-linux64/chrome-headless-shell")

STAGE_ORDER = [
    "convert", "extract", "split", "concepts", "tabilify", "retrieval",
    "graph", "drafting", "dedup", "export_docx", "export_bibtex",
    "persistence", "api", "security", "frontend",
]

STYLES = {
    "midnight":  dict(bg="#0d1117", fg="#e6edf3", bar="#58a6ff", ipb="#f0b429",
                      card="#161b22", sub="#8b949e", font="'Segoe UI',sans-serif", extra=""),
    "terminal":  dict(bg="#0c0c0c", fg="#33ff66", bar="#33ff66", ipb="#ffff55",
                      card="#0c0c0c", sub="#1fbf50", font="'Courier New',monospace",
                      extra=".card{border:1px solid #33ff66;border-radius:0}"),
    "blueprint": dict(bg="#1e3a5f", fg="#ffffff", bar="#9ecfff", ipb="#ffd166",
                      card="#26507f", sub="#bcd8f5", font="'Trebuchet MS',sans-serif",
                      extra=".card{background-image:repeating-linear-gradient(0deg,transparent,transparent 24px,rgba(255,255,255,.06) 25px),repeating-linear-gradient(90deg,transparent,transparent 24px,rgba(255,255,255,.06) 25px)}"),
    "pastel":    dict(bg="#fdf6ec", fg="#4a3f35", bar="#f4a261", ipb="#2a9d8f",
                      card="#ffffff", sub="#a08c7d", font="'Comic Sans MS','Segoe UI',sans-serif", extra=""),
    "newspaper": dict(bg="#f8f5f0", fg="#1a1a1a", bar="#1a1a1a", ipb="#8b0000",
                      card="#ffffff", sub="#666666", font="Georgia,serif",
                      extra=".card{border:2px solid #1a1a1a;border-radius:0;box-shadow:none}.bar{border-radius:0}.bar-fill{border-radius:0}"),
    "neon":      dict(bg="#12002e", fg="#f3e8ff", bar="#c77dff", ipb="#06d6a0",
                      card="#1e0049", sub="#b892e8", font="'Verdana',sans-serif",
                      extra=".bar-fill{box-shadow:0 0 12px #c77dff}.ip-row .bar-fill{box-shadow:0 0 12px #06d6a0}"),
    "forest":    dict(bg="#10241a", fg="#e8f5e9", bar="#66bb6a", ipb="#ffca28",
                      card="#16301f", sub="#8fbc8f", font="'Palatino Linotype',serif", extra=""),
    "candy":     dict(bg="#fff0f6", fg="#5c2137", bar="#ff5d8f", ipb="#3a86ff",
                      card="#ffffff", sub="#b98aa0", font="'Trebuchet MS',sans-serif", extra=""),
}

TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}}
body{{background:{bg};color:{fg};font-family:{font};margin:0;padding:28px}}
.card{{background:{card};border-radius:14px;padding:22px 26px;max-width:900px;margin:0 auto;
      box-shadow:0 2px 10px rgba(0,0,0,.25)}}
h1{{font-size:24px;margin:0 0 2px;text-transform:capitalize}}
.mode{{color:{sub};font-size:12.5px;margin:0 0 18px}}
.row{{margin:10px 0}}
.name{{font-size:13.5px;font-weight:600;display:flex;justify-content:space-between}}
.badge{{font-size:10px;padding:1px 7px;border-radius:999px;margin-left:8px;vertical-align:middle}}
.pass{{background:rgba(46,160,67,.25);color:#3fb950}}
.fail{{background:rgba(248,81,73,.25);color:#f85149}}
.bar{{height:16px;background:rgba(128,128,128,.18);border-radius:999px;overflow:hidden;margin-top:3px}}
.bar-fill{{height:100%;background:{bar};border-radius:999px}}
.ip-row .bar-fill{{background:{ipb}}}
.ip-row .name::before{{content:"★ ";color:{ipb}}}
.score{{font-size:12px;color:{sub};margin-top:2px}}
.meta{{font-size:11px;color:{sub};margin-top:14px}}
{extra}
</style></head><body><div class="card">
<h1>{title}</h1><p class="mode">{mode}</p>
{rows}
<p class="meta">{meta}</p>
</div></body></html>"""


def latest_results():
    latest = {}
    for f in HERE.glob("results-*-run*.json"):
        m = re.match(r"results-(.+)-run(\d+)\.json$", f.name)
        if not m:
            continue
        stage, n = m.group(1), int(m.group(2))
        if stage not in latest or n > latest[stage][1]:
            latest[stage] = (f, n)
    return latest


def row_html(r):
    name = html.escape(r.get("candidate", "?"))
    is_ip = r.get("candidate") == "ip-incumbent"
    gate = r.get("gate", "")
    score = float(r.get("score") or 0)
    badge = f'<span class="badge {"pass" if gate == "PASS" else "fail"}">{gate}</span>'
    pct = max(0.0, min(1.0, score)) * 100
    return (f'<div class="row{" ip-row" if is_ip else ""}">'
            f'<div class="name"><span>{name}{badge}</span><span>{score:.4g}</span></div>'
            f'<div class="bar"><div class="bar-fill" style="width:{pct:.1f}%"></div></div>'
            f'</div>')


def chart_html(title, mode, rows, meta, style):
    s = STYLES[style]
    return TEMPLATE.format(title=html.escape(title), mode=html.escape(mode),
                           rows="".join(rows), meta=html.escape(meta), **s)


def screenshot(html_path, png_path, height):
    subprocess.run(
        [str(SHELL_BIN), "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         f"--screenshot={png_path}", f"--window-size=980,{height}",
         f"file://{html_path}"],
        check=True, capture_output=True, timeout=120)


def main():
    outdir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "/mnt/c/Users/npwad/OneDrive/Desktop/ip-eval-charts")
    outdir.mkdir(parents=True, exist_ok=True)
    latest = latest_results()
    styles = list(STYLES)
    made = []

    # champions chart: best candidate per stage
    champs = []
    for stage in STAGE_ORDER:
        if stage not in latest:
            continue
        f, n = latest[stage]
        lb = json.loads(f.read_text()).get("leaderboard", [])
        if lb:
            best = max(lb, key=lambda r: r.get("score") or 0)
            champs.append({"candidate": f'{stage}: {best["candidate"]}',
                           "score": best.get("score") or 0, "gate": best.get("gate", "")})
    if champs:
        rows = [row_html(c) for c in sorted(champs, key=lambda c: -c["score"])]
        p = outdir / "00-champions.html"
        p.write_text(chart_html(
            "Champions — best candidate per stage",
            f"ip-eval · {TODAY} · latest run per stage",
            rows, f"{len(champs)} stages", "newspaper"))
        screenshot(p, outdir / "00-champions.png", 140 + 34 * len(rows))
        made.append(outdir / "00-champions.png")

    for i, stage in enumerate(STAGE_ORDER):
        if stage not in latest:
            continue
        f, n = latest[stage]
        d = json.loads(f.read_text())
        lb = sorted(d.get("leaderboard", []), key=lambda r: -(r.get("score") or 0))
        un = len(d.get("candidates_unavailable", []))
        style = styles[i % len(styles)]
        rows = [row_html(r) for r in lb]
        meta = (f"run{n} · {len(lb)} raced · {un} honest-unavailable · "
                f"{d.get('mode', '')[:0]}★ = ip-incumbent")
        p = outdir / f"{i + 1:02d}-{stage}.html"
        p.write_text(chart_html(stage.replace("_", " "), d.get("mode", ""),
                                rows, meta, style))
        screenshot(p, outdir / f"{i + 1:02d}-{stage}.png", 150 + 40 * len(rows))
        made.append(outdir / f"{i + 1:02d}-{stage}.png")
        p.unlink()  # keep the folder PNG-only

    champ_html = outdir / "00-champions.html"
    if champ_html.exists():
        champ_html.unlink()
    print(f"wrote {len(made)} charts to {outdir}")
    for m in made:
        print(" ", m.name)


if __name__ == "__main__":
    main()
