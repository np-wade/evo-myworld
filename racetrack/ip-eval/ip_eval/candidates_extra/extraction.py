"""Extraction family plugin.

Candidates:
- pandoc-pypandoc: pandoc via the pypandoc-binary pip package (venv subprocess).
  Reads docx/html/md/txt; PDF is honestly refused (pandoc cannot read PDF).
- mineru: opendatalab MinerU via magic-pdf[full] (venv subprocess, 300s/call).
- undoc: iyulab_undoc corpus repo (Rust). The bundled CLI drags in
  self_update -> openssl-sys, which does not build on this host, so we compile
  a thin shim binary against the pure-Rust library in a /tmp copy and wire
  that. docx/xlsx/pptx only.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..candidates import REPOS, VENVS, Candidate, _run, provision_venv


def _sniff(file: Path, nbytes: int = 2048) -> bytes:
    try:
        with file.open("rb") as fh:
            return fh.read(nbytes)
    except OSError:
        return b""


def _looks_like_html(head: bytes) -> bool:
    low = head.lower()
    return low.lstrip().startswith(b"<") and (b"<html" in low or b"<!doctype html" in low)


# ---------------------------------------------------------------------------
# pandoc via pypandoc-binary
# ---------------------------------------------------------------------------

class PandocPypandoc(Candidate):
    name = "pandoc-pypandoc"
    stages = {"extract"}
    VENV = "pandoc"

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        self._python, reason = provision_venv(self.VENV, ["pypandoc-binary"])
        return (self._python is not None), reason

    def extract(self, file: Path, name: str, mime: str) -> dict:
        head = _sniff(file)
        if not head:
            return {"ok": False, "error": "empty file"}
        if head.startswith(b"%PDF"):
            return {"ok": False, "error": "pandoc cannot read PDF input"}
        lower = name.lower()
        if lower.endswith(".docx"):
            fmt = "docx"
        elif lower.endswith((".html", ".htm")) or _looks_like_html(head):
            fmt = "html"
        elif lower.endswith((".md", ".markdown", ".txt")):
            # already plain text/markdown: pass through natively, pandoc would
            # only re-wrap it
            return {"ok": True, "content": file.read_bytes().decode("utf-8", "replace"),
                    "extractionQuality": "native-text", "engine": "pandoc-passthrough"}
        else:
            return {"ok": False, "error": f"unsupported format for pandoc: {name}"}
        try:
            proc = _run(
                [str(self._python), "-c",
                 "import sys, pypandoc\n"
                 "sys.stdout.write(pypandoc.convert_file(sys.argv[1], 'plain', format=sys.argv[2]))\n",
                 str(file), fmt],
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "pandoc subprocess timed out"}
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr.decode()[-300:]}
        return {"ok": True, "content": proc.stdout.decode(),
                "extractionQuality": "native-text", "engine": f"pandoc-{fmt}"}


# ---------------------------------------------------------------------------
# MinerU (magic-pdf[full])
# ---------------------------------------------------------------------------

class MinerU(Candidate):
    name = "mineru"
    stages = {"extract"}
    VENV = "mineru"
    CALL_TIMEOUT_S = 300  # model download + layout inference are heavy

    def __init__(self):
        self._python: Path | None = None
        self._cli: Path | None = None

    def available(self):
        self._python, reason = provision_venv(self.VENV, ["magic-pdf[full]"])
        if self._python is None:
            return False, reason
        cli = self._python.parent / "magic-pdf"
        if not cli.exists():
            return False, "magic-pdf CLI missing after install"
        self._cli = cli
        return True, ""

    def extract(self, file: Path, name: str, mime: str) -> dict:
        # magic-pdf 0.6.1 CLI: `magic-pdf pdf --pdf <file> --method ...`;
        # it reads config from ~/magic-pdf.json, so HOME is redirected to a
        # temp dir carrying one (the real home is never touched).
        if not name.lower().endswith((".pdf", ".docx")):
            return {"ok": False, "error": "magic-pdf handles pdf/docx only"}
        with tempfile.TemporaryDirectory(prefix="mineru-out-") as outdir:
            home = Path(outdir) / "home"
            home.mkdir()
            (home / "magic-pdf.json").write_text(json.dumps({
                "temp-output-dir": str(Path(outdir) / "out"),
                "models-dir": str(Path(outdir) / "models"),
                "device-mode": "cpu",
            }))
            try:
                proc = _run([str(self._cli), "pdf", "--pdf", str(file),
                             "--method", "auto"],
                            timeout=self.CALL_TIMEOUT_S,
                            env={"HOME": str(home)})
            except subprocess.TimeoutExpired:
                return {"ok": False,
                        "error": f"magic-pdf timed out after {self.CALL_TIMEOUT_S}s"}
            if proc.returncode != 0:
                return {"ok": False, "error": proc.stderr.decode()[-300:]}
            mds = sorted(Path(outdir).rglob("*.md"))
            if not mds:
                return {"ok": False, "error": "magic-pdf produced no markdown output"}
            return {"ok": True, "content": mds[0].read_text(errors="replace"),
                    "extractionQuality": "ocr-layout", "engine": "magic-pdf"}


# ---------------------------------------------------------------------------
# undoc (iyulab_undoc, Rust, built from corpus copy under /tmp)
# ---------------------------------------------------------------------------

UNDOC_SRC = REPOS / "iyulab_undoc" / "code"
UNDOC_BIN = VENVS / "undoc" / "bin" / "undoc-extract"
UNDOC_BUILD_TIMEOUT_S = 600

_SHIM_CARGO_TOML = """\
[package]
name = "undoc-extract"
version = "0.1.0"
edition = "2021"

[dependencies]
undoc = { path = "__UNDOC_SRC__" }

[profile.release]
lto = false
codegen-units = 4
"""

_SHIM_MAIN_RS = """\
// Thin extraction front-end over the undoc library. The bundled CLI pulls
// self_update -> openssl-sys, which cannot build on this host; the library
// itself is pure Rust, so we wire it directly.
use std::env;

fn main() {
    let path = match env::args().nth(1) {
        Some(p) => p,
        None => {
            eprintln!("usage: undoc-extract <file>");
            std::process::exit(2);
        }
    };
    let doc = match undoc::parse_file(&path) {
        Ok(d) => d,
        Err(e) => {
            eprintln!("parse error: {e}");
            std::process::exit(1);
        }
    };
    let heading_config =
        undoc::render::HeadingConfig::default().with_default_style_mapping();
    let options = undoc::render::RenderOptions::new().with_heading_config(heading_config);
    match undoc::render::to_markdown(&doc, &options) {
        Ok(md) => print!("{md}"),
        Err(e) => {
            eprintln!("render error: {e}");
            std::process::exit(1);
        }
    }
}
"""


def _build_undoc() -> tuple[Path | None, str]:
    """Build the undoc shim binary in a /tmp copy; never inside the corpus."""
    if UNDOC_BIN.exists():
        return UNDOC_BIN, ""
    if not shutil.which("cargo"):
        return None, "cargo not on PATH"
    if not (UNDOC_SRC / "Cargo.toml").exists():
        return None, f"corpus path missing: {UNDOC_SRC}"
    tmp = Path(tempfile.mkdtemp(prefix="undoc-build-"))
    try:
        src_copy = tmp / "src"
        shutil.copytree(UNDOC_SRC, src_copy,
                        ignore=shutil.ignore_patterns("target"))
        shim = tmp / "shim"
        (shim / "src").mkdir(parents=True)
        (shim / "Cargo.toml").write_text(
            _SHIM_CARGO_TOML.replace("__UNDOC_SRC__", src_copy.as_posix()))
        (shim / "src" / "main.rs").write_text(_SHIM_MAIN_RS)
        try:
            proc = _run(
                ["cargo", "build", "--release",
                 "--manifest-path", str(shim / "Cargo.toml")],
                timeout=UNDOC_BUILD_TIMEOUT_S,
                env={"CARGO_TARGET_DIR": str(tmp / "target")},
            )
        except subprocess.TimeoutExpired:
            return None, f"cargo build timed out after {UNDOC_BUILD_TIMEOUT_S}s"
        binary = tmp / "target" / "release" / "undoc-extract"
        if proc.returncode != 0 or not binary.exists():
            return None, f"cargo build failed: {proc.stderr.decode()[-300:]}"
        UNDOC_BIN.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, UNDOC_BIN)
        return UNDOC_BIN, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # /tmp build dir always deleted


class Undoc(Candidate):
    name = "undoc"
    stages = {"extract"}

    def __init__(self):
        self._bin: Path | None = None

    def available(self):
        self._bin, reason = _build_undoc()
        return (self._bin is not None), reason

    def extract(self, file: Path, name: str, mime: str) -> dict:
        head = _sniff(file)
        if not head:
            return {"ok": False, "error": "empty file"}
        if not name.lower().endswith((".docx", ".xlsx", ".pptx")):
            return {"ok": False,
                    "error": "undoc handles Office documents (docx/xlsx/pptx) only"}
        try:
            proc = _run([str(self._bin), str(file)])
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "undoc subprocess timed out"}
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr.decode()[-300:]}
        return {"ok": True, "content": proc.stdout.decode(),
                "extractionQuality": "native-text", "engine": "undoc"}


CANDIDATES = [PandocPypandoc, MinerU, Undoc]
