"""Deterministic fixture generator — the grader-owned oracle.

Every document is synthesized from a seeded RNG. Gold (sections, concepts,
metrics, citations, canonical normalized text) is recorded at generation time
in fixtures/gold.json, which candidates must never read.

Re-runnable and idempotent: existing fixtures are left untouched unless
--force is given, so frozen gold can never silently drift under a race.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import unicodedata
import zipfile
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
GOLD_PATH = FIXTURES_DIR / "gold.json"
SEED = 20260727


# ---------------------------------------------------------------------------
# normalization (mirrors the oracle; candidates are scored against this)
# ---------------------------------------------------------------------------

def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("’", "'").replace("‘", "'")
    value = value.replace("“", '"').replace("”", '"')
    value = value.replace("—", "-").replace("–", "-")
    value = value.replace(" ", " ")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


# ---------------------------------------------------------------------------
# logical document model
# ---------------------------------------------------------------------------

CONCEPTS = [
    # (canonical name, type, acronym_or_none)
    ("Evidence Graph Transformer", "Architecture", "EGT"),
    ("Local Evidence Retriever", "System Component", "LER"),
    ("Adaptive Chunking Algorithm", "Method", None),
    ("SciFact Corpus", "Dataset", None),
    ("Citation Verifier Pipeline", "System Component", None),
    ("Hybrid Retrieval Method", "Method", None),
    ("Review Benchmark Dataset", "Dataset", None),
]

SECTION_PLAN = [
    ("Abstract", 2),
    ("Introduction", 3),
    ("Methods", 4),
    ("Experiments", 3),
    ("Results", 3),
    ("Discussion", 2),
    ("Conclusion", 1),
]

_SENTENCE_TEMPLATES = [
    "The {c} achieves {v}% accuracy on the {d}.",
    "We pair the {c} with the {c2} to keep attribution exact.",
    "Across three seeds the {c} holds latency of {ms} ms at p95.",
    "The {c} reduces extraction error by {v}% relative to the baseline.",
    "Ablation on the {d} shows the {c} contributes {v} F1 points.",
    "The {c} processes {n} documents while staying under {gb} GB of memory.",
    "Unlike prior work, the {c} never fabricates a citation it cannot trace.",
    "The {c2} reuses spans emitted by the {c} without re-parsing the source.",
]

_REF_POOL = [
    ("Vaswani", 2017, "Attention Is All You Need"),
    ("Lewis", 2020, "Retrieval-Augmented Generation for Knowledge-Intensive NLP"),
    ("Karpukhin", 2020, "Dense Passage Retrieval for Open-Domain QA"),
    ("Wadden", 2020, "Fact or Fiction: Verifying Scientific Claims"),
    ("Beltagy", 2019, "SciBERT: A Pretrained Language Model for Scientific Text"),
    ("Devlin", 2019, "BERT: Pre-training of Deep Bidirectional Transformers"),
]


def _sentences_for(rng: random.Random, count: int, concepts, dataset: str):
    out = []
    used_metrics = []
    for _ in range(count):
        template = rng.choice(_SENTENCE_TEMPLATES)
        c, c2 = rng.sample(concepts, 2)
        value = rng.randint(3, 97) + rng.choice([0, 0.2, 0.5])
        ms = rng.randint(40, 900)
        n = rng.randint(8, 400)
        gb = rng.choice([2, 4, 8, 12])
        sentence = template.format(c=c, c2=c2, v=value, ms=ms, n=n, d=dataset, gb=gb)
        out.append(sentence)
        for m in re.finditer(r"\d+(?:\.\d+)?\s*(?:%|ms|GB|F1)", sentence):
            used_metrics.append(m.group(0))
    return out, used_metrics


def make_logical_doc(key: str, seed: int):
    """Build the logical (format-independent) document. Grader-only."""
    rng = random.Random(seed)
    concept_pairs = rng.sample(CONCEPTS, 4)
    names = [c[0] for c in concept_pairs]
    dataset = next(c[0] for c in concept_pairs if c[1] == "Dataset") if any(
        c[1] == "Dataset" for c in concept_pairs) else "SciFact Corpus"
    title = {
        "alpha": "Grounded Evidence Pipelines for Scientific Write-ups",
        "beta": "Deterministic Chunking and Citation Audits at Scale",
    }[key]
    authors = [rng.choice(["Okafor", "Nguyen", "Garcia"]) + ", A."]
    year = rng.choice([2023, 2024, 2025])

    sections = []
    all_metrics = []
    for heading, para_count in SECTION_PLAN:
        paragraphs = []
        for _ in range(para_count):
            sents, metrics = _sentences_for(rng, rng.randint(2, 3), names, dataset)
            all_metrics.extend(metrics)
            paragraphs.append(" ".join(sents))
        sections.append({"heading": heading, "paragraphs": paragraphs})

    refs = rng.sample(_REF_POOL, 4)
    gold = {
        "key": key,
        "title": title,
        "authors": authors,
        "year": year,
        "sections": [{"heading": s["heading"], "paragraphs": s["paragraphs"]} for s in sections],
        "concepts": [
            {"name": c[0], "type": c[1], "acronym": c[2]} for c in concept_pairs
        ],
        "nested_pairs": [
            ["Evidence Graph", "Evidence Graph Transformer"],
            ["Review Benchmark", "Review Benchmark Dataset"],
        ],
        "metrics": sorted(set(all_metrics)),
        "references": [
            {"author": a, "year": y, "title": t} for a, y, t in refs
        ],
    }
    return gold


# ---------------------------------------------------------------------------
# renderers — logical doc -> bytes per format
# ---------------------------------------------------------------------------

def render_markdown(doc) -> str:
    lines = [f"# {doc['title']}", ""]
    for s in doc["sections"]:
        lines.append(f"## {s['heading']}")
        lines.append("")
        for p in s["paragraphs"]:
            lines.append(p)
            lines.append("")
    lines.append("## References")
    lines.append("")
    for i, r in enumerate(doc["references"], 1):
        lines.append(f"[{i}] {r['author']} ({r['year']}). {r['title']}.")
        lines.append("")
    return "\n".join(lines)


def render_html(doc) -> str:
    parts = ["<html><head><meta charset='utf-8'><title>%s</title></head><body>" % doc["title"]]
    parts.append(f"<h1>{doc['title']}</h1>")
    for s in doc["sections"]:
        parts.append(f"<h2>{s['heading']}</h2>")
        for p in s["paragraphs"]:
            parts.append(f"<p>{p}</p>")
    parts.append("<h2>References</h2><ol>")
    for r in doc["references"]:
        parts.append(f"<li>{r['author']} ({r['year']}). {r['title']}.</li>")
    parts.append("</ol></body></html>")
    return "\n".join(parts)


def render_txt(doc) -> str:
    lines = [doc["title"], ""]
    for i, s in enumerate(doc["sections"], 1):
        lines.append(f"{i}. {s['heading']}")
        lines.append("")
        for p in s["paragraphs"]:
            lines.append(p)
            lines.append("")
    lines.append(f"{len(doc['sections']) + 1}. References")
    lines.append("")
    for i, r in enumerate(doc["references"], 1):
        lines.append(f"[{i}] {r['author']} ({r['year']}). {r['title']}.")
    return "\n".join(lines)


def _xml_escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_docx(doc) -> bytes:
    """Minimal OPC .docx, stdlib-only. Heading styles + body paragraphs."""
    body = []

    def para(text, style=None):
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body.append(f"<w:p>{ppr}<w:r><w:t xml:space='preserve'>{_xml_escape(text)}</w:t></w:r></w:p>")

    para(doc["title"], "Title")
    for s in doc["sections"]:
        para(s["heading"], "Heading1")
        for p in s["paragraphs"]:
            para(p)
    para("References", "Heading1")
    for i, r in enumerate(doc["references"], 1):
        para(f"[{i}] {r['author']} ({r['year']}). {r['title']}.")

    document_xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main' "
        "xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>"
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )
    content_types = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
        "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"
        "<Default Extension='xml' ContentType='application/xml'/>"
        "<Override PartName='/word/document.xml' ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/>"
        "</Types>"
    )
    rels = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
        "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='word/document.xml'/>"
        "</Relationships>"
    )
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document_xml)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# minimal PDF writer (literal text operators; no compression)
# ---------------------------------------------------------------------------

def _pdf_escape(value: str) -> str:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def render_pdf(pages_lines: list[list[str]]) -> bytes:
    """pages_lines: list of pages, each a list of text lines."""
    objects: list[bytes] = []

    def add(body: str) -> int:
        objects.append(body.encode("latin1"))
        return len(objects)  # 1-based object number

    catalog_id = add("<< /Type /Catalog /Pages 2 0 R >>")
    kids = []
    page_ids = []
    content_ids = []
    next_id = 3
    for _ in pages_lines:
        page_ids.append(next_id)
        content_ids.append(next_id + 1)
        next_id += 2
    font_id = next_id

    kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
    add(f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_ids)} >>")
    assert len(objects) == catalog_id + 1  # objects 1,2 placed

    for idx, lines in enumerate(pages_lines):
        content_id = content_ids[idx]
        add(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>")
        stream_lines = ["BT", "/F1 11 Tf", "72 740 Td", "14 TL"]
        for line in lines:
            stream_lines.append(f"({_pdf_escape(line)}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines)
        add(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")

    add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin1") + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin1")
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("latin1")
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode("latin1")
    return bytes(out)


def doc_to_pdf_lines(doc, max_line: int = 88):
    """Wrap the logical doc into PDF text lines, one page per ~44 lines."""
    import textwrap
    raw = [doc["title"], ""]
    for s in doc["sections"]:
        raw.append(s["heading"])
        for p in s["paragraphs"]:
            raw.extend(textwrap.wrap(p, max_line))
            raw.append("")
    raw.append("References")
    for i, r in enumerate(doc["references"], 1):
        raw.append(f"[{i}] {r['author']} ({r['year']}). {r['title']}.")
    pages = [raw[i:i + 44] for i in range(0, len(raw), 44)]
    return pages


# ---------------------------------------------------------------------------
# adversarial fixtures
# ---------------------------------------------------------------------------

UNICODE_PARAGRAPH = (
    "The ﬁnal “Evidence Graph Transformer” run — seeded deterministically — "
    "keeps café-style combining marks and  non-breaking spaces intact enough "
    "to test normalization, smart ‘quotes’, and ligatures such as ﬂow."
)

FURNITURE_BODY = [
    "The Evidence Graph Transformer anchors each citation to a source span.",
    "Retrieval quality improves when page furniture is removed before chunking.",
    "Footnote: the ablation corpus is public and must survive furniture removal.",
]


def build_fixtures(force: bool = False) -> dict:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    if GOLD_PATH.exists() and not force:
        return json.loads(GOLD_PATH.read_text())

    gold = {"seed": SEED, "documents": {}, "adversarial": {}}
    docs_dir = FIXTURES_DIR / "docs"
    docs_dir.mkdir(exist_ok=True)

    # --- main logical docs, rendered cross-format -------------------------
    for key, seed in (("alpha", SEED), ("beta", SEED + 1)):
        logical = make_logical_doc(key, seed)
        entry = {"formats": {}, **{k: v for k, v in logical.items() if k != "key"}}
        renders = {
            "md": ("text/markdown", render_markdown(logical).encode("utf-8")),
            "html": ("text/html", render_html(logical).encode("utf-8")),
            "txt": ("text/plain", render_txt(logical).encode("utf-8")),
            "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                     render_docx(logical)),
            "pdf": ("application/pdf", render_pdf(doc_to_pdf_lines(logical))),
        }
        for fmt, (mime, data) in renders.items():
            name = f"{key}.{fmt}"
            (docs_dir / name).write_bytes(data)
            entry["formats"][fmt] = {
                "file": f"docs/{name}",
                "mime": mime,
                # canonical text a perfect extractor should produce
                "canonical_text": normalize_text(render_markdown(logical)),
            }
        gold["documents"][key] = entry

    # --- adversarial pack --------------------------------------------------
    adv = {}

    (docs_dir / "empty.bin").write_bytes(b"")
    adv["empty"] = {"file": "docs/empty.bin", "expect": "graceful-empty"}

    (docs_dir / "corrupt.pdf").write_bytes(b"%PDF-1.4\nbroken xref with no objects at all%%EOF")
    adv["corrupt_pdf"] = {"file": "docs/corrupt.pdf", "expect": "graceful-failure"}

    # misleading extension: html content in a .txt name
    misleading = render_html(make_logical_doc("alpha", SEED)).encode("utf-8")
    (docs_dir / "misleading.txt").write_bytes(misleading)
    adv["misleading_extension"] = {
        "file": "docs/misleading.txt", "expect": "content-sniffing",
        "canonical_text": normalize_text(render_markdown(make_logical_doc("alpha", SEED))),
    }

    (docs_dir / "unicode.md").write_text(
        "# Unicode Torture\n\n## Methods\n\n" + UNICODE_PARAGRAPH + "\n", encoding="utf-8")
    adv["unicode_normalization"] = {
        "file": "docs/unicode.md",
        "expect": "normalized-equivalence",
        "canonical_text": normalize_text("# Unicode Torture\n\n## Methods\n\n" + UNICODE_PARAGRAPH),
    }

    # page-furniture PDF: repeated header/footer, one real footnote
    pages = []
    for page_no in range(1, 4):
        lines = ["Confidential Draft 7", f"Page {page_no} of 3", ""]
        lines.extend(FURNITURE_BODY)
        lines.extend(["", "Confidential Draft 7", f"Page {page_no} of 3"])
        pages.append(lines)
    (docs_dir / "furniture.pdf").write_bytes(render_pdf(pages))
    adv["page_furniture"] = {
        "file": "docs/furniture.pdf",
        "expect": "furniture-removed-footnote-kept",
        "must_contain": ["Footnote: the ablation corpus is public"],
        "must_not_repeat": ["Confidential Draft 7"],
        "body_sentences": FURNITURE_BODY,
    }

    # dedup torture v2: required merges AND forbidden merges. A deduper that
    # collapses number/entity swaps is destroying evidence; one that misses
    # punctuation variants is leaving redundancy.
    unique_a = "The Adaptive Chunking Algorithm splits on headings before size limits."
    unique_b = "Citation audits reject any reference that lacks a source span."
    dup = "The Local Evidence Retriever ranks 12 vault sentences by coverage."
    dup_punct = "The Local Evidence Retriever ranks 12 vault sentences by coverage!"
    swap_num = "The Local Evidence Retriever ranks 47 vault sentences by coverage."
    swap_ent = "The Global Evidence Retriever ranks 12 vault sentences by coverage."
    dedup_md = "# Dedup Torture\n\n## Methods\n\n" + "\n\n".join(
        [unique_a, dup, unique_b, dup, dup_punct, swap_num, swap_ent]) + "\n"
    (docs_dir / "dedup.md").write_text(dedup_md, encoding="utf-8")
    adv["dedup"] = {
        "file": "docs/dedup.md",
        "expect": "merge-required-and-forbidden",
        "must_keep": [unique_a, unique_b, dup, swap_num, swap_ent],
        "must_merge_away": [dup_punct],  # punctuation variant of dup
    }

    # split torture: setext title, numbered headings, a false-heading prose
    # trap ("Results are discussed later..."), subsection numbering.
    gamma_md = (
        "Deterministic Fixture Methods\n"
        "=============================\n"
        "\n"
        "Opening paragraph on fixture design for the split race.\n"
        "\n"
        "2. Methods\n"
        "\n"
        "We describe the heading-detection protocol in prose form.\n"
        "\n"
        "Results are discussed later in the paper.\n"
        "\n"
        "2.1 Data\n"
        "\n"
        "Synthetic corpora with planted boundaries drive evaluation.\n"
        "\n"
        "2.2 Setup\n"
        "\n"
        "Each candidate sees identical canonical text.\n"
        "\n"
        "Scoring Notes\n"
        "-------------\n"
        "\n"
        "Boundary precision and recall are computed over heading sets.\n"
    )
    (docs_dir / "gamma.md").write_text(gamma_md, encoding="utf-8")
    adv["split_torture"] = {
        "file": "docs/gamma.md",
        "expect": "heading-precision-and-recall",
        "gold_headings": ["2. Methods", "2.1 Data", "2.2 Setup", "Scoring Notes"],
        "false_heading_traps": ["Results are discussed later in the paper."],
    }

    gold["adversarial"] = adv

    # retrieval hard queries: acronym resolution, paraphrase, near-topic
    # distractor. Authored (not RNG) so the grader owns every judgment.
    hard_sentences = [
        "The Local Evidence Retriever (LER) ranks vault sentences by coverage.",
        "LER keeps every citation span attached to its source sentence.",
        "The Local Alignment Ranker reorders vault sentences by coverage.",
        "Evidence retrieval from local vaults keeps drafted claims grounded.",
        "The Citation Verifier Pipeline audits each reference before export.",
        "Adaptive chunking splits documents on headings before size limits.",
        "Graph edges record co-occurrence inside a shared section.",
        "Export writes a valid DOCX package with native footnotes.",
    ]
    # tabilify fixture: prose metrics with signs/negation/uncertainty + real
    # markdown tables (standard, transposed, missing values). Grader owns the
    # structured records every candidate must reproduce.
    tabilify_md = (
        "# Results Tabulation\n\n"
        "## Results\n\n"
        "The Evidence Graph Transformer reaches 94.2% accuracy, up 2.1 points "
        "from the 92.1% baseline. Its p95 latency is 182 ms, and memory stays "
        "under 12 GB. The Local Evidence Retriever shows no improvement over "
        "the 88.4% control.\n\n"
        "| Method | Accuracy | p95 Latency |\n"
        "|---|---|---|\n"
        "| Evidence Graph Transformer | 94.2% | 182 ms |\n"
        "| Local Evidence Retriever | 91.7% | 145 ms |\n"
        "| Baseline | 88.4% | — |\n"
        "\n"
        "| Metric | Evidence Graph Transformer | Local Evidence Retriever |\n"
        "|---|---|---|\n"
        "| Accuracy | 94.2% | 91.7% |\n"
        "| Memory | 12 GB | 8 GB |\n"
    )
    (docs_dir / "tabilify.md").write_text(tabilify_md, encoding="utf-8")
    gold["tabilify"] = {
        "file": "docs/tabilify.md",
        "records": [
            # prose metrics
            {"subject": "Evidence Graph Transformer", "metric": "accuracy",
             "value": "94.2", "unit": "%", "origin": "prose"},
            {"subject": "baseline", "metric": "accuracy",
             "value": "92.1", "unit": "%", "origin": "prose"},
            {"subject": "Evidence Graph Transformer", "metric": "p95 latency",
             "value": "182", "unit": "ms", "origin": "prose"},
            {"subject": "control", "metric": "accuracy",
             "value": "88.4", "unit": "%", "origin": "prose"},
            # standard table
            {"subject": "Evidence Graph Transformer", "metric": "Accuracy",
             "value": "94.2", "unit": "%", "origin": "table"},
            {"subject": "Evidence Graph Transformer", "metric": "p95 Latency",
             "value": "182", "unit": "ms", "origin": "table"},
            {"subject": "Local Evidence Retriever", "metric": "Accuracy",
             "value": "91.7", "unit": "%", "origin": "table"},
            {"subject": "Local Evidence Retriever", "metric": "p95 Latency",
             "value": "145", "unit": "ms", "origin": "table"},
            {"subject": "Baseline", "metric": "Accuracy",
             "value": "88.4", "unit": "%", "origin": "table"},
            # transposed table
            {"subject": "Evidence Graph Transformer", "metric": "Memory",
             "value": "12", "unit": "GB", "origin": "table"},
            {"subject": "Local Evidence Retriever", "metric": "Memory",
             "value": "8", "unit": "GB", "origin": "table"},
        ],
        # Baseline p95 latency is "—": reporting a value for it is fabrication
        "must_not_report": [
            {"subject": "Baseline", "metric": "p95 Latency"},
        ],
    }

    gold["retrieval_hard"] = {
        "corpus": hard_sentences,
        "queries": [
            {"query": "LER",
             "gold": [hard_sentences[0], hard_sentences[1]],
             "note": "acronym resolution"},
            {"query": "local evidence retrieval",
             "gold": [hard_sentences[3]],
             "note": "paraphrase; sentence 2 is a near-topic distractor"},
            {"query": "Local Evidence Retriever",
             "gold": [hard_sentences[0], hard_sentences[1]],
             "note": "exact phrase vs distractor sentence 2"},
        ],
    }

    # graph hard case: similar-name concepts that NEVER co-occur are
    # false-edge traps for similarity-based linkers. Authored, grader-owned.
    gold["graph_hard"] = {
        "concepts": [
            {"id": "h1", "name": "Evidence Graph Transformer", "type": "Architecture",
             "sectionIds": ["s1", "s2"],
             "evidence": "The Evidence Graph Transformer anchors each claim to a span."},
            {"id": "h2", "name": "Graph Attention Encoder", "type": "Architecture",
             "sectionIds": ["s2"],
             "evidence": "The Graph Attention Encoder weights pairwise node messages."},
            {"id": "h3", "name": "Evidence Graph Decoder", "type": "Architecture",
             "sectionIds": ["s3"],
             "evidence": "The Evidence Graph Decoder reconstructs triples from node states."},
            {"id": "h4", "name": "Local Evidence Retriever", "type": "System Component",
             "sectionIds": ["s1", "s3"],
             "evidence": "The Local Evidence Retriever ranks vault sentences by coverage."},
            {"id": "h5", "name": "Evidence Coverage Metric", "type": "Metric",
             "sectionIds": ["s3"],
             "evidence": "The Evidence Coverage Metric counts supported claims per section."},
            {"id": "h6", "name": "Citation Verifier Pipeline", "type": "System Component",
             "sectionIds": ["s4"],
             "evidence": "The Citation Verifier Pipeline audits each reference before export."},
            {"id": "h7", "name": "Verifier Pipeline Audit", "type": "Method",
             "sectionIds": ["s5"],
             "evidence": "The Verifier Pipeline Audit replays historical citation checks."},
            {"id": "h8", "name": "Adaptive Chunking Algorithm", "type": "Method",
             "sectionIds": ["s4"],
             "evidence": "The Adaptive Chunking Algorithm splits on headings first."},
        ],
        # gold edges = true section co-occurrence only
        "gold_edges": [
            ["Evidence Graph Transformer", "Graph Attention Encoder"],
            ["Evidence Graph Transformer", "Local Evidence Retriever"],
            ["Evidence Graph Decoder", "Local Evidence Retriever"],
            ["Local Evidence Retriever", "Evidence Coverage Metric"],
            ["Citation Verifier Pipeline", "Adaptive Chunking Algorithm"],
        ],
        "false_edge_traps": [
            ["Evidence Graph Transformer", "Evidence Graph Decoder"],
            ["Citation Verifier Pipeline", "Verifier Pipeline Audit"],
            ["Evidence Graph Decoder", "Evidence Coverage Metric"],
        ],
    }

    # bibtex hard references: unicode names, braces/& in title, missing year
    gold["bibtex_hard"] = [
        {"author": "Müller, B.", "year": 2024,
         "title": "Benchmarks & Braces {Revisited}: 100% Coverage"},
        {"author": "O'Neil, C.", "year": None,
         "title": "Undated Fragments"},
    ]

    gold["version"] = 2
    GOLD_PATH.write_text(json.dumps(gold, indent=2, ensure_ascii=False))
    return gold


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="regenerate fixtures and gold")
    args = parser.parse_args()
    gold = build_fixtures(force=args.force)
    n_docs = len(gold["documents"])
    n_adv = len(gold["adversarial"])
    print(f"fixtures ready: {n_docs} documents x 5 formats, {n_adv} adversarial cases -> {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
