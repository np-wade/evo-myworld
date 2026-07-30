"""Tabilify family — Stage 3b reference candidate.

- md-table-parser: stdlib markdown table parser (standard + transposed
  orientation, missing-value cells) plus prose metric extraction with
  metric-name detection. This is the honest reference for what a
  table-aware tabilifier produces; it exists so the incumbent's gap is
  measured against a real implementation, not imagination.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate  # noqa: E402

_VALUE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(%|ms|s|GB|MB|F1|points?)?$")
_PROSE_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(%|ms|GB|MB|s)\b")
_METRIC_WORDS = ("accuracy", "latency", "memory", "precision", "recall", "f1")


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _parse_value(cell: str):
    match = _VALUE_RE.match(cell.strip())
    if match:
        return match.group(1), match.group(2) or ""
    return None


def _parse_tables(lines: list[str]) -> list[dict]:
    records = []
    i = 0
    while i < len(lines) - 1:
        if lines[i].lstrip().startswith("|") and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            header = _split_row(lines[i])
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(_split_row(lines[j]))
                j += 1
            first_col_numeric = any(_parse_value(r[0]) for r in rows if r)
            if not first_col_numeric:
                for row in rows:
                    if not row:
                        continue
                    subject = row[0]
                    for k, cell in enumerate(row[1:], 1):
                        metric = header[k] if k < len(header) else ""
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
                    metric = row[0]
                    for k, cell in enumerate(row[1:], 1):
                        subject = header[k] if k < len(header) else ""
                        if cell in ("—", "-", ""):
                            continue
                        parsed = _parse_value(cell)
                        if parsed:
                            records.append({"subject": subject, "metric": metric,
                                            "value": parsed[0], "unit": parsed[1]})
            i = j
        else:
            i += 1
    return records


def _parse_prose(lines: list[str]) -> list[dict]:
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


class MdTableParser(Candidate):
    name = "md-table-parser"
    stages = {"tabilify"}

    def available(self):
        return True, ""

    def tabilify(self, content: str) -> list[dict]:
        lines = content.splitlines()
        return _parse_tables(lines) + _parse_prose(lines)

    @staticmethod
    def _sections_from(content: str) -> list[dict]:
        """Deterministic ATX-heading split: [{id, order, title, content}]."""
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

    def tabilify_table(self, kind: str, payload: dict) -> list[dict]:
        if kind == "documents":
            rows = []
            for file in payload["files"]:
                text = Path(file["path"]).read_text(encoding="utf-8",
                                                    errors="replace")
                rows.append({"name": file["name"],
                             "extractionQuality": "native-text",
                             "pages": 1, "engine": "md-table-parser",
                             "chars": len(text)})
            return rows
        if kind == "sections":
            return self._sections_from(payload["content"])
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


CANDIDATES = [MdTableParser]
