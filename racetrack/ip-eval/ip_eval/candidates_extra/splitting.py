"""Splitting family plugin (pack 02) — four candidates for the `split` stage.

- ontocast-chunker: growgraph_ontocast corpus
  (code/ontocast/tool/chunk/chunker.py). Honest unavailable: the module is
  not importable standalone (chunker.py drags pydantic/rdflib plus
  hdbscan/umap-learn/scikit-learn/langchain via ontocast.tool.chunk.util)
  and its semantic mode needs sentence-transformers model weights, which
  this suite never downloads. The naive fallback is not exposed without
  that full import chain.
- opennlp-split: apache_opennlp corpus (Java/Maven). Gate on
  shutil.which("java") + honest refusal; no maven build is attempted.
- paperspine-split: WUBING2023_PaperSpine corpus
  (code/src/scripts/structured_review.py). Its section-structuring logic
  (extract_sections: TeX \\section{...} regex split, single-section
  fallback) is deterministic and stdlib-only, so it is imported by file
  path and driven on the content.
- undoc-headings: iyulab_undoc corpus. Reuses the built shim binary at
  .venv-candidates/undoc/bin/undoc-extract if present (never rebuilds).
  The binary renders docx/xlsx/pptx files to markdown; split() receives
  plain text, so the heading analyzer cannot be driven honestly on this
  stage's input — reports unavailable with the true reason.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import REPOS, VENVS, Candidate  # noqa: E402

ONTOCAST_CHUNKER = REPOS / "growgraph_ontocast" / "code" / "ontocast" / "tool" / "chunk" / "chunker.py"
OPENNLP_SRC = REPOS / "apache_opennlp"
PAPERSPINE_SCRIPT = REPOS / "WUBING2023_PaperSpine" / "code" / "src" / "scripts" / "structured_review.py"
UNDOC_BIN = VENVS / "undoc" / "bin" / "undoc-extract"  # same path as extraction.py:145

# mirrors SECTION_RE in WUBING2023_PaperSpine .../scripts/structured_review.py:33
_TEX_SECTION_RE = re.compile(r"\\(?:section|subsection|subsubsection)\*?\{")


class OntoCastChunker(Candidate):
    """growgraph_ontocast ChunkerTool — honest refusal.

    chunker.py:1-13 imports the full ontocast package: pydantic, rdflib
    (via tool/onto.py) and, via tool/chunk/util.py:5-10, numpy + hdbscan +
    umap-learn + scikit-learn + langchain_core at module load. Its semantic
    mode (chunker.py:38-47, 244-253) needs a sentence-transformers model
    download, which is disallowed. The naive fallback (chunker.py:120-175)
    cannot be reached without that import chain, and porting it inline is
    not one of the paths this pack allows for this candidate.
    """
    name = "ontocast-chunker"
    stages = {"split"}

    def available(self):
        if not ONTOCAST_CHUNKER.exists():
            return False, f"corpus path missing: {ONTOCAST_CHUNKER}"
        return False, (
            "ontocast chunker not importable standalone: module load drags "
            "hdbscan/umap-learn/scikit-learn/langchain_core + rdflib, and its "
            "semantic mode needs sentence-transformers model weights (no "
            "model downloads allowed); naive path not reachable standalone"
        )


class OpenNLPSplit(Candidate):
    """apache_opennlp sentence detector — Java-gated honest refusal.

    Corpus: apache_opennlp opennlp-runtime/src/main/java/opennlp/tools/
    sentdetect/. Running it needs a maven build (not attempted on this
    box) plus a downloaded sentence-detection model (disallowed).
    """
    name = "opennlp-split"
    stages = {"split"}

    def available(self):
        if not shutil.which("java"):
            return False, "opennlp is a Java/Maven project; no java on this box"
        return False, (
            "java present, but opennlp needs a maven build (not attempted on "
            "this box) and a downloaded sentence-detection model (disallowed)"
        )


class PaperSpineSplit(Candidate):
    """WUBING2023_PaperSpine structured_review.extract_sections, file-path import.

    Corpus: WUBING2023_PaperSpine code/src/scripts/structured_review.py:206-221.
    TeX input is split on \\section/\\subsection/\\subsubsection{...}
    (SECTION_RE, line 33); anything else yields a single "Full Manuscript"
    section. The script and its _paper_spine_utils sibling are stdlib-only,
    so no venv is provisioned. split() writes the content to a temp file
    (.tex suffix when it holds a TeX section command, else .md) and maps
    the corpus output to [{id, order, title, content}], 1-based.
    """
    name = "paperspine-split"
    stages = {"split"}

    def __init__(self):
        self._mod = None

    def available(self):
        try:
            if not PAPERSPINE_SCRIPT.exists():
                return False, f"corpus path missing: {PAPERSPINE_SCRIPT}"
            spec = importlib.util.spec_from_file_location(
                "paperspine_structured_review", PAPERSPINE_SCRIPT)
            mod = importlib.util.module_from_spec(spec)
            # register before exec: @dataclass looks up sys.modules[__module__]
            sys.modules[spec.name] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception:
                sys.modules.pop(spec.name, None)
                raise
            self._mod = mod
            return True, ""
        except Exception as exc:  # available() must never raise
            self._mod = None
            return False, f"paperspine import failed: {exc}"

    def split(self, content: str) -> list[dict]:
        if self._mod is None:
            raise RuntimeError("paperspine module not provisioned; call available() first")
        suffix = ".tex" if _TEX_SECTION_RE.search(content) else ".md"
        with tempfile.NamedTemporaryFile(
                "w", suffix=suffix, encoding="utf-8", delete=False) as fh:
            fh.write(content)
            tmp = Path(fh.name)
        try:
            raw_sections = self._mod.extract_sections(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        sections = []
        for order, sec in enumerate(raw_sections, 1):
            sections.append({
                "id": f"s{order}",
                "order": order,
                "title": sec.get("title", ""),
                "content": "\n\n".join(sec.get("paragraphs", [])),
            })
        return sections


class UndocHeadings(Candidate):
    """iyulab_undoc heading analyzer — honest refusal on this stage.

    Reuses (read-only, never rebuilds) the shim binary built by
    extraction.py's _build_undoc at .venv-candidates/undoc/bin/undoc-extract.
    That binary parses docx/xlsx/pptx FILES and renders markdown; the DOCX
    style->heading analysis (corpus code/src/docx/parser.rs,
    render/heading_analyzer.rs) happens inside the render and is not
    exposed as a text->sections API. split(content) receives already-
    extracted plain text, so there is no honest way to drive the binary
    on this stage's input.
    """
    name = "undoc-headings"
    stages = {"split"}

    def available(self):
        if not UNDOC_BIN.exists():
            return False, (
                f"undoc shim binary not built ({UNDOC_BIN}); pack rule is "
                "reuse-only (no rebuild), and split() receives text, not a "
                "docx file the binary could parse"
            )
        return False, (
            "undoc-extract renders docx/xlsx/pptx files to markdown; split() "
            "receives plain text, so the heading analyzer cannot be driven "
            "honestly on this stage's input"
        )


CANDIDATES = [OntoCastChunker, OpenNLPSplit, PaperSpineSplit, UndocHeadings]
