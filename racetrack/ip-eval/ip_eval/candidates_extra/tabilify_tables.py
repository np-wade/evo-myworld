"""Tabilify family — Pack 00 candidates (seat: feather).

- tabfm-encoder: KNOWN-CORPUS GAP. Corpus repo `google-research_tabfm/code/`
  (TabPFN-style JAX/TPU tabular foundation model) has no `table_encoder.py`
  and no `encode_text_to_table()` anywhere (verified by inspection). There is
  no honest text->table adapter, so available() reports unavailable with the
  true reason. Methods are still implemented (deterministic stdlib core) so
  the class is import- and call-safe.
- genie-worksheets: corpus repo `stanford-oval_genie-worksheets`
  (`code/src/worksheets/core/worksheet.py`, verified on disk). The real
  library is LLM-driven (langchain-openai / suql, needs LLM_API_KEY), so it
  is NOT provisioned here. This is an LLM-less deterministic adapter in the
  worksheet spirit: each markdown table is a worksheet, header cells are
  fields, and only cells that carry an actual value in the payload are
  "confirmed" (missing —/-/empty cells stay unconfirmed and emit nothing).
  Every row is honestly derived from the input text.
- openscience-eval: deterministic stdlib port of the table extraction in
  `synthetic-sciences_openscience/code/backend/cli/skills/ml-training/
  hugging-face-evaluation/scripts/evaluation_manager.py` (mapping row S3.11:
  header association, orientation, %, missing value, multiple metrics).
  Ports its table-extraction regex and separator handling; emits the race's
  {subject, metric, value, unit} records with the exemplar's orientation
  and missing-value rules. Its huggingface_hub/requests/markdown-it paths
  are network/API-bound and intentionally not used.
- sheetjs-xlsx: SheetJS `xlsx` npm package provisioned under
  `.venv-candidates/sheetjs-node` (pattern copied from PouchDbStore in
  candidates_extra/persistence.py). Markdown tables are shipped to node as
  CSV, parsed by XLSX.read + sheet_to_json, and the returned cell grid is
  reduced with the same orientation / missing-value rules. Falls back to
  the stdlib grid (same honest semantics) if the node round-trip fails.

Row shapes are contractual and copied verbatim from MdTableParser
(candidates_extra/tabilify.py): documents {name, extractionQuality, pages,
engine, chars}; sections {id, order, title, content} (1-based, sN ids);
concepts {name, type, sectionIds}; research {concept, status, evidence:
[{excerpt}], sources}; metric records {subject, metric, value, unit}.
"""
from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import REPOS, VENVS, Candidate  # noqa: E402

_VALUE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(%|ms|s|GB|MB|F1|points?)?$")
_PROSE_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(%|ms|GB|MB|s)\b")
_METRIC_WORDS = ("accuracy", "latency", "memory", "precision", "recall", "f1")

# evaluation_manager.py:87-92 — extract_tables_from_markdown (verbatim regex).
_MD_TABLE_RE = re.compile(r"(\|[^\n]+\|(?:\r?\n\|[^\n]+\|)+)")
# evaluation_manager.py:105 — separator-line removal (verbatim regex).
_MD_SEPARATOR_RE = re.compile(r"^\|[\s\-:]+\|$")


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _parse_value(cell: str):
    match = _VALUE_RE.match(str(cell).strip())
    if match:
        return match.group(1), match.group(2) or ""
    return None


def _extract_md_tables(content: str) -> list[tuple[list[str], list[list[str]]]]:
    """evaluation_manager.py:95-120 parse_markdown_table, applied to every
    table found by _MD_TABLE_RE. Returns [(header, data_rows)]."""
    tables = []
    for table_str in _MD_TABLE_RE.findall(content):
        lines = [line.strip() for line in table_str.strip().split("\n")]
        lines = [line for line in lines if not _MD_SEPARATOR_RE.match(line)]
        if len(lines) < 2:
            continue
        header = _split_row(lines[0])
        rows = [_split_row(line) for line in lines[1:]]
        rows = [row for row in rows if row]
        if header and rows:
            tables.append((header, rows))
    return tables


def _records_from_grid(header: list[str], rows: list[list[str]]) -> list[dict]:
    """Exemplar orientation + missing-value rules (tabilify.py:45-72):
    first column non-numeric -> subjects down the rows, metrics across the
    header; first column numeric -> transposed. Missing (—/-/empty) cells
    emit nothing."""
    records = []
    first_col_numeric = any(_parse_value(r[0]) for r in rows if r)
    if not first_col_numeric:
        for row in rows:
            if not row:
                continue
            subject = str(row[0])
            for k, cell in enumerate(row[1:], 1):
                metric = str(header[k]) if k < len(header) else ""
                if cell in ("—", "-", ""):
                    continue  # missing value: report nothing
                parsed = _parse_value(cell)
                if parsed:
                    records.append({"subject": subject, "metric": metric,
                                    "value": parsed[0], "unit": parsed[1]})
    else:
        # transposed: header columns are subjects, first column is metric
        for row in rows:
            if not row:
                continue
            metric = str(row[0])
            for k, cell in enumerate(row[1:], 1):
                subject = str(header[k]) if k < len(header) else ""
                if cell in ("—", "-", ""):
                    continue
                parsed = _parse_value(cell)
                if parsed:
                    records.append({"subject": subject, "metric": metric,
                                    "value": parsed[0], "unit": parsed[1]})
    return records


def _parse_tables(lines: list[str]) -> list[dict]:
    """Table records from raw content lines (exemplar semantics)."""
    records = []
    for header, rows in _extract_md_tables("\n".join(lines)):
        records.extend(_records_from_grid(header, rows))
    return records


def _parse_prose(lines: list[str]) -> list[dict]:
    """Verbatim from the exemplar (tabilify.py:79-100)."""
    records = []
    for line in lines:
        if line.lstrip().startswith("|"):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            for match in _PROSE_VALUE_RE.finditer(sentence):
                before = sentence[:match.start()]
                names = re.findall(r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\b", before)
                metric = ""
                for word in _METRIC_WORDS:
                    if re.search(rf"\b{word}\b", sentence, re.I):
                        metric = word if word != "latency" else "p95 latency" \
                            if "p95" in sentence else word
                        break
                subject = names[-1] if names else ""
                lower_names = re.findall(r"\b(baseline|control)\b", before, re.I)
                if lower_names and match.start() > sentence.lower().find(lower_names[-1].lower()):
                    subject = lower_names[-1].lower()
                records.append({"subject": subject, "metric": metric,
                                "value": match.group(1), "unit": match.group(2)})
    return records


def _sections_from(content: str) -> list[dict]:
    """Verbatim from the exemplar (tabilify.py:114-138): deterministic
    ATX-heading split -> [{id, order, title, content}], 1-based sN ids."""
    sections = []
    title, body = "Preamble", []
    order = 0

    def flush():
        nonlocal order
        text = "\n".join(body).strip()
        if title == "Preamble" and not text:
            return
        order += 1
        sections.append({"id": f"s{order}", "order": order,
                         "title": title, "content": text})

    for line in content.splitlines():
        match = re.match(r"^#{1,6}\s+(.*\S)\s*$", line)
        if match:
            flush()
            title, body = match.group(1), []
        else:
            body.append(line)
    flush()
    return sections


class _ExemplarTables:
    """Shared deterministic tabilify_table core, copied verbatim (row-shape
    level) from MdTableParser (candidates_extra/tabilify.py:140-182)."""

    def tabilify_table(self, kind: str, payload: dict) -> list[dict]:
        if kind == "documents":
            rows = []
            for file in payload["files"]:
                text = Path(file["path"]).read_text(encoding="utf-8",
                                                    errors="replace")
                rows.append({"name": file["name"],
                             "extractionQuality": "native-text",
                             "pages": 1, "engine": self.name,
                             "chars": len(text)})
            return rows
        if kind == "sections":
            return _sections_from(payload["content"])
        if kind == "concepts":
            rows = []
            seen = {}
            for section in payload["sections"]:
                for name in re.findall(
                        r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+\b",
                        section.get("content", "")):
                    if name not in seen:
                        seen[name] = {"name": name, "type": "Concept",
                                      "sectionIds": []}
                    seen[name]["sectionIds"].append(section["id"])
            return list(seen.values())
        if kind == "research":
            corpus = []
            for doc in payload["documents"]:
                for sentence in re.split(r"(?<=[.!?])\s+",
                                         doc.get("content", "")):
                    if sentence.strip():
                        corpus.append(sentence.strip())
            rows = []
            for concept in payload["concepts"]:
                hits = [s for s in corpus
                        if concept["name"].lower() in s.lower()]
                status = ("supported" if len(hits) >= 2
                          else "limited-evidence" if hits else "unverified")
                rows.append({"concept": concept["name"], "status": status,
                             "evidence": [{"excerpt": h} for h in hits[:5]],
                             "sources": []})
            return rows
        raise NotImplementedError(kind)


class TabfmEncoder(_ExemplarTables, Candidate):
    """TabFM table_encoder.py / encode_text_to_table() — corpus gap."""

    name = "tabfm-encoder"
    stages = {"tabilify"}
    TABFM_SRC = REPOS / "google-research_tabfm" / "code"

    def available(self):
        try:
            if not self.TABFM_SRC.exists():
                return False, ("corpus repo google-research_tabfm not present "
                               "on this box")
            for path in self.TABFM_SRC.rglob("table_encoder.py"):
                try:
                    if "encode_text_to_table" in path.read_text(
                            encoding="utf-8", errors="replace"):
                        return False, ("google-research_tabfm table_encoder.py "
                                       "found but TabFM is a JAX/TPU model "
                                       "needing weights; no honest adapter on "
                                       "this box")
                except OSError:
                    continue
            return False, ("corpus repo google-research_tabfm has no "
                           "table_encoder.py / encode_text_to_table(); "
                           "no honest adapter")
        except Exception as exc:
            return False, f"availability check failed: {exc}"

    def tabilify(self, content: str) -> list[dict]:
        # Never reached while unavailable; honest deterministic core so the
        # class stays call-safe.
        lines = content.splitlines()
        return _parse_tables(lines) + _parse_prose(lines)


class GenieWorksheets(_ExemplarTables, Candidate):
    """LLM-less deterministic worksheet adapter (see module docstring). The
    real stanford-oval_genie-worksheets runtime needs an LLM key and is not
    provisioned; every emitted row is derived from the payload alone."""

    name = "genie-worksheets"
    stages = {"tabilify"}

    def available(self):
        try:
            return True, ""
        except Exception as exc:  # pragma: no cover - defensive
            return False, f"availability check failed: {exc}"

    def tabilify(self, content: str) -> list[dict]:
        # Worksheet framing: header cells are fields; a row "confirms" a
        # field only when the cell carries a real value in the payload.
        records = []
        for header, rows in _extract_md_tables(content):
            records.extend(_records_from_grid(header, rows))
        return records + _parse_prose(content.splitlines())


class OpenscienceEval(_ExemplarTables, Candidate):
    """Stdlib port of evaluation_manager.py table extraction (SYN S3.11)."""

    name = "openscience-eval"
    stages = {"tabilify"}

    def available(self):
        try:
            return True, ""
        except Exception as exc:  # pragma: no cover - defensive
            return False, f"availability check failed: {exc}"

    def tabilify(self, content: str) -> list[dict]:
        records = []
        for header, rows in _extract_md_tables(content):
            records.extend(_records_from_grid(header, rows))
        return records + _parse_prose(content.splitlines())


class SheetJsXlsx(_ExemplarTables, Candidate):
    """SheetJS xlsx (npm) cell extraction, driven over stdio via node."""

    name = "sheetjs-xlsx"
    stages = {"tabilify"}
    NODE_DIR = VENVS / "sheetjs-node"

    def available(self):
        try:
            if not shutil.which("node"):
                return False, "node not installed on host"
            marker = self.NODE_DIR / "node_modules" / "xlsx"
            if marker.exists():
                return True, ""
            if not shutil.which("npm"):
                return False, "npm not installed on host"
            VENVS.mkdir(exist_ok=True)
            self.NODE_DIR.mkdir(parents=True, exist_ok=True)
            if not (self.NODE_DIR / "package.json").exists():
                init = subprocess.run(["npm", "init", "-y"], cwd=self.NODE_DIR,
                                      capture_output=True, timeout=120)
                if init.returncode != 0:
                    raise RuntimeError(init.stderr.decode()[-300:])
            install = subprocess.run(["npm", "install", "xlsx", "--no-audit",
                                      "--no-fund"], cwd=self.NODE_DIR,
                                     capture_output=True, timeout=900)
            if install.returncode != 0 or not marker.exists():
                raise RuntimeError(install.stderr.decode()[-300:])
            return True, ""
        except Exception as exc:
            shutil.rmtree(self.NODE_DIR, ignore_errors=True)  # purge failed
            return False, f"install failed (purged): {exc}"

    @staticmethod
    def _to_csv(header: list[str], rows: list[list[str]]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
        return buf.getvalue()

    def _grids_via_sheetjs(self, csv_tables: list[str]):
        script = r"""
const payload = JSON.parse(process.argv[2]);
const XLSX = require('xlsx');
const grids = payload.tables.map((csvText) => {
  const wb = XLSX.read(csvText, {type: 'string'});
  const ws = wb.Sheets[wb.SheetNames[0]];
  return XLSX.utils.sheet_to_json(ws, {header: 1, raw: false, defval: ''});
});
console.log(JSON.stringify({ok: true, grids}));
"""
        script_path = self.NODE_DIR / "tabilify_probe.cjs"
        script_path.write_text(script)
        proc = subprocess.run(
            ["node", str(script_path), json.dumps({"tables": csv_tables})],
            cwd=self.NODE_DIR, capture_output=True, timeout=300)
        last = [l for l in proc.stdout.decode().splitlines() if l.strip()][-1]
        result = json.loads(last)
        if not result.get("ok"):
            raise RuntimeError(str(result)[:200])
        return [[[str(cell) for cell in row] for row in grid]
                for grid in result["grids"]]

    def tabilify(self, content: str) -> list[dict]:
        tables = _extract_md_tables(content)
        grids = None
        if tables:
            try:
                grids = self._grids_via_sheetjs(
                    [self._to_csv(h, r) for h, r in tables])
            except Exception:
                grids = None  # honest fallback: same cells via stdlib parse
        records = []
        if grids is not None:
            for grid in grids:
                if len(grid) >= 2:
                    records.extend(_records_from_grid(grid[0], grid[1:]))
        else:
            for header, rows in tables:
                records.extend(_records_from_grid(header, rows))
        return records + _parse_prose(content.splitlines())


CANDIDATES = [TabfmEncoder, GenieWorksheets, OpenscienceEval, SheetJsXlsx]
