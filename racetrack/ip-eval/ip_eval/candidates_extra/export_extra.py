"""export family extras — corpus-repo gated candidates (pack 08).

All four candidates are honest refusals on this box; none fabricate output:

- jabref-bibtex (corpus JabRef_jabref, Java/Gradle): JabRef's BibTeX
  machinery (e.g. jablib/.../citationkeypattern/CitationKeyGenerator.java)
  only runs as part of the full Gradle build. There is no java on this box
  and Gradle builds are not attempted in the race lane, so the candidate
  reports unavailable with the true reason.
- doxx-export (corpus bgreenwell_doxx, Rust): direction check failed. doxx
  is a DOCX *reader/renderer* — its export surface (code/src/export.rs:
  export_document -> Markdown/Text/Csv/Json/Ansi) cannot write DOCX. Its
  docx-rs dependency is used only for reading (document/loader.rs:
  read_docx) and test-fixture generation (bin/generate_test_docs.rs), so
  building a markdown->DOCX shim on top of it would not be doxx. Reports
  unavailable with that true reason instead of shipping a fake writer.
- mdxjs-rs (corpus wooorm_mdxjs-rs) and mdx-rs (corpus web-infra-dev_mdx-rs):
  both are MDX compilers whose public API compiles MDX to JSX/JavaScript
  (code/src/lib.rs and code/crates/mdx_rs/src/lib.rs, `compile()`); neither
  can emit DOCX bytes, so they report unavailable with the true reason.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import REPOS, Candidate  # noqa: E402

JABREF_SRC = REPOS / "JabRef_jabref" / "code"
DOXX_SRC = REPOS / "bgreenwell_doxx" / "code"
MDXJS_SRC = REPOS / "wooorm_mdxjs-rs" / "code"
MDX_RS_SRC = REPOS / "web-infra-dev_mdx-rs" / "code"


class JabrefBibtex(Candidate):
    """JabRef BibTeX export — Java-gated honest refusal (no gradle build)."""

    name = "jabref-bibtex"
    stages = {"export_bibtex"}

    def available(self):
        try:
            if not shutil.which("java"):
                return False, ("jabref is a Java/Gradle project; "
                               "no java on this box")
            if not JABREF_SRC.exists():
                return False, f"corpus path missing: {JABREF_SRC}"
            return False, ("java present, but JabRef's BibTeX export requires a "
                           "full Gradle build of jabref/jablib, which is not "
                           "attempted in the race lane")
        except Exception as exc:
            return False, f"availability check failed: {exc}"

    def export_bibtex(self, citations: list[dict]) -> str:
        raise RuntimeError("jabref-bibtex is unavailable; see available() reason")


class DoxxExport(Candidate):
    """bgreenwell_doxx — refused: the library reads DOCX, it cannot write it."""

    name = "doxx-export"
    stages = {"export_docx"}

    def available(self):
        try:
            if not shutil.which("cargo"):
                return False, "cargo not on PATH"
            if not (DOXX_SRC / "Cargo.toml").exists():
                return False, f"corpus path missing: {DOXX_SRC}"
            return False, ("doxx is a DOCX reader/renderer: its export surface is "
                           "markdown/text/csv/json/ansi only; it cannot write DOCX")
        except Exception as exc:
            return False, f"availability check failed: {exc}"

    def export_docx(self, markdown: str, citations: list[dict]) -> bytes:
        raise RuntimeError("doxx-export is unavailable; see available() reason")


class MdxJsRs(Candidate):
    """wooorm mdxjs-rs — MDX -> JSX/JS compiler, not a DOCX writer."""

    name = "mdxjs-rs"
    stages = {"export_docx"}

    def available(self):
        try:
            if not shutil.which("cargo"):
                return False, "cargo not on PATH"
            if not (MDXJS_SRC / "Cargo.toml").exists():
                return False, f"corpus path missing: {MDXJS_SRC}"
            return False, "mdxjs-rs compiles MDX to JSX, cannot emit DOCX"
        except Exception as exc:
            return False, f"availability check failed: {exc}"

    def export_docx(self, markdown: str, citations: list[dict]) -> bytes:
        raise RuntimeError("mdxjs-rs is unavailable; see available() reason")


class MdxRs(Candidate):
    """web-infra-dev mdx-rs — MDX -> JSX/JS compiler, not a DOCX writer."""

    name = "mdx-rs"
    stages = {"export_docx"}

    def available(self):
        try:
            if not shutil.which("cargo"):
                return False, "cargo not on PATH"
            if not (MDX_RS_SRC / "Cargo.toml").exists():
                return False, f"corpus path missing: {MDX_RS_SRC}"
            return False, "mdx-rs compiles MDX to JSX, cannot emit DOCX"
        except Exception as exc:
            return False, f"availability check failed: {exc}"

    def export_docx(self, markdown: str, citations: list[dict]) -> bytes:
        raise RuntimeError("mdx-rs is unavailable; see available() reason")


CANDIDATES = [JabrefBibtex, DoxxExport, MdxJsRs, MdxRs]
