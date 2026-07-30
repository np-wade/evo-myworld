"""export family — export_docx stage candidates.

- pandoc-docx: pypandoc-binary converts markdown + references to .docx bytes.
- docxtpl-minimal: docxtpl renders the body into a minimal python-docx template.
Both run in per-candidate venvs via provision_venv; a failed install is
purged by provision_venv itself and the candidate records unavailable.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from ..candidates import Candidate, _run, provision_venv


def _full_markdown(markdown: str, citations: list[dict]) -> str:
    refs = ["\n\n# References\n"]
    for c in citations:
        authors = c.get("authors") or []
        author = authors[0] if isinstance(authors, list) and authors else str(authors)
        refs.append(f"- {c.get('citeKey', '')} {author} ({c.get('year', '')}). "
                    f"{c.get('title', '')}.")
    return markdown + "\n".join(refs)


class PandocDocx(Candidate):
    name = "pandoc-docx"
    stages = {"export_docx"}

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        self._python, reason = provision_venv("pandoc", ["pypandoc-binary"])
        return (self._python is not None), reason

    def export_docx(self, markdown: str, citations: list[dict]) -> bytes:
        script = (
            "import sys, json, base64, tempfile, os\n"
            "import pypandoc\n"
            "md = json.load(sys.stdin)['markdown']\n"
            "fd, out = tempfile.mkstemp(suffix='.docx')\n"
            "os.close(fd)\n"
            "try:\n"
            "    pypandoc.convert_text(md, 'docx', format='md', outputfile=out)\n"
            "    data = open(out, 'rb').read()\n"
            "finally:\n"
            "    os.unlink(out)\n"
            "sys.stdout.write(base64.b64encode(data).decode())\n"
        )
        payload = json.dumps({"markdown": _full_markdown(markdown, citations)}).encode()
        proc = _run([str(self._python), "-c", script], stdin_data=payload, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-300:])
        return base64.b64decode(proc.stdout.decode())


class DocxtplMinimal(Candidate):
    """docxtpl against a minimal python-docx template with a {{body}} slot."""
    name = "docxtpl-minimal"
    stages = {"export_docx"}

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        self._python, reason = provision_venv("docxtpl", ["docxtpl"])
        return (self._python is not None), reason

    def export_docx(self, markdown: str, citations: list[dict]) -> bytes:
        script = (
            "import sys, json, base64, tempfile, os, re\n"
            "from docx import Document\n"
            "from docxtpl import DocxTemplate\n"
            "md = json.load(sys.stdin)['markdown']\n"
            "# minimal template: one heading + one {{body}} paragraph\n"
            "fd, tpl = tempfile.mkstemp(suffix='.docx')\n"
            "os.close(fd)\n"
            "doc = Document()\n"
            "doc.add_heading('Export', level=1)\n"
            "doc.add_paragraph('{{body}}')\n"
            "doc.save(tpl)\n"
            "body_lines = []\n"
            "for line in md.splitlines():\n"
            "    m = re.match(r'^(#{1,6})\\s+(.*)$', line)\n"
            "    body_lines.append(m.group(2) if m else line)\n"
            "out = None\n"
            "try:\n"
            "    t = DocxTemplate(tpl)\n"
            "    t.render({'body': '\\n'.join(body_lines)})\n"
            "    fd, out = tempfile.mkstemp(suffix='.docx')\n"
            "    os.close(fd)\n"
            "    t.save(out)\n"
            "    data = open(out, 'rb').read()\n"
            "finally:\n"
            "    os.unlink(tpl)\n"
            "    if out and os.path.exists(out): os.unlink(out)\n"
            "sys.stdout.write(base64.b64encode(data).decode())\n"
        )
        payload = json.dumps({"markdown": _full_markdown(markdown, citations)}).encode()
        proc = _run([str(self._python), "-c", script], stdin_data=payload, timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-300:])
        return base64.b64decode(proc.stdout.decode())


CANDIDATES = [PandocDocx, DocxtplMinimal]
