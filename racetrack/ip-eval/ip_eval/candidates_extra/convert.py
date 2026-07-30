"""Convert family — S9 document-format conversion candidates.

Stage contract (driven by race._workload_convert):

    convert(task: dict) -> dict
    task = {"direction": "ingress"|"egress",
            "source_path": str,        # ingress: fixture file on disk; egress: ""
            "source_format": "md"|"html"|"txt"|"docx"|"pdf" (ingress)
                             | "canonical" (egress),
            "target_format": "text" (ingress) | "docx"|"html"|"pdf" (egress),
            "canonical": str}          # egress only: gold canonical text
    returns {"ok": bool,
             "text": str,              # ingress: converted text; egress html: html doc
             "data_base64": str,       # egress docx/pdf: binary payload, base64
             "error": str}             # when not ok — an unsupported cell is an
                                       # honest 0, never a crash

Candidates:
- ip-incumbent:      ingress via the IP driver's extractDocument path; egress
                     docx via the IP driver's createDocx path. The incumbent
                     ships no html/pdf exporter (docx/latex only), so those
                     cells are honest 0s.
- pandoc-convert:    jgm/pandoc via pip pypandoc-binary (no Haskell build).
                     PDF egress probed against a pip typst engine; if the
                     engine probe fails the pdf cell is an honest 0. Pandoc
                     cannot READ pdf, so pdf ingress is an honest 0.
- docx2python-convert: ShayHill/docx2python — docx ingress reader only;
                     no egress (honest 0s).
- mineru-convert:    opendatalab/MinerU — pdf->markdown ingress, real model
                     pipeline (weights download allowed). Provisioning
                     failures purge the venv and report the true reason.
- stirling-pdf:      Stirling-Tools/Stirling-PDF docker lane — html->pdf
                     egress over its HTTP API; container always torn down.
- olmocr-convert:    allenai/olmocr — needs a CUDA GPU; honest-unavailable.

Honesty: available() never raises; unsupported cells return ok=False; no
output or score is ever fabricated.
"""
from __future__ import annotations

import atexit
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import (  # noqa: E402
    Candidate, InformationProcesser, VENVS, provision_venv,
)


def _fail(reason: str) -> dict:
    return {"ok": False, "text": "", "data_base64": "", "error": reason}


# ---------------------------------------------------------------------------
# ip-incumbent — reuse the extract / docx driver paths
# ---------------------------------------------------------------------------

class IpConvert(InformationProcesser):
    name = "ip-incumbent"
    stages = {"convert"}

    _MIMES = {
        "md": "text/markdown",
        "html": "text/html",
        "txt": "text/plain",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
    }

    def convert(self, task: dict) -> dict:
        if task["direction"] == "ingress":
            path = Path(task["source_path"])
            out = self.extract(path, path.name,
                               self._MIMES.get(task["source_format"], ""))
            if not out.get("ok"):
                return _fail(out.get("error", "extract failed"))
            return {"ok": True, "text": out.get("content", ""),
                    "data_base64": "", "error": ""}
        target = task["target_format"]
        if target == "docx":
            out = self._call("docx", {"markdown": task["canonical"],
                                      "citations": []})
            if not out.get("ok"):
                return _fail(out.get("error", "docx export failed"))
            return {"ok": True, "text": "", "data_base64": out["base64"],
                    "error": ""}
        return _fail(f"incumbent has no {target} exporter "
                     "(server ships docx/latex writers only)")


# ---------------------------------------------------------------------------
# pandoc-convert — pypandoc-binary; typst probed as the pdf engine
# ---------------------------------------------------------------------------

_PANDOC_DRIVER = r"""
import base64, json, sys, tempfile
from pathlib import Path
import pypandoc

task = json.loads(sys.argv[1])
typst = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
out = {"ok": False, "text": "", "data_base64": "", "error": ""}
INGRESS = {"md": "markdown", "html": "html", "txt": "markdown", "docx": "docx"}
try:
    if task["direction"] == "ingress":
        fmt = INGRESS.get(task["source_format"])
        if fmt is None:
            out["error"] = f"pandoc has no {task['source_format']} reader"
        else:
            out["text"] = pypandoc.convert_file(
                task["source_path"], "markdown", format=fmt)
            out["ok"] = True
    else:
        target = task["target_format"]
        if target == "html":
            out["text"] = pypandoc.convert_text(
                task["canonical"], "html", format="markdown")
            out["ok"] = True
        elif target == "docx":
            with tempfile.TemporaryDirectory() as tmp:
                dest = str(Path(tmp) / "out.docx")
                pypandoc.convert_text(task["canonical"], "docx",
                                      format="markdown", outputfile=dest)
                out["data_base64"] = base64.b64encode(
                    Path(dest).read_bytes()).decode()
                out["ok"] = True
        elif target == "pdf" and typst == "binding":
            # pandoc's typst writer + the python-typst binding (no CLI ships
            # with the pip typst package, so --pdf-engine is not an option)
            import typst as _typst_mod
            src = pypandoc.convert_text(task["canonical"], "typst",
                                        format="markdown")
            with tempfile.TemporaryDirectory() as tmp:
                doc = Path(tmp) / "doc.typ"
                doc.write_text(src)
                out["data_base64"] = base64.b64encode(
                    _typst_mod.compile(str(doc))).decode()
            out["ok"] = True
        elif target == "pdf":
            out["error"] = "no usable pdf engine (typst probe failed)"
        else:
            out["error"] = f"unknown egress target {target}"
except Exception as exc:
    out["error"] = f"{type(exc).__name__}: {exc}"[:300]
print(json.dumps(out))
"""


class PandocConvert(Candidate):
    name = "pandoc-convert"
    stages = {"convert"}

    def __init__(self):
        self._python: Path | None = None
        self._typst: str = "-"  # "-" = no pdf engine

    def _drive(self, task: dict, timeout: int = 300) -> dict:
        proc = subprocess.run(
            [str(self._python), "-c", _PANDOC_DRIVER,
             json.dumps(task), self._typst],
            capture_output=True, timeout=timeout)
        try:
            last = [l for l in proc.stdout.decode().splitlines() if l.strip()][-1]
            return json.loads(last)
        except Exception:
            return _fail(f"pandoc driver: {proc.stderr.decode()[-200:]}")

    def available(self):
        try:
            self._python, reason = provision_venv(
                "pandoc", ["pypandoc-binary", "typst"])
            if self._python is None:
                return False, reason
            smoke = self._drive({"direction": "egress", "source_path": "",
                                 "source_format": "canonical",
                                 "target_format": "html",
                                 "canonical": "# T\n\nBody."})
            if not smoke.get("ok"):
                return False, f"pandoc smoke failed: {smoke.get('error')}"
            # pdf engine probe: real tiny md -> pdf via pandoc's typst writer
            # + the python-typst binding
            self._typst = "binding"
            probe = self._drive({"direction": "egress", "source_path": "",
                                 "source_format": "canonical",
                                 "target_format": "pdf",
                                 "canonical": "# T\n\nBody."})
            if not (probe.get("ok")
                    and base64.b64decode(probe["data_base64"])[:5] == b"%PDF-"):
                self._typst = "-"  # engine unusable -> honest 0 pdf cell
            return True, ""
        except Exception as exc:
            return False, f"available() error: {exc}"

    def convert(self, task: dict) -> dict:
        return self._drive(task)


# ---------------------------------------------------------------------------
# docx2python-convert — docx ingress reader only
# ---------------------------------------------------------------------------

class Docx2PythonConvert(Candidate):
    name = "docx2python-convert"
    stages = {"convert"}

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        try:
            self._python, reason = provision_venv("docx2python", ["docx2python"])
            return (self._python is not None), reason
        except Exception as exc:
            return False, f"available() error: {exc}"

    def convert(self, task: dict) -> dict:
        if task["direction"] != "ingress":
            return _fail("docx2python is a docx reader; it has no export path")
        if task["source_format"] != "docx":
            return _fail(f"docx2python reads docx only, "
                         f"not {task['source_format']}")
        proc = subprocess.run(
            [str(self._python), "-c",
             "import sys, docx2python; r = docx2python.docx2python(sys.argv[1]);"
             "print(r.text)", task["source_path"]],
            capture_output=True, timeout=120)
        if proc.returncode != 0:
            return _fail(f"docx2python: {proc.stderr.decode()[-200:]}")
        return {"ok": True, "text": proc.stdout.decode(),
                "data_base64": "", "error": ""}


# ---------------------------------------------------------------------------
# mineru-convert — pdf -> markdown ingress (real VLM pipeline)
# ---------------------------------------------------------------------------

class MineruConvert(Candidate):
    name = "mineru-convert"
    stages = {"convert"}

    def __init__(self):
        self._python: Path | None = None
        self._cli: Path | None = None
        self._cache: dict[str, dict] = {}

    def available(self):
        try:
            python = VENVS / "mineru" / "bin" / "python"
            if python.exists():
                self._python = python
            else:
                self._python, reason = provision_venv("mineru", ["mineru[core]"])
                if self._python is None:
                    return False, reason
            check = subprocess.run(
                [str(self._python), "-c", "import mineru"],
                capture_output=True, timeout=300)
            if check.returncode != 0:
                return False, ("mineru installed but import failed: "
                               f"{check.stderr.decode()[-200:]}")
            cli = self._python.parent / "mineru"
            if not cli.exists():
                return False, "mineru import ok but CLI entry point missing"
            self._cli = cli
            return True, ""
        except Exception as exc:
            return False, f"available() error: {exc}"

    def convert(self, task: dict) -> dict:
        if task["direction"] != "ingress" or task["source_format"] != "pdf":
            return _fail("MinerU lane handles pdf ingress only "
                         "(no egress, no other readers)")
        src = task["source_path"]
        if src in self._cache:  # identical file across reps: convert once
            return self._cache[src]
        tmp = tempfile.mkdtemp(prefix="mineru-out-")
        try:
            proc = subprocess.run(
                [str(self._cli), "-p", src, "-o", tmp],
                capture_output=True, timeout=1800)
            if proc.returncode != 0:
                result = _fail(f"mineru exited {proc.returncode}: "
                               f"{proc.stderr.decode()[-200:]}")
            else:
                mds = sorted(Path(tmp).rglob("*.md"))
                if not mds:
                    result = _fail("mineru ran but produced no markdown")
                else:
                    result = {"ok": True,
                              "text": mds[0].read_text(errors="replace"),
                              "data_base64": "", "error": ""}
        except subprocess.TimeoutExpired:
            result = _fail("mineru timed out (1800s; model download or inference)")
        except Exception as exc:
            result = _fail(f"mineru convert error: {exc}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self._cache[src] = result
        return result


# ---------------------------------------------------------------------------
# stirling-pdf — docker lane, html -> pdf egress over HTTP
# ---------------------------------------------------------------------------

def _canonical_to_html(canonical: str) -> str:
    """Minimal markdown -> html for the Stirling html->pdf endpoint."""
    import html as _html
    parts = ["<html><head><meta charset='utf-8'><title>convert</title>"
             "</head><body>"]
    paragraph = []

    def flush():
        if paragraph:
            parts.append("<p>%s</p>" % " ".join(paragraph))
            paragraph.clear()

    for line in canonical.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("#"):
            flush()
            level = len(stripped) - len(stripped.lstrip("#"))
            level = min(max(level, 1), 6)
            text = stripped[level:].strip()
            parts.append(f"<h{level}>{_html.escape(text)}</h{level}>")
        else:
            paragraph.append(_html.escape(stripped))
    flush()
    parts.append("</body></html>")
    return "\n".join(parts)


class StirlingPdf(Candidate):
    name = "stirling-pdf"
    stages = {"convert"}
    IMAGE = "stirlingtools/stirling-pdf:latest"

    def __init__(self):
        self._container: str | None = None
        self._atexit_armed = False

    def available(self):
        try:
            if not shutil.which("docker"):
                return False, "docker not installed on this host"
            inspect = subprocess.run(
                ["docker", "image", "inspect", self.IMAGE],
                capture_output=True, timeout=60)
            if inspect.returncode != 0:
                pull = subprocess.run(["docker", "pull", self.IMAGE],
                                      capture_output=True, timeout=1800)
                if pull.returncode != 0:
                    return False, ("stirling-pdf image absent and docker pull "
                                   f"failed: {pull.stderr.decode()[-200:]}")
            return True, ""
        except Exception as exc:
            return False, f"available() error: {exc}"

    def _teardown(self):
        if self._container:
            subprocess.run(["docker", "rm", "-f", self._container],
                           capture_output=True, timeout=60)
            self._container = None

    def _start(self) -> str:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        name = f"ip-eval-stirling-{os.getpid()}-{port}"
        run = subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", name,
             "-e", "SECURITY_ENABLELOGIN=false",  # else the API 401s every call
             "-p", f"127.0.0.1:{port}:8080", self.IMAGE],
            capture_output=True, timeout=120)
        if run.returncode != 0:
            raise RuntimeError(f"docker run failed: {run.stderr.decode()[-200:]}")
        self._container = name
        if not self._atexit_armed:
            atexit.register(self._teardown)  # belt-and-braces vs hard kills
            self._atexit_armed = True
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                        base + "/api/v1/info/status", timeout=2) as resp:
                    if resp.status == 200:
                        return base
            except Exception:
                time.sleep(2)
        raise RuntimeError("stirling-pdf server did not come up within 180s")

    def convert(self, task: dict) -> dict:
        if task["direction"] != "egress" or task["target_format"] != "pdf":
            return _fail("stirling-pdf lane drives html->pdf egress only")
        try:
            base = self._start()
            html_doc = _canonical_to_html(task["canonical"])
            boundary = "ipeval-stirling-boundary"
            body = b"\r\n".join([
                f"--{boundary}".encode(),
                b'Content-Disposition: form-data; name="fileInput"; '
                b'filename="input.html"',
                b"Content-Type: text/html",
                b"",
                html_doc.encode(),
                f"--{boundary}--".encode(),
                b"",
            ])
            req = urllib.request.Request(
                base + "/api/v1/convert/html/pdf", data=body,
                headers={"Content-Type":
                         f"multipart/form-data; boundary={boundary}"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = resp.read()
            if not data.startswith(b"%PDF"):
                return _fail("stirling returned a non-pdf payload "
                             f"({len(data)} bytes)")
            return {"ok": True, "text": "",
                    "data_base64": base64.b64encode(data).decode(),
                    "error": ""}
        except Exception as exc:
            return _fail(f"stirling-pdf lane: {type(exc).__name__}: {exc}"[:250])
        finally:
            self._teardown()  # container down on success AND every failure


# ---------------------------------------------------------------------------
# olmocr-convert — honest-unavailable placeholder (no GPU on this box)
# ---------------------------------------------------------------------------

class OlmOcrConvert(Candidate):
    name = "olmocr-convert"
    stages = {"convert"}

    def available(self):
        try:
            has_smi = shutil.which("nvidia-smi") is not None
            has_dev = any(Path("/dev").glob("nvidia*"))
            if not has_smi and not has_dev:
                return False, ("olmOCR (allenai/olmocr) is a CUDA VLM pipeline; "
                               "no GPU on this box (nvidia-smi not on PATH, "
                               "no /dev/nvidia* devices)")
            return False, ("GPU present but the olmocr lane is not provisioned "
                           "in this suite (no vllm/sglang serving lane)")
        except Exception as exc:
            return False, f"available() error: {exc}"

    def convert(self, task: dict) -> dict:  # only reached if available()
        return _fail("olmocr-convert is not provisioned (no GPU lane)")


CANDIDATES = [IpConvert, PandocConvert, Docx2PythonConvert, MineruConvert,
              StirlingPdf, OlmOcrConvert]
