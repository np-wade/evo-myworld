"""End-to-end pipeline — the seed task, run STATEFULLY like a real watcher:

  RUN 1 (baseline): snapshot every watched page (v1), normalize, persist the
         baseline store to out/<set>/state/ (html + sha256 manifest).
  RUN 2 (watch):    load the stored baseline, diff the current pages (v2)
         against it with the race-winning combo, classify real-vs-churn,
         report what's new / gone / moved / changed.

Output: out/<set>/report.json, report.md (change table + before/after
snippets), changes.json (the full detection manifest incl. suppressed churn),
state/ (the baseline store). Then scores the run against the injection
manifest: detection P/R/F1, false-alarm rate, localization, latency (hard
track) and change-summary readability (advisory track). 100% offline.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from .classify import classify
from .differs import ALL_DIFFERS
from .oracle import FIXTURES, Oracle
from .race import page_files
from .snapshot import ALL_NORMALIZERS

DEFAULT_DIFFER = "dom-diff"     # stage-race winner (see results-diff-run1.json)
DEFAULT_NORM = "strip"


def _snip(s: str, n: int = 80) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def run_pipeline(set_key: str = "set1", differ: str = DEFAULT_DIFFER,
                 norm: str = DEFAULT_NORM, outdir: str = "") -> dict:
    t_start = time.perf_counter()
    root = FIXTURES / set_key
    out = Path(outdir) if outdir else Path(__file__).parent.parent / "out" / set_key
    state = out / "state"
    state.mkdir(parents=True, exist_ok=True)

    diffs = {d.key: d for d in ALL_DIFFERS if d.available()}
    norms = {n.key: n for n in ALL_NORMALIZERS if n.available()}
    de = diffs.get(differ) or next(iter(diffs.values()))
    no = norms.get(norm) or next(iter(norms.values()))

    pages = page_files(set_key)

    # RUN 1 — baseline snapshot (statefulness: this is what run 2 reads back)
    baseline_manifest = {}
    for page in pages:
        html = no.normalize((root / "v1" / f"{page}.html").read_text())
        (state / f"{page}.html").write_text(html)
        baseline_manifest[page] = hashlib.sha256(html.encode()).hexdigest()
    (state / "baseline.json").write_text(json.dumps(
        {"set": set_key, "normalizer": no.key, "sha256": baseline_manifest},
        indent=2))

    # RUN 2 — watch: diff current pages against the STORED baseline
    dets, lat, page_errors = [], [], []
    for page in pages:
        base = (state / f"{page}.html").read_text()
        cur = no.normalize((root / "v2" / f"{page}.html").read_text())
        t0 = time.perf_counter()
        try:
            d = de.diff(page, base, cur)
            classify(d)
        except Exception as e:  # one weird page must not kill the watch run
            page_errors.append(f"{page}: {type(e).__name__}: {e}")
            lat.append((time.perf_counter() - t0) * 1000)
            continue
        lat.append((time.perf_counter() - t0) * 1000)
        dets.extend(d)

    reported = [d for d in dets if d.label == "real"]
    suppressed = [d for d in dets if d.label == "churn"]

    report = {
        "prompt": f"Watch these {len(pages)} pages; each run, report what "
                  f"changed since last run — what's new, gone, moved.",
        "set": set_key, "differ": de.key, "normalizer": no.key,
        "pages_watched": len(pages),
        "pages_changed": sorted({d.page for d in reported}),
        "changes": [asdict(d) for d in reported],
        "suppressed_churn": [asdict(d) for d in suppressed],
        "page_errors": page_errors,
        "p50_ms_per_page": round(statistics.median(lat), 2) if lat else 0.0,
        "wall_s": round(time.perf_counter() - t_start, 2),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    (out / "changes.json").write_text(json.dumps(
        {"set": set_key, "detections": [asdict(d) for d in dets]}, indent=2))

    md = [f"# Watchdog report — {set_key}", "",
          f"Watching {len(pages)} pages ({de.key}/{no.key}). "
          f"**{len(reported)} real changes** on "
          f"{len(report['pages_changed'])} pages; "
          f"{len(suppressed)} cosmetic diffs suppressed as churn.", "",
          "| page | what | element | before | after |", "|---|---|---|---|---|"]
    for d in reported:
        md.append(f"| {d.page} | {d.change_type} | {d.element_id or '-'} | "
                  f"{_snip(d.before)} | {_snip(d.after)} |")
    md += ["", "## Suppressed churn (not real changes)", ""]
    for d in suppressed:
        md.append(f"- {d.page}: {d.change_type} {d.element_id or '(no id)'} — "
                  f"{_snip(d.before, 60)} -> {_snip(d.after, 60)}")
    (out / "report.md").write_text("\n".join(md) + "\n")

    return {"report": report, "outdir": str(out)}


def score_pipeline(res: dict, set_key: str = "set1") -> dict:
    """Hard-score detection vs the injection manifest; advisory-score the
    readability of the change summary."""
    oracle = Oracle(set_key)
    report = res["report"]
    dets = report["changes"] + report["suppressed_churn"]
    sc = oracle.score_detections(dets)

    hard = {
        "f1": sc.f1, "recall": sc.recall, "precision": sc.precision,
        "false_alarm_rate": sc.false_alarm_rate,
        "localization": sc.localization,
        "real_hit": f"{sc.real_hit}/{sc.real_total}",
        "churn_flagged": f"{sc.churn_flagged}/{sc.churn_total}",
        "churn_suppressed": sc.n_suppressed,
        "missed": sc.missed, "false_alarms": sc.flagged,
        "pages": report["pages_watched"],
        "p50_ms_per_page": report["p50_ms_per_page"],
        "wall_s": report["wall_s"],
    }
    rows = report["changes"]
    with_snip = sum(1 for d in rows if (d["before"] or d["after"]))
    snips = [len(d["before"]) + len(d["after"]) for d in rows]
    advisory = {  # readability of the report — advisory ONLY, never ranked
        "reported_rows": len(rows),
        "snippet_coverage": round(with_snip / len(rows), 4) if rows else 0.0,
        "avg_snippet_chars": round(statistics.mean(snips), 1) if snips else 0,
        "note": "advisory only — human-facing summary quality, not optimized",
    }
    return {"hard": hard, "advisory": advisory}
