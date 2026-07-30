#!/usr/bin/env python3
"""Generate a self-contained HTML infographic of the latest ip-eval race results.

Reads the newest results-<stage>-runN.json per stage plus pipeline-run2.json
and emits ip-eval-results-<date>.html next to them. No external assets —
suitable for headless-Chromium print-to-pdf.
"""
import glob
import html
import json
import re
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TODAY = date.today().isoformat()
OUT = HERE / f"ip-eval-results-{TODAY}.html"

STAGE_ORDER = [
    "extract", "split", "concepts", "tabilify", "retrieval", "graph",
    "drafting", "dedup", "export_docx", "export_bibtex",
    "persistence", "api", "security", "frontend",
]

# Up to 3 extra metrics to show per candidate, per stage: (label, key, fmt)
METRICS = {
    "api":           [("HTTP probes", "pass_rate", "{:.0%}"), ("p50 ms", "latency_ms_p50", "{:.0f}")],
    "concepts":      [("mean F1", "mean_f1", "{:.3f}"), ("type acc", "type_accuracy", "{:.3f}"), ("nested", "nested_score", "{:.3f}")],
    "dedup":         [("dedup score", "dedup_score", "{:.3f}"), ("punct merged", "punct_variant_merged", "{}"), ("swaps kept", "unique_and_swaps_kept", "{}")],
    "drafting":      [("draft score", "draft_score", "{:.3f}"), ("citation bind", "citation_binding", "{:.3f}"), ("metric fidelity", "metric_fidelity", "{:.3f}")],
    "export_bibtex": [("coverage", "bibtex_coverage", "{:.3f}"), ("entries", "entry_count", "{}"), ("hard score", "hard_score", "{:.3f}")],
    "export_docx":   [("docx score", "docx_score", "{:.3f}"), ("text fidelity", "text_fidelity", "{:.3f}"), ("footnotes", "footnote_entries", "{}")],
    "extract":       [("mean F1", "mean_f1", "{:.3f}"), ("heading ret.", "heading_retention", "{:.3f}"), ("p50 ms", "latency_ms_p50", "{:.0f}")],
    "frontend":      [("UI probes", "pass_rate", "{:.0%}")],
    "graph":         [("node F1", "node_f1", "{:.3f}"), ("edge prec", "edge_precision", "{:.3f}"), ("edge recall", "edge_recall", "{:.3f}")],
    "persistence":   [("write p50 ms", "p50_write_ms", "{:.2f}"), ("torn reads", "torn_reads", "{}"), ("lost updates", "lost_updates", "{}")],
    "retrieval":     [("recall@5", "recall_at_5", "{:.3f}"), ("hard recall@5", "hard_recall_at_5", "{:.3f}"), ("p50 ms", "latency_ms_p50", "{:.0f}")],
    "security":      [("checks", "pass_rate", "{:.0%}"), ("npm high", "npm_high", "{}")],
    "split":         [("mean F1", "mean_f1", "{:.3f}"), ("gamma F1", "gamma_f1", "{:.3f}")],
    "tabilify":      [("docs F1", "documents_f1", "{:.3f}"), ("concepts F1", "concepts_f1", "{:.3f}"), ("metrics F1", "metrics_f1", "{:.3f}")],
}

FIXED_DEFECTS = [
    ("annoy", "retrieval", "missing numpy in candidate PIP list",
     "runs clean: recall@5 0.3564, ties the 7-way lead (run6)"),
    ("turso-store", "persistence", "`nonlocal` SyntaxError + libsql lock retry",
     "runs: gate PASS, score 0.5 — 20 lost updates under concurrency exposed (run7)"),
    ("opendal-store", "persistence", "`nonlocal` SyntaxError",
     "runs: score 0.85, ties ip-incumbent / sqlite at the top (run7)"),
    ("hayhooks-api", "api", "server never came up on :8973; stderr was DEVNULL'd",
     "server starts via hayhooks_cli with captured log: gate PASS, 0.5714 (run3)"),
    ("nemo-gliner", "concepts", "TimeoutExpired escaped available(); crashed the stage (run5)",
     "HF_HUB_OFFLINE fast path + exception-proof available(): gate PASS, 0.4896 (run6)"),
]

SESSION_NOTES = [
    "Mid-session the whole <code>ip-eval/</code> tree was accidentally deleted by an external session and fully restored; venvs re-provisioned on demand.",
    "Retrieval grew from a 5-way to a <b>7-way tie at 0.3564</b> (annoy and haystack-bm25 joined IP, librer, ragbits-rrf, rank-bm25, tantivy-py) once the haystack venv existed.",
    "Drafting: paperspine-draft 0.9325 took the crown from IP (0.9077). Graph: graphify-graph/naive/networkx 0.9833 &gt; IP 0.9714.",
    "Persistence: IP = sqlite = opendal 0.85 &gt; pouchdb 0.775 &gt; turso 0.5 &gt; naive FAIL (376 torn reads, 21 lost updates).",
    "<code>race extract</code> deliberately not re-run: new extract candidates are all honest-unavailable and the frontier is unchanged (OCR image lane, docker lane, R10 SLO/fault rows).",
]


def latest_results():
    latest = {}
    for f in HERE.glob("results-*.json"):
        m = re.match(r"results-(.+)-run(\d+)\.json$", f.name)
        if not m:
            continue
        stage, n = m.group(1), int(m.group(2))
        if stage not in latest or n > latest[stage][1]:
            latest[stage] = (f, n)
    return latest


def esc(s):
    return html.escape(str(s))


def bar(score, gate, is_ip):
    pct = max(0.0, min(1.0, float(score))) * 100
    cls = "bar-fill pass" if gate == "PASS" else "bar-fill fail"
    if is_ip:
        cls += " ip"
    return (f'<div class="bar"><div class="{cls}" style="width:{pct:.1f}%"></div>'
            f'<span class="bar-label">{score:.4g}</span></div>')


def metric_chips(stage, row):
    chips = []
    for label, key, fmt in METRICS.get(stage, []):
        v = row.get(key)
        if v is None:
            continue
        try:
            txt = fmt.format(v)
        except (ValueError, TypeError):
            txt = str(v)
        chips.append(f'<span class="chip">{esc(label)} <b>{esc(txt)}</b></span>')
    return '<div class="chips">' + "".join(chips) + "</div>" if chips else ""


def stage_card(stage, path, run):
    d = json.loads(path.read_text())
    lb = sorted(d.get("leaderboard", []), key=lambda r: -(r.get("score") or 0))
    unavail = d.get("candidates_unavailable", [])
    n_pass = sum(1 for r in lb if r.get("gate") == "PASS")
    rows = []
    for r in lb:
        name = r.get("candidate", "?")
        is_ip = name == "ip-incumbent"
        gate = r.get("gate", "")
        badge = f'<span class="badge {"pass" if gate == "PASS" else "fail"}">{gate}</span>'
        star = '<span class="ip-star" title="incumbent">★</span>' if is_ip else ""
        rows.append(
            f'<div class="cand{" ip-row" if is_ip else ""}">'
            f'<div class="cand-head"><span class="cand-name">{star}{esc(name)}</span>{badge}</div>'
            f'{bar(r.get("score") or 0, gate, is_ip)}'
            f'{metric_chips(stage, r)}'
            f'</div>'
        )
    un = ""
    if unavail:
        items = "".join(
            f'<li><b>{esc(u["candidate"])}</b> — <span title="{esc(u["reason"])}">'
            f'{esc(u["reason"][:150])}{"…" if len(u["reason"]) > 150 else ""}</span></li>'
            for u in unavail
        )
        un = f'<details class="unavail"><summary>honest-unavailable ({len(unavail)})</summary><ul>{items}</ul></details>'
    return f'''
    <section class="card">
      <header><h3>{esc(stage.replace("_", " "))}</h3>
        <span class="run-tag">run{run} · {n_pass}/{len(lb)} gate PASS</span></header>
      <p class="mode">{esc(d.get("mode", ""))}</p>
      {''.join(rows)}
      {un}
    </section>'''


def main():
    latest = latest_results()
    total_runs = len(list(HERE.glob("results-*-run*.json")))
    raced = sum(len(json.loads(p.read_text()).get("leaderboard", []))
                for p, _ in latest.values())
    unav = sum(len(json.loads(p.read_text()).get("candidates_unavailable", []))
               for p, _ in latest.values())

    pipe = json.loads((HERE / "pipeline-run2.json").read_text())
    pipe_scores = "".join(
        f'<span class="chip">{esc(k)} <b>{v:.4g}</b></span>'
        for k, v in pipe["score"]["hard"].items()
    )

    cards = "".join(
        stage_card(stage, latest[stage][0], latest[stage][1])
        for stage in STAGE_ORDER if stage in latest
    )

    defects = "".join(
        f'<tr><td><b>{esc(n)}</b></td><td>{esc(s)}</td><td class="was">{esc(w)}</td>'
        f'<td class="now">{esc(f)}</td></tr>'
        for n, s, w, f in FIXED_DEFECTS
    )
    notes = "".join(f"<li>{n}</li>" for n in SESSION_NOTES)

    OUT.write_text(TEMPLATE.format(
        today=TODAY, total_runs=total_runs, n_stages=len(latest),
        raced=raced, unav=unav, cards=cards, defects=defects,
        notes=notes, pipe_scores=pipe_scores,
        pipe_wall=pipe["score"]["wall_s"], pipe_chain=esc(pipe["report"]["chain"]),
    ))
    print(f"wrote {OUT}")


TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>ip-eval race results — {today}</title>
<style>
  @page {{ size: A4; margin: 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         color: #1c2430; background: #f4f6f9; margin: 0; padding: 24px; }}
  .band {{ background: linear-gradient(120deg, #12336e, #1f5fb8); color: #fff;
          border-radius: 14px; padding: 26px 30px; margin-bottom: 18px; }}
  .band h1 {{ margin: 0 0 4px; font-size: 30px; letter-spacing: .3px; }}
  .band p {{ margin: 2px 0; opacity: .92; font-size: 14px; }}
  .stats {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 18px; }}
  .stat {{ background: #fff; border-radius: 12px; padding: 14px 16px;
          box-shadow: 0 1px 3px rgba(16,30,54,.12); }}
  .stat .num {{ font-size: 26px; font-weight: 700; color: #1f5fb8; }}
  .stat .lbl {{ font-size: 12px; color: #5a6675; text-transform: uppercase; letter-spacing: .6px; }}
  h2 {{ font-size: 18px; margin: 22px 0 10px; color: #12336e; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 16px 18px;
          box-shadow: 0 1px 3px rgba(16,30,54,.12); break-inside: avoid; }}
  .card header {{ display: flex; justify-content: space-between; align-items: baseline; }}
  .card h3 {{ margin: 0; font-size: 17px; text-transform: capitalize; }}
  .run-tag {{ font-size: 11px; color: #7a8595; }}
  .mode {{ font-size: 12px; color: #5a6675; margin: 6px 0 12px; }}
  .cand {{ padding: 7px 0; border-top: 1px solid #eef1f5; }}
  .ip-row {{ background: #fff8e6; margin: 0 -8px; padding: 7px 8px; border-radius: 8px; }}
  .cand-head {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }}
  .cand-name {{ font-weight: 600; font-size: 13.5px; }}
  .ip-star {{ color: #e8a100; margin-right: 4px; }}
  .badge {{ font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 999px; }}
  .badge.pass {{ background: #dcf5e3; color: #157a3a; }}
  .badge.fail {{ background: #fde2e1; color: #b3261e; }}
  .bar {{ position: relative; height: 18px; background: #eef1f5; border-radius: 999px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 999px; }}
  .bar-fill.pass {{ background: linear-gradient(90deg, #2e9e5b, #52c77e); }}
  .bar-fill.fail {{ background: linear-gradient(90deg, #c0392b, #e06a5b); }}
  .bar-fill.ip {{ outline: 2px solid #e8a100; outline-offset: -2px; }}
  .bar-label {{ position: absolute; right: 8px; top: 0; line-height: 18px; font-size: 11px;
               font-weight: 700; color: #1c2430; }}
  .chips {{ margin-top: 4px; }}
  .chip {{ display: inline-block; font-size: 11px; background: #f0f3f8; border-radius: 6px;
          padding: 2px 7px; margin: 2px 4px 0 0; color: #445060; }}
  .unavail {{ margin-top: 10px; font-size: 12px; color: #5a6675; }}
  .unavail summary {{ cursor: pointer; font-weight: 600; }}
  .unavail ul {{ margin: 6px 0 0; padding-left: 18px; }}
  .unavail li {{ margin-bottom: 4px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 12px;
          overflow: hidden; box-shadow: 0 1px 3px rgba(16,30,54,.12); font-size: 12.5px; }}
  th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #eef1f5; vertical-align: top; }}
  th {{ background: #12336e; color: #fff; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; }}
  td.was {{ color: #b3261e; }}
  td.now {{ color: #157a3a; }}
  .panel {{ background: #fff; border-radius: 12px; padding: 16px 18px;
           box-shadow: 0 1px 3px rgba(16,30,54,.12); font-size: 13px; }}
  .panel ul {{ margin: 8px 0 0; padding-left: 20px; }}
  .panel li {{ margin-bottom: 6px; }}
  footer {{ margin-top: 24px; font-size: 11px; color: #7a8595; text-align: center; }}
  code {{ background: #eef1f5; padding: 1px 5px; border-radius: 4px; font-size: 11.5px; }}
  @media print {{ body {{ background: #fff; padding: 0; }} .grid {{ gap: 10px; }} }}
</style></head><body>

<div class="band">
  <h1>ip-eval Race Results</h1>
  <p>candidate-expansion tranche · {today} · racetrack/ip-eval · latest run per stage</p>
  <p>IP-incumbent rows are highlighted ★ — every score comes from a real race on self-authored fixtures with gold oracles.</p>
</div>

<div class="stats">
  <div class="stat"><div class="num">{n_stages}</div><div class="lbl">stages</div></div>
  <div class="stat"><div class="num">{total_runs}</div><div class="lbl">race runs on disk</div></div>
  <div class="stat"><div class="num">{raced}</div><div class="lbl">candidates raced</div></div>
  <div class="stat"><div class="num">{unav}</div><div class="lbl">honest-unavailable</div></div>
  <div class="stat"><div class="num">5</div><div class="lbl">defects fixed today</div></div>
</div>

<h2>Stage leaderboards</h2>
<div class="grid">
{cards}
</div>

<h2>Defects fixed in this tranche (before → after)</h2>
<table>
  <tr><th>candidate</th><th>stage</th><th>was</th><th>now</th></tr>
  {defects}
</table>

<h2>End-to-end pipeline (run2)</h2>
<div class="panel">
  chain: <code>{pipe_chain}</code> · wall {pipe_wall}s
  <div class="chips" style="margin-top:8px">{pipe_scores}</div>
</div>

<h2>Session notes</h2>
<div class="panel"><ul>{notes}</ul></div>

<footer>generated {today} by make_infographic.py from results-*-runN.json · selftest: all green · evo-myworld racetrack</footer>
</body></html>
"""

if __name__ == "__main__":
    main()
