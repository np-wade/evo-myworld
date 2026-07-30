"""OCR extraction family plugin (pack 01).

Candidates (stage: extract):
- olmocr: allenai_olmocr (corpus code/olmocr/pipeline.py). Gated on local HF
  model weights + a GPU; the multi-GB weight download is never attempted on
  this box, so it is honestly unavailable here.
- stirling-pdf: Stirling-Tools_Stirling-PDF (Java Spring server,
  corpus code/app/core/.../controller/api/). Server-class: refuses via
  available() unless the docker lane is enabled and java exists.
- tesseract-cli: tesseract-ocr_tesseract (corpus code/src/api/baseapi.cpp).
  Drives the system tesseract binary over page images; PDF input is rasterized
  via pdftoppm/gs when present, otherwise honestly refused.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate, _run, provision_venv  # noqa: E402


def _sniff(file: Path, nbytes: int = 2048) -> bytes:
    try:
        with file.open("rb") as fh:
            return fh.read(nbytes)
    except OSError:
        return b""


def _looks_like_image(head: bytes) -> bool:
    return (
        head.startswith(b"\x89PNG\r\n\x1a\n")
        or head.startswith(b"\xff\xd8\xff")
        or head.startswith((b"II*\x00", b"MM\x00*"))
        or head.startswith(b"BM")
        or head.startswith(b"GIF8")
    )


# ---------------------------------------------------------------------------
# olmocr (allenai_olmocr) — gated on local model weights, never downloaded here
# ---------------------------------------------------------------------------

class OlmOcr(Candidate):
    name = "olmocr"
    stages = {"extract"}
    VENV = "olmocr"

    def __init__(self):
        self._python: Path | None = None

    @staticmethod
    def _find_weights() -> Path | None:
        cache = Path.home() / ".cache" / "huggingface" / "hub"
        if not cache.is_dir():
            return None
        for entry in cache.glob("models--allenai--olmOCR*"):
            if any(entry.rglob("*.safetensors")) or any(entry.rglob("*.bin")):
                return entry
        return None

    def available(self):
        try:
            if self._find_weights() is None:
                # No venv is created on this path, so there is no partial venv
                # to purge; the multi-GB HF weight download is not attempted.
                return False, ("olmocr model weights not downloadable on this box "
                               "(multi-GB HF download disabled; disk is tight)")
            if not shutil.which("nvidia-smi"):
                return False, "olmocr needs a GPU for vllm inference; nvidia-smi not on PATH"
            self._python, reason = provision_venv(self.VENV, ["olmocr"])
            if self._python is None:
                return False, reason  # provision_venv already purged on failure
            return True, ""
        except Exception as exc:  # available() must never raise
            return False, f"available() check failed: {exc}"

    def extract(self, file: Path, name: str, mime: str) -> dict:
        head = _sniff(file)
        if not head:
            return {"ok": False, "error": "empty file"}
        # available() gates real runs; if we ever get here the serving stack
        # (vllm + model weights) is still not started by this adapter.
        return {"ok": False,
                "error": "olmocr requires a running vllm model server; this adapter does not start one"}


# ---------------------------------------------------------------------------
# stirling-pdf (Java Spring server) — server-class, honestly refused
# ---------------------------------------------------------------------------

class StirlingPdf(Candidate):
    name = "stirling-pdf"
    stages = {"extract"}

    def available(self):
        try:
            if not shutil.which("java"):
                return False, "java not on PATH"
            if os.environ.get("RACETRACK_DOCKER") != "1":
                return False, "needs docker lane (set RACETRACK_DOCKER=1 for server-class candidates)"
            return False, "stirling-pdf server provisioning not implemented by this adapter"
        except Exception as exc:  # available() must never raise
            return False, f"available() check failed: {exc}"

    def extract(self, file: Path, name: str, mime: str) -> dict:
        head = _sniff(file)
        if not head:
            return {"ok": False, "error": "empty file"}
        return {"ok": False,
                "error": "stirling-pdf requires a reachable server; none is running"}


# ---------------------------------------------------------------------------
# tesseract-cli — system binary over page images; PDF via rasterizer only
# ---------------------------------------------------------------------------

class TesseractCli(Candidate):
    name = "tesseract-cli"
    stages = {"extract"}
    CALL_TIMEOUT_S = 180  # OCR subprocesses are slow; timeout -> honest error
    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif")

    def __init__(self):
        self._bin: str | None = None

    def available(self):
        try:
            self._bin = shutil.which("tesseract")
            if not self._bin:
                return False, "tesseract binary not on PATH"
            return True, ""
        except Exception as exc:  # available() must never raise
            return False, f"available() check failed: {exc}"

    def _ocr_image(self, image: Path) -> dict:
        try:
            proc = _run([self._bin, str(image), "stdout"],
                        timeout=self.CALL_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return {"ok": False,
                    "error": f"tesseract timed out after {self.CALL_TIMEOUT_S}s"}
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr.decode()[-300:]}
        return {"ok": True, "content": proc.stdout.decode(errors="replace"),
                "extractionQuality": "ocr-layout", "engine": "tesseract-cli"}

    def _extract_pdf(self, file: Path) -> dict:
        pdftoppm = shutil.which("pdftoppm")
        gs = shutil.which("gs")
        if not pdftoppm and not gs:
            return {"ok": False,
                    "error": "tesseract cannot read PDF directly and no rasterizer (pdftoppm/gs) on PATH"}
        with tempfile.TemporaryDirectory(prefix="tesseract-pdf-") as outdir:
            prefix = str(Path(outdir) / "page")
            if pdftoppm:
                cmd = [pdftoppm, "-r", "200", "-png", str(file), prefix]
            else:
                cmd = [gs, "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m", "-r200",
                       f"-sOutputFile={prefix}-%d.png", str(file)]
            try:
                proc = _run(cmd, timeout=self.CALL_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                return {"ok": False,
                        "error": f"pdf rasterize timed out after {self.CALL_TIMEOUT_S}s"}
            if proc.returncode != 0:
                return {"ok": False,
                        "error": f"pdf rasterize failed: {proc.stderr.decode()[-300:]}"}
            pages = sorted(Path(outdir).glob("page-*.png"))
            if not pages:
                return {"ok": False, "error": "rasterizer produced no page images"}
            texts = []
            for page in pages:
                result = self._ocr_image(page)
                if not result["ok"]:
                    return result
                texts.append(result["content"])
            return {"ok": True, "content": "\n\n".join(texts),
                    "extractionQuality": "ocr-layout", "engine": "tesseract-cli"}

    def extract(self, file: Path, name: str, mime: str) -> dict:
        head = _sniff(file)
        if not head:
            return {"ok": False, "error": "empty file"}
        if head.startswith(b"%PDF"):
            return self._extract_pdf(file)
        if name.lower().endswith(self.IMAGE_EXTS) or _looks_like_image(head):
            return self._ocr_image(file)
        return {"ok": False,
                "error": f"tesseract handles page images (and rasterized PDF) only: {name}"}


CANDIDATES = [OlmOcr, StirlingPdf, TesseractCli]
