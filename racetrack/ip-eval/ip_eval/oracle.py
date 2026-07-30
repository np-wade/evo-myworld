"""Oracle — hard scoring against grader-owned gold. Pure stdlib.

No LLM judgment anywhere in this module. Every score is a deterministic
function of (candidate output, gold).
"""
from __future__ import annotations

import io
import json
import re
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path

from .fixtures import GOLD_PATH, normalize_text


def load_gold() -> dict:
    return json.loads(GOLD_PATH.read_text())


# ---------------------------------------------------------------------------
# text similarity primitives
# ---------------------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w][\w'’-]*", normalize_text(text).lower())


def token_prf(pred_text: str, gold_text: str) -> dict:
    """Bag-of-token precision/recall/F1 between two texts."""
    pred, gold = _tokens(pred_text), _tokens(gold_text)
    if not pred and not gold:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not pred or not gold:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    from collections import Counter
    p_counts, g_counts = Counter(pred), Counter(gold)
    overlap = sum((p_counts & g_counts).values())
    precision = overlap / len(pred)
    recall = overlap / len(gold)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def _norm_key(value: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(value).lower()).strip()


# ---------------------------------------------------------------------------
# stage 1 — extraction
# ---------------------------------------------------------------------------

def score_extraction(candidate_text: str, canonical_text: str) -> dict:
    """Token F1 of extracted text vs canonical, plus heading retention."""
    sim = token_prf(candidate_text, canonical_text)
    gold_headings = re.findall(r"^#{1,6}\s+(.+)$", canonical_text, flags=re.M)
    cand_norm = _norm_key(candidate_text)
    retained = sum(1 for h in gold_headings if _norm_key(h) in cand_norm)
    sim["heading_retention"] = round(retained / max(1, len(gold_headings)), 4)
    return sim


def score_adversarial(case: str, output: dict, gold_case: dict) -> dict:
    """Gate-style checks for the adversarial pack. output = {ok, text, error}."""
    expect = gold_case["expect"]
    text = output.get("text") or ""
    if expect == "graceful-empty":
        return {"pass": output.get("ok", False) or bool(output.get("error")),
                "detail": "no crash on zero-byte input"}
    if expect == "graceful-failure":
        return {"pass": not output.get("ok", False) or len(text) < 80,
                "detail": "corrupt pdf rejected or flagged, no fabricated text"}
    if expect == "content-sniffing":
        sim = token_prf(text, gold_case["canonical_text"])
        return {"pass": sim["f1"] >= 0.6, "f1": sim["f1"],
                "detail": "html content recovered despite .txt name"}
    if expect == "normalized-equivalence":
        sim = token_prf(normalize_text(text), gold_case["canonical_text"])
        return {"pass": sim["f1"] >= 0.9, "f1": sim["f1"],
                "detail": "unicode normalizes to canonical form"}
    if expect == "furniture-removed-footnote-kept":
        norm = normalize_text(text)
        kept = all(s in norm for s in gold_case.get("must_contain", []))
        header_count = norm.count(gold_case["must_not_repeat"][0]) if gold_case.get("must_not_repeat") else 0
        body_hits = sum(1 for s in gold_case.get("body_sentences", []) if s in norm)
        return {"pass": kept and header_count <= 1 and body_hits >= 2,
                "footnote_kept": kept, "furniture_repetitions": header_count,
                "body_sentences_found": body_hits}
    if expect == "merge-required-and-forbidden":
        norm = normalize_text(text)
        kept_ok = all(k in norm for k in gold_case["must_keep"])
        merged_ok = all(m not in norm for m in gold_case["must_merge_away"])
        dup = gold_case["must_keep"][2]
        dup_count = norm.count(dup)
        checks = {
            "unique_and_swaps_kept": kept_ok,
            "punct_variant_merged": merged_ok,
            "no_double_survivor": dup_count <= 1,
        }
        score = sum(checks.values()) / len(checks)
        return {"pass": all(checks.values()), "score": round(score, 4), **checks}
    if expect == "exact-duplicates-removed-unique-kept":
        norm = normalize_text(text)
        unique_kept = all(u in norm for u in gold_case["unique_paragraphs"])
        dup = gold_case["unique_paragraphs"][-1]
        dup_count = norm.count(dup)
        return {"pass": unique_kept and dup_count <= 1,
                "unique_kept": unique_kept, "duplicate_survivors": dup_count}
    return {"pass": False, "detail": f"unknown expectation {expect}"}


# ---------------------------------------------------------------------------
# stage 2 — splitting
# ---------------------------------------------------------------------------

def score_split(pred_headings: list[str], gold_headings: list[str]) -> dict:
    """Boundary P/R/F1 over normalized heading strings (set-based)."""
    pred = {_norm_key(h) for h in pred_headings if h and _norm_key(h) != "introduction & overview"}
    gold = {_norm_key(h) for h in gold_headings}
    gold.discard("")
    if not pred and not gold:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not pred or not gold:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    tp = len(pred & gold)
    precision = tp / len(pred)
    recall = tp / len(gold)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


# ---------------------------------------------------------------------------
# stage 3 — concepts / ontology / metrics
# ---------------------------------------------------------------------------

def score_concepts(pred_concepts: list[dict], gold_concepts: list[dict]) -> dict:
    """Exact normalized-name match; type accuracy over matched; nested handling."""
    pred_by_key = {_norm_key(c.get("name", "")): c for c in pred_concepts}
    gold_by_key = {_norm_key(c["name"]): c for c in gold_concepts}
    tp_keys = set(pred_by_key) & set(gold_by_key)
    precision = len(tp_keys) / max(1, len(pred_by_key))
    recall = len(tp_keys) / max(1, len(gold_by_key))
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    type_hits = sum(
        1 for k in tp_keys
        if _norm_key(str(pred_by_key[k].get("type", ""))) == _norm_key(gold_by_key[k]["type"])
    )
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "type_accuracy": round(type_hits / max(1, len(tp_keys)), 4),
        "matched": sorted(tp_keys),
    }


def score_nested_suppression(pred_concepts: list[dict], nested_pairs: list[list[str]]) -> dict:
    """For each (short, long) gold pair: long present, short suppressed or related."""
    pred_keys = {_norm_key(c.get("name", "")) for c in pred_concepts}
    wins = 0
    for short, long_ in nested_pairs:
        if _norm_key(long_) in pred_keys and _norm_key(short) not in pred_keys:
            wins += 1
    return {"nested_score": round(wins / max(1, len(nested_pairs)), 4)}


def score_metrics(pred_metrics: list[str], gold_metrics: list[str]) -> dict:
    pred_text = " ".join(pred_metrics)
    hits = sum(1 for m in gold_metrics if m in pred_text)
    return {"metric_capture": round(hits / max(1, len(gold_metrics)), 4)}


# ---------------------------------------------------------------------------
# stage 3b — tabilification (structured metric records from prose + tables)
# ---------------------------------------------------------------------------

def _row_f1(pred_rows: list[dict], gold_rows: list[dict], keys: list[str]) -> float:
    """Set-based F1 over rows projected to the given keys."""
    def proj(row):
        return tuple(_norm_key(str(row.get(k, ""))) for k in keys)
    pred = {proj(r) for r in pred_rows}
    gold = {proj(r) for r in gold_rows}
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    tp = len(pred & gold)
    p, r = tp / len(pred), tp / len(gold)
    return round(2 * p * r / (p + r), 4) if p + r else 0.0


def score_tabilify_tables(tables: dict[str, list[dict]], gold: dict) -> dict:
    """Four table kinds + slicing. tables keys: documents, sections, concepts,
    research, metrics."""
    out: dict[str, float] = {}

    # documents: name + extraction quality per ingested file
    doc_gold = []
    for key, doc in gold["documents"].items():
        doc_gold.append({"name": f"{key}.md", "extractionQuality": "native-text"})
    out["documents_f1"] = _row_f1(
        tables.get("documents", []), doc_gold, ["name", "extractionQuality"])

    # sections: ordered headings per document (alpha only, deterministic)
    alpha = gold["documents"]["alpha"]
    sec_gold = [{"order": i + 1, "title": s["heading"]}
                for i, s in enumerate(alpha["sections"])]
    out["sections_f1"] = _row_f1(
        tables.get("sections", []), sec_gold, ["order", "title"])

    # concepts: name + type + document
    con_gold = [{"name": c["name"], "type": c["type"]} for c in alpha["concepts"]]
    out["concepts_f1"] = _row_f1(
        tables.get("concepts", []), con_gold, ["name", "type"])

    # research: status per concept from the grader's containment rule
    corpus = []
    for section in alpha["sections"]:
        for paragraph in section["paragraphs"]:
            corpus.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+", paragraph)
                          if s.strip())
    res_gold = []
    for concept in alpha["concepts"]:
        hits = [s for s in corpus if concept["name"].lower() in s.lower()]
        status = ("supported" if len(hits) >= 2
                  else "limited-evidence" if len(hits) == 1 else "unverified")
        res_gold.append({"concept": concept["name"], "status": status})
    out["research_f1"] = _row_f1(
        tables.get("research", []), res_gold, ["concept", "status"])
    out["research_statuses"] = res_gold  # used by the linking checks

    # metrics: full structured records (existing scorer)
    out["metrics"] = score_tabilify(tables.get("metrics", []), gold["tabilify"])
    return out


def score_linking(tables: dict[str, list[dict]]) -> dict:
    """Referential integrity INSIDE a candidate's own output: concepts must
    point at real sections, research rows at real concepts, metric subjects at
    real concepts (soft)."""
    section_ids = {str(s.get("id")) for s in tables.get("sections", [])}
    concept_names = {_norm_key(c.get("name", "")) for c in tables.get("concepts", [])}
    checks = []
    for concept in tables.get("concepts", []):
        for sid in concept.get("sectionIds", []):
            checks.append(str(sid) in section_ids)
    for row in tables.get("research", []):
        name = _norm_key(str(row.get("concept", row.get("conceptName", ""))))
        checks.append(name in concept_names)
    excerpts_ok = 0
    excerpts_total = 0
    source = " ".join(str(s.get("content", "")) for s in tables.get("sections", []))
    source_norm = _norm_key(source)
    for row in tables.get("research", []):
        for evidence in row.get("evidence", []):
            excerpts_total += 1
            excerpt = evidence.get("excerpt", "") if isinstance(evidence, dict) else str(evidence)
            excerpts_ok += int(_norm_key(excerpt)[:60] in source_norm)
    link_score = (sum(checks) / len(checks)) if checks else 0.0
    return {
        "link_integrity": round(link_score, 4),
        "excerpt_verbatim": round(excerpts_ok / excerpts_total, 4)
        if excerpts_total else -1.0,
    }

def _record_credit(pred: dict, gold_rec: dict) -> float:
    p_subj, p_metric = _norm_key(str(pred.get("subject", ""))), _norm_key(str(pred.get("metric", "")))
    p_value = re.sub(r"\s", "", str(pred.get("value", "")))
    p_unit = str(pred.get("unit", "")).strip()
    g_subj, g_metric = _norm_key(gold_rec["subject"]), _norm_key(gold_rec["metric"])
    if p_value != re.sub(r"\s", "", gold_rec["value"]) or p_unit != gold_rec["unit"]:
        return 0.0
    if p_subj == g_subj and p_metric == g_metric:
        return 1.0
    if p_subj == g_subj:
        return 0.7
    return 0.4  # right number+unit, wrong attribution


def score_tabilify(pred_records: list[dict], gold_spec: dict) -> dict:
    gold_records = gold_spec["records"]
    credits = []
    for gold_rec in gold_records:
        credits.append(max((_record_credit(p, gold_rec) for p in pred_records),
                           default=0.0))
    recall = sum(credits) / max(1, len(gold_records))
    full_hits = sum(
        1 for p in pred_records
        if any(_record_credit(p, g) == 1.0 for g in gold_records)
    )
    precision = full_hits / max(1, len(pred_records))
    fabrications = []
    for ban in gold_spec.get("must_not_report", []):
        for p in pred_records:
            if _norm_key(str(p.get("subject", ""))) == _norm_key(ban["subject"]) \
                    and _norm_key(ban["metric"]) in _norm_key(str(p.get("metric", ""))):
                fabrications.append(p)
    return {
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4)
        if precision + recall else 0.0,
        "fabrications": len(fabrications),
        "n_pred": len(pred_records),
    }


# ---------------------------------------------------------------------------
# stage 4 — retrieval
# ---------------------------------------------------------------------------

def score_retrieval(ranked: list[str], gold_hits: list[str], ks=(1, 5)) -> dict:
    gold_set = {_norm_key(s) for s in gold_hits}
    out = {}
    for k in ks:
        top = {_norm_key(s) for s in ranked[:k]}
        out[f"recall@{k}"] = round(len(top & gold_set) / max(1, len(gold_set)), 4)
    return out


# ---------------------------------------------------------------------------
# stage 7 — dedup / assembly
# ---------------------------------------------------------------------------

def score_dedup_output(output_text: str, gold_case: dict) -> dict:
    result = score_adversarial("dedup", {"ok": True, "text": output_text}, gold_case)
    return result


# ---------------------------------------------------------------------------
# stage 5 — knowledge graph
# ---------------------------------------------------------------------------

def score_graph(pred_nodes: list[str], pred_edges: list[tuple[str, str]],
                gold_nodes: list[str], gold_edges: list[tuple[str, str]]) -> dict:
    """Node name P/R/F1 + undirected edge precision/recall vs gold."""
    def edge_key(edge):
        a, b = sorted((_norm_key(edge[0]), _norm_key(edge[1])))
        return (a, b)

    pred_n = {_norm_key(n) for n in pred_nodes} - {""}
    gold_n = {_norm_key(n) for n in gold_nodes} - {""}
    n_tp = len(pred_n & gold_n)
    n_p = n_tp / max(1, len(pred_n))
    n_r = n_tp / max(1, len(gold_n))
    n_f1 = 2 * n_p * n_r / (n_p + n_r) if n_p + n_r else 0.0

    pred_e = {edge_key(e) for e in pred_edges if edge_key(e)[0] != edge_key(e)[1]}
    gold_e = {edge_key(e) for e in gold_edges}
    e_tp = len(pred_e & gold_e)
    e_p = e_tp / max(1, len(pred_e))
    e_r = e_tp / max(1, len(gold_e))
    return {
        "node_f1": round(n_f1, 4),
        "edge_precision": round(e_p, 4),
        "edge_recall": round(e_r, 4),
        "pred_edges": len(pred_e),
        "gold_edges": len(gold_e),
    }


# ---------------------------------------------------------------------------
# stage 6 — grounded drafting
# ---------------------------------------------------------------------------

def score_draft(draft_texts: list[str], source_text: str, concepts: list[dict],
                n_sections: int) -> dict:
    """Hard checks only: concept coverage, citation binding, metric fidelity,
    section completeness. Readability stays advisory."""
    joined = normalize_text("\n\n".join(draft_texts))
    source_norm = normalize_text(source_text)

    covered = sum(1 for c in concepts if _norm_key(c["name"]) in _norm_key(joined))
    coverage = covered / max(1, len(concepts))

    # citation binding: every sentence quoting a source span >= 60 chars must
    # carry a [n] marker
    sentences = re.split(r"(?<=[.!?])\s+", joined)
    bound = total = 0
    for sentence in sentences:
        long_quote = any(len(span) >= 60 and span in sentence
                         for span in re.findall(r"[^.!?]{60,}", source_norm))
        if long_quote:
            total += 1
            bound += int(bool(re.search(r"\[\d+\]", sentence)))
    binding = bound / total if total else 0.0

    # metric fidelity: every metric-looking token in the draft must exist in source
    draft_metrics = set(re.findall(r"\d+(?:\.\d+)?\s*(?:%|ms|GB|F1)", joined))
    fabricated = {m for m in draft_metrics if m not in source_norm}
    fidelity = 1.0 - len(fabricated) / max(1, len(draft_metrics))

    completeness = min(1.0, len(draft_texts) / max(1, n_sections))
    return {
        "concept_coverage": round(coverage, 4),
        "citation_binding": round(binding, 4),
        "metric_fidelity": round(fidelity, 4),
        "fabricated_metrics": sorted(fabricated),
        "completeness": round(completeness, 4),
        "score": round(0.3 * coverage + 0.3 * binding + 0.25 * fidelity
                       + 0.15 * completeness, 4),
    }


# ---------------------------------------------------------------------------
# stage 8 — export validity
# ---------------------------------------------------------------------------

DOCX_REQUIRED_PARTS = [
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
]


def score_docx(data: bytes) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            bad = z.testzip()
            names = set(z.namelist())
            document_xml = z.read("word/document.xml").decode("utf-8", "replace") \
                if "word/document.xml" in names else ""
    except Exception as exc:  # not a zip at all
        return {"valid": False, "error": str(exc)}
    missing = [p for p in DOCX_REQUIRED_PARTS if p not in names]
    return {
        "valid": bad is None and not missing and len(document_xml) > 100,
        "zip_ok": bad is None,
        "missing_parts": missing,
        "has_footnotes": "word/footnotes.xml" in names,
        "has_styles": "word/styles.xml" in names,
        "has_core_props": "docProps/core.xml" in names,
    }


def score_bibtex(bibtex: str, gold_refs: list[dict]) -> dict:
    entries = re.findall(r"@\w+\s*\{", bibtex)
    field_hits = 0
    for ref in gold_refs:
        author_ok = ref["author"].split(",")[0].lower() in bibtex.lower()
        year_ok = str(ref["year"]) in bibtex
        title_ok = _norm_key(ref["title"])[:30] in _norm_key(bibtex)
        field_hits += int(author_ok and year_ok and title_ok)
    return {
        "entry_count": len(entries),
        "gold_refs_covered": field_hits,
        "coverage": round(field_hits / max(1, len(gold_refs)), 4),
    }


def score_docx_v2(data: bytes, canonical_text: str) -> dict:
    """Weighted, discriminating DOCX score: validity is necessary but not
    sufficient — footnotes, styles, real heading styles, and text fidelity
    separate a manuscript writer from a minimal zip."""
    base = score_docx(data)
    if not base.get("valid"):
        return {"score": 0.0, "valid": False, "error": base.get("error", "")}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        document_xml = z.read("word/document.xml").decode("utf-8", "replace")
        footnotes_xml = z.read("word/footnotes.xml").decode("utf-8", "replace") \
            if "word/footnotes.xml" in z.namelist() else ""
    texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", document_xml)
    fidelity = token_prf(" ".join(texts), canonical_text)["f1"]
    heading_styles = bool(re.search(r'w:pStyle w:val="[^"]*Heading', document_xml))
    footnote_entries = len(re.findall(r"<w:footnote\b", footnotes_xml))
    parts = {
        "valid": 0.35,
        "footnotes": 0.15 if footnote_entries >= 2 else 0.0,
        "styles": 0.10 if base.get("has_styles") else 0.0,
        "heading_styles": 0.15 if heading_styles else 0.0,
        "text_fidelity": 0.25 * fidelity,
    }
    return {
        "score": round(sum(parts.values()), 4),
        "valid": True,
        "footnote_entries": footnote_entries,
        "heading_styles": heading_styles,
        "text_fidelity": fidelity,
        **{f"pts_{k}": round(v, 4) for k, v in parts.items()},
    }


def score_bibtex_v2(bibtex: str, hard_refs: list[dict]) -> dict:
    """Coverage + structure + escaping on adversarial references."""
    checks = {}
    for ref in hard_refs:
        surname = ref["author"].split(",")[0]
        key = surname.lower().replace("ü", "u")
        haystack = bibtex.lower()
        present = surname.lower() in haystack or key in haystack
        checks[f"author:{surname}"] = present
        if ref["year"] is not None:
            checks[f"year:{surname}"] = str(ref["year"]) in bibtex
        title_probe = _norm_key(ref["title"])[:20]
        checks[f"title:{surname}"] = title_probe.split()[0] in _norm_key(bibtex)
    checks["balanced_braces"] = bibtex.count("{") == bibtex.count("}")
    checks["no_raw_inner_braces"] = "{Revisited}" not in bibtex
    checks["no_none_year"] = not re.search(r"year\s*=\s*\{(None|null|)\}", bibtex)
    passed = sum(1 for v in checks.values() if v is True)
    return {"score": round(passed / max(1, len(checks)), 4), "checks": checks}


# ---------------------------------------------------------------------------
# stage 9 — convert egress validity (html / pdf); docx reuses score_docx_v2
# ---------------------------------------------------------------------------

class _HtmlTextParser(HTMLParser):
    """Collects all text plus the contents of h1-h6 heading tags."""

    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.texts: list[str] = []
        self.headings: list[str] = []
        self._heading_tag: str | None = None
        self._heading_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.HEADING_TAGS:
            self._heading_tag = tag
            self._heading_buf = []

    def handle_endtag(self, tag):
        if tag == self._heading_tag:
            self.headings.append("".join(self._heading_buf))
            self._heading_tag = None

    def handle_data(self, data):
        self.texts.append(data)
        if self._heading_tag:
            self._heading_buf.append(data)


def score_html_export(html_text: str, canonical_text: str) -> dict:
    """HTML egress: parseable + heading structure preserved + text fidelity."""
    if not html_text or "<" not in html_text:
        return {"score": 0.0, "wellformed": False, "error": "no html payload"}
    parser = _HtmlTextParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as exc:
        return {"score": 0.0, "wellformed": False, "error": str(exc)}
    gold_headings = re.findall(r"^#{1,6}\s+(.+)$", canonical_text, flags=re.M)
    heading_norms = [_norm_key(h) for h in parser.headings]
    found = sum(
        1 for h in gold_headings
        if any(hn and (_norm_key(h) == hn or _norm_key(h) in hn)
               for hn in heading_norms)
    )
    structure = found / max(1, len(gold_headings))
    fidelity = token_prf(" ".join(parser.texts), canonical_text)["f1"]
    return {
        "score": round(0.5 * structure + 0.5 * fidelity, 4),
        "wellformed": True,
        "headings_found": found,
        "headings_total": len(gold_headings),
        "text_fidelity": fidelity,
    }


def _pdf_unescape(value: str) -> str:
    return (value.replace(r"\(", "(").replace(r"\)", ")")
            .replace(r"\n", "\n").replace(r"\r", "").replace(r"\t", "\t")
            .replace(r"\\", "\\"))


def _pdf_literal_bytes(value: str) -> bytes:
    """Decode a PDF literal-string body (octal \\ddd and simple escapes)."""
    out = bytearray()
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt in "01234567":
                digits = ""
                j = i + 1
                while j < len(value) and len(digits) < 3 and value[j] in "01234567":
                    digits += value[j]
                    j += 1
                out.append(int(digits, 8) & 0xFF)
                i = j
                continue
            escapes = {"n": 10, "r": 13, "t": 9, "(": 40, ")": 41, "\\": 92}
            out.append(escapes.get(nxt, ord(nxt) & 0xFF))
            i += 2
            continue
        out.append(ord(char) & 0xFF)
        i += 1
    return bytes(out)


def _pdf_objects(data: bytes) -> dict[int, bytes]:
    """object number -> raw body (stream included). Objects embedded in
    compressed object streams (ObjStm; chromium/pdfbox writers) are unpacked
    too — that is where their font dicts and ToUnicode refs live."""
    objects = {}
    for m in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", data, re.S):
        objects[int(m.group(1))] = m.group(2)
    for body in list(objects.values()):
        if b"/ObjStm" not in body:
            continue
        header = re.search(rb"/N\s+(\d+).*?/First\s+(\d+)", body, re.S)
        stream = re.search(rb"stream\r?\n(.*?)endstream", body, re.S)
        if not header or not stream:
            continue
        count, first = int(header.group(1)), int(header.group(2))
        raw = stream.group(1).rstrip(b"\r\n")
        try:
            raw = zlib.decompress(raw)
        except Exception:
            pass
        ints = [int(x) for x in re.findall(rb"\d+", raw[:first])]
        pairs = list(zip(ints[0::2], ints[1::2]))[:count]
        for i, (onum, off) in enumerate(pairs):
            end = pairs[i + 1][1] if i + 1 < len(pairs) else len(raw) - first
            objects.setdefault(onum, raw[first + off:first + end])
    return objects


def _pdf_stream_text(body: bytes) -> str | None:
    """Decompressed stream content of an object body, if any."""
    m = re.search(rb"stream\r?\n(.*?)endstream", body, re.S)
    if not m:
        return None
    raw = m.group(1).rstrip(b"\r\n")
    try:
        raw = zlib.decompress(raw)
    except Exception:
        pass
    return raw.decode("latin1", "replace")


def _parse_tounicode(cmap_text: str) -> dict[int, str]:
    """bfchar/bfrange entries of a ToUnicode CMap: CID code -> unicode str."""
    cmap: dict[int, str] = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap_text, re.S):
        for m in re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            code = int(m.group(1), 16)
            cmap[code] = bytes.fromhex(m.group(2)).decode("utf-16-be", "replace")
    for block in re.findall(r"beginbfrange(.*?)endbfrange", cmap_text, re.S):
        for m in re.finditer(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            lo, hi, start = (int(m.group(i), 16) for i in (1, 2, 3))
            for k, code in enumerate(range(lo, hi + 1)):
                cmap[code] = chr(start + k)
        for m in re.finditer(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", block, re.S):
            lo = int(m.group(1), 16)
            for k, value in enumerate(re.findall(r"<([0-9A-Fa-f]+)>", m.group(3))):
                cmap[lo + k] = bytes.fromhex(value).decode("utf-16-be", "replace")
    return cmap


def _pdf_font_cmaps(data: bytes) -> dict[str, dict[int, str]]:
    """resource font name (/f0, /F1, ...) -> ToUnicode map, when present.

    Font resource dicts may be inline (`/Font << /F1 4 0 R >>`) or indirect
    (`/Font 19 0 R` pointing at a dict object), so resolve name -> font obj
    by scanning every reference whose target is a font with a ToUnicode."""
    objects = _pdf_objects(data)
    font_maps: dict[int, dict[int, str]] = {}
    for num, body in objects.items():
        if not re.search(rb"/Type\s*/Font\b", body):
            continue
        ref = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", body)
        if not ref:
            continue
        stream = _pdf_stream_text(objects.get(int(ref.group(1)), b""))
        if stream:
            font_maps[num] = _parse_tounicode(stream)
    cmaps: dict[str, dict[int, str]] = {}
    for body in objects.values():
        for m in re.finditer(rb"/(\w+)\s+(\d+)\s+0\s+R", body):
            num = int(m.group(2))
            if num in font_maps:
                cmaps[m.group(1).decode()] = font_maps[num]
    return cmaps


_PDF_SHOW = re.compile(
    r"/(\w+)\s+[\d.]+\s+Tf"                # font switch
    r"|\[(.*?)\]\s*TJ"                     # TJ array (kerning pieces of one line)
    r"|\(((?:\\.|[^\\()])*)\)\s*Tj"        # standalone literal string
    r"|<([0-9A-Fa-f\s]+)>\s*Tj"            # standalone hex string
    , re.S)

_PDF_STRING = re.compile(r"\(((?:\\.|[^\\()])*)\)|<([0-9A-Fa-f\s]+)>")


def _pdf_decode(raw_bytes: bytes, cmap: dict[int, str] | None) -> str:
    if cmap:
        chars = []
        for i in range(0, len(raw_bytes) - 1, 2):
            code = (raw_bytes[i] << 8) | raw_bytes[i + 1]
            chars.append(cmap.get(code, ""))
        return "".join(chars)
    return raw_bytes.decode("latin1", "replace")


def _pdf_text_chunks(data: bytes) -> list[str]:
    """Stdlib PDF text pull: Tj/TJ string operands inside BT/ET blocks over
    raw and flate-decompressed content streams. CID-keyed fonts (typst,
    chromium) are decoded through their ToUnicode CMaps; simple fonts fall
    back to single-byte latin1. Pieces inside one TJ array are joined (they
    are kerning splits of a single line); separate showing ops are spaced."""
    font_cmaps = _pdf_font_cmaps(data)
    chunks: list[str] = []
    streams = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = match.group(1).rstrip(b"\r\n")
        streams.append(raw)
        try:
            streams.append(zlib.decompress(raw))
        except Exception:
            pass
    for blob in streams:
        content = blob.decode("latin1", "replace")
        for block in re.findall(r"BT(.*?)ET", content, re.S):
            font: str | None = None
            pieces: list[str] = []
            for tok in _PDF_SHOW.finditer(block):
                if tok.group(1) is not None:
                    font = tok.group(1)
                    continue
                cmap = font_cmaps.get(font or "")
                if tok.group(2) is not None:  # TJ array: join inner strings
                    inner = []
                    for s in _PDF_STRING.finditer(tok.group(2)):
                        if s.group(1) is not None:
                            inner.append(_pdf_decode(
                                _pdf_literal_bytes(s.group(1)), cmap))
                        else:
                            hexstr = re.sub(r"\s+", "", s.group(2) or "")
                            if hexstr:
                                inner.append(_pdf_decode(
                                    bytes.fromhex(hexstr), cmap))
                    pieces.append("".join(inner))
                elif tok.group(3) is not None:
                    pieces.append(_pdf_decode(
                        _pdf_literal_bytes(tok.group(3)), cmap))
                else:
                    hexstr = re.sub(r"\s+", "", tok.group(4) or "")
                    if hexstr:
                        pieces.append(_pdf_decode(bytes.fromhex(hexstr), cmap))
            if pieces:
                chunks.append(" ".join(p for p in pieces if p))
    return chunks


def score_pdf_export(data: bytes, canonical_text: str) -> dict:
    """PDF egress: valid header + extractable text + text fidelity."""
    header_ok = data[:5] == b"%PDF-"
    text = " ".join(_pdf_text_chunks(data))
    parseable = bool(header_ok and len(text.strip()) >= 40)
    fidelity = token_prf(text, canonical_text)["f1"] if parseable else 0.0
    return {
        "score": round(0.5 * float(parseable) + 0.5 * fidelity, 4),
        "header_ok": bool(header_ok),
        "parseable": parseable,
        "text_fidelity": fidelity,
    }


# ---------------------------------------------------------------------------
# cross-cutting — determinism
# ---------------------------------------------------------------------------

def deterministic(output_a, output_b) -> bool:
    return json.dumps(output_a, sort_keys=True, default=str) == \
           json.dumps(output_b, sort_keys=True, default=str)
