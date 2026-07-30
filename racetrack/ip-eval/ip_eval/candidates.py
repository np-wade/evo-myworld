"""Candidates — incumbent, baselines, and corpus competitors.

Rules (bench-factory):
- every candidate has available(); missing dep => skipped and recorded, never a crash.
- pip-based candidates install into per-candidate venvs under .venv-candidates/
  via uv. A failed install is purged immediately (disk is tight) and the
  candidate is recorded unavailable with the tail of the install log.
- corpus-local pure-python modules are imported by file path, no install.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SUITE_DIR = Path(__file__).resolve().parent.parent
DRIVER = SUITE_DIR / "drivers" / "ip_driver.mjs"
IP_PROJECT = Path(os.environ.get(
    "IP_PROJECT_DIR",
    Path.home() / "coding/docker-envs/projects/information-processer",
))
REPOS = Path(os.environ.get(
    "CORPUS_REPOS",
    Path.home() / "coding/docker-envs/filing-cabinet/library-base/repos",
))
VENVS = SUITE_DIR / ".venv-candidates"
PROVISION_LOG = SUITE_DIR / "provision-report.json"

UV = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
CALL_TIMEOUT_S = 90


def _run(cmd, *, timeout=CALL_TIMEOUT_S, env=None, stdin_data: bytes | None = None):
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        cmd, capture_output=True, timeout=timeout, env=merged_env,
        input=stdin_data,
    )


# ---------------------------------------------------------------------------
# provisioning
# ---------------------------------------------------------------------------

def provision_venv(name: str, pip_packages: list[str]) -> tuple[Path | None, str]:
    """Create (or reuse) .venv-candidates/<name> and pip-install packages.

    On ANY failure the venv is deleted to reclaim disk. Returns
    (python_path_or_None, reason).
    """
    venv = VENVS / name
    python = venv / "bin" / "python"
    if python.exists():
        return python, ""
    VENVS.mkdir(exist_ok=True)
    try:
        if not Path(UV).exists() and not shutil.which("uv"):
            return None, "uv not installed on host"
        create = _run([UV, "venv", str(venv), "--python", "3.12"], timeout=300)
        if create.returncode != 0:
            raise RuntimeError(f"uv venv failed: {create.stderr.decode()[-400:]}")
        install = _run(
            [UV, "pip", "install", "--python", str(python), *pip_packages],
            timeout=900,
        )
        if install.returncode != 0:
            raise RuntimeError(f"uv pip install failed: {install.stderr.decode()[-400:]}")
        return python, ""
    except Exception as exc:
        shutil.rmtree(venv, ignore_errors=True)  # purge failed download: disk is tight
        return None, f"install failed (purged): {exc}"


def record_provision(report: dict) -> None:
    PROVISION_LOG.write_text(json.dumps(report, indent=2))


# ---------------------------------------------------------------------------
# candidate base
# ---------------------------------------------------------------------------

class Candidate:
    name = "base"
    stages: set[str] = set()

    def available(self) -> tuple[bool, str]:
        return False, "not implemented"

    # stage entry points; default = does not implement
    def extract(self, file: Path, name: str, mime: str) -> dict:
        raise NotImplementedError

    def split(self, content: str) -> list[dict]:
        raise NotImplementedError

    def concepts(self, sections: list[dict]) -> list[dict]:
        raise NotImplementedError

    def dedup(self, paragraphs: list[str]) -> list[str]:
        raise NotImplementedError

    def retrieve(self, query: str, corpus: list[str]) -> list[str]:
        """Rank corpus sentences for the query, best first."""
        raise NotImplementedError

    def graph(self, concepts: list[dict]) -> dict:
        """Build a concept graph: {"nodes": [names], "edges": [(name, name)]}."""
        raise NotImplementedError

    def tabilify(self, content: str) -> list[dict]:
        """Structured metric records: [{subject, metric, value, unit}]."""
        raise NotImplementedError

    def draft(self, sections: list[dict], concepts: list[dict],
              research: dict) -> list[str]:
        """One draft text per section, grounded in the given evidence."""
        raise NotImplementedError

    def export_docx(self, markdown: str, citations: list[dict]) -> bytes:
        raise NotImplementedError

    def export_bibtex(self, citations: list[dict]) -> str:
        raise NotImplementedError

    # --- app-level probes (P10/A10/S10/F11) -------------------------------

    def store_probe(self, action: str, payload: dict) -> dict:
        """Persistence probe: write_read|concurrent|atomicity|corrupt_read|safe_name."""
        raise NotImplementedError

    def start_api(self) -> str:
        """Start the candidate's HTTP API; return base URL."""
        raise NotImplementedError

    def stop_api(self) -> None:
        raise NotImplementedError

    def api_probe_endpoints(self) -> dict:
        """Endpoint map for generic API probes: {mutate, deep}."""
        return {}

    def security_probe(self, probe: str, payload: dict) -> dict:
        raise NotImplementedError

    def frontend_probe(self, probe: str) -> dict:
        """Returns {"pass": bool, "detail": str} for a named UI probe."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# incumbent — Information Processer via node driver
# ---------------------------------------------------------------------------

class InformationProcesser(Candidate):
    name = "ip-incumbent"
    stages = {"extract", "split", "concepts", "dedup", "retrieval",
              "graph", "drafting", "tabilify", "export_docx", "export_bibtex",
              "persistence", "api", "security"}

    def __init__(self):
        self._api_proc: subprocess.Popen | None = None
        self._api_data: Path | None = None

    def available(self) -> tuple[bool, str]:
        if not shutil.which("node"):
            return False, "node not on PATH"
        if not (IP_PROJECT / "server" / "pipeline.mjs").exists():
            return False, f"incumbent source missing at {IP_PROJECT}"
        probe = _run(["node", str(DRIVER), "split"],
                     stdin_data=json.dumps({"content": "hello world probe"}).encode())
        if probe.returncode != 0:
            return False, f"driver probe failed: {probe.stderr.decode()[-300:]}"
        return True, ""

    def _call(self, stage: str, payload: dict) -> dict:
        proc = _run(
            ["node", str(DRIVER), stage],
            stdin_data=json.dumps(payload).encode(),
            env={"IP_SERVER_DIR": str(IP_PROJECT / "server")},
        )
        try:
            out = json.loads(proc.stdout.decode())
        except Exception:
            return {"ok": False, "error": f"driver non-JSON output: {proc.stdout[:200]!r} {proc.stderr[-300:]!r}"}
        if proc.returncode != 0 and out.get("ok"):
            out = {"ok": False, "error": f"driver exit {proc.returncode}"}
        return out

    def extract(self, file: Path, name: str, mime: str) -> dict:
        return self._call("extract", {"file": str(file), "name": name, "mime": mime})

    def split(self, content: str) -> list[dict]:
        out = self._call("split", {"content": content})
        return out.get("sections", []) if out.get("ok") else []

    def concepts(self, sections: list[dict]) -> list[dict]:
        out = self._call("concepts", {"sections": sections})
        return out.get("concepts", []) if out.get("ok") else []

    def dedup(self, paragraphs: list[str]) -> list[str]:
        drafts = [{"id": "d1", "sectionId": "s1", "title": "Methods",
                   "content": "\n\n".join(paragraphs)}]
        out = self._call("combine", {"drafts": drafts})
        if not out.get("ok"):
            return paragraphs
        combined = out.get("combined", {})
        text = combined.get("content", "") if isinstance(combined, dict) else str(combined)
        return [p for p in text.split("\n\n") if p.strip()]

    def export_docx(self, markdown: str, citations: list[dict]) -> bytes:
        import base64
        out = self._call("docx", {"markdown": markdown, "citations": citations})
        if not out.get("ok"):
            raise RuntimeError(out.get("error", "docx failed"))
        return base64.b64decode(out["base64"])

    def retrieve(self, query: str, corpus: list[str]) -> list[str]:
        documents = [{"id": "fx", "title": "fixture", "content": "\n".join(corpus)}]
        out = self._call("research",
                         {"concept": {"id": "c1", "name": query}, "documents": documents})
        if not out.get("ok"):
            return []
        research = out.get("research", {})
        return [e.get("excerpt", "") for e in research.get("evidence", [])]

    def tabilify(self, content: str) -> list[dict]:
        import re as _re
        sections = self.split(content)
        concepts = self.concepts(sections)
        records = []
        for concept in concepts:
            match = _re.match(r"(\d+(?:\.\d+)?)\s*(%|ms|s|GB|MB|F1)?",
                              concept.get("metric", ""))
            if match:
                records.append({"subject": concept["name"], "metric": "",
                                "value": match.group(1),
                                "unit": match.group(2) or ""})
        return records

    def tabilify_table(self, kind: str, payload: dict) -> list[dict]:
        if kind == "documents":
            rows = []
            for file in payload["files"]:
                out = self.extract(file["path"], file["name"], file["mime"])
                rows.append({"name": file["name"],
                             "extractionQuality": out.get("extractionQuality", ""),
                             "pages": out.get("pages", 0),
                             "engine": out.get("engine", "")})
            return rows
        if kind == "sections":
            return self.split(payload["content"])
        if kind == "concepts":
            return self.concepts(payload["sections"])
        if kind == "research":
            rows = []
            for concept in payload["concepts"]:
                out = self._call("research", {"concept": concept,
                                              "documents": payload["documents"]})
                research = out.get("research", {})
                rows.append({"concept": concept["name"],
                             "status": research.get("status", ""),
                             "evidence": research.get("evidence", []),
                             "sources": research.get("sources", [])})
            return rows
        raise NotImplementedError(kind)

    def graph(self, concepts: list[dict]) -> dict:
        out = self._call("graph", {"concepts": concepts})
        if not out.get("ok"):
            return {"nodes": [], "edges": []}
        graph = out.get("graph", {})
        label_by_id = {c["id"]: c["name"] for c in concepts}
        nodes = [n.get("label", "") for n in graph.get("nodes", [])]
        edges = [
            (label_by_id.get(link.get("source"), link.get("source", "")),
             label_by_id.get(link.get("target"), link.get("target", "")))
            for link in graph.get("links", [])
        ]
        return {"nodes": nodes, "edges": edges}

    def draft(self, sections: list[dict], concepts: list[dict],
              research: dict) -> list[str]:
        out = self._call("draft", {"sections": sections, "concepts": concepts,
                                   "researchByConcept": research})
        if not out.get("ok"):
            return []
        return [d.get("content", "") for d in out.get("drafts", [])]

    def export_bibtex(self, citations: list[dict]) -> str:
        pipeline_path = (IP_PROJECT / "server" / "pipeline.mjs").as_posix()
        proc = _run(
            ["node", "--input-type=module", "-e",
             f"import {{formatBibtex}} from '{pipeline_path}';"
             "let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{"
             "process.stdout.write(formatBibtex(JSON.parse(d)))});"],
            stdin_data=json.dumps(citations).encode(),
        )
        return proc.stdout.decode() if proc.returncode == 0 else ""

    def store_probe(self, action: str, payload: dict) -> dict:
        import tempfile
        data_dir = Path(tempfile.mkdtemp(prefix=f"ip-store-{action}-"))
        try:
            proc = _run(
                ["node", str(SUITE_DIR / "drivers" / "ip_store_driver.mjs"), action],
                stdin_data=json.dumps(payload).encode(),
                env={"IP_SERVER_DIR": str(IP_PROJECT / "server"),
                     "INFORMATION_PROCESSER_DATA_DIRECTORY": str(data_dir)},
                timeout=180,
            )
            try:
                return json.loads(proc.stdout.decode())
            except Exception:
                return {"ok": False,
                        "error": f"store driver: {proc.stderr.decode()[-200:]}"}
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def start_api(self) -> str:
        import tempfile
        import urllib.request
        self._api_data = Path(tempfile.mkdtemp(prefix="ip-api-"))
        port = 8971
        self._api_proc = subprocess.Popen(
            ["node", str(IP_PROJECT / "server" / "index.mjs")],
            env={**os.environ, "INFORMATION_PROCESSER_PORT": str(port),
                 "INFORMATION_PROCESSER_DATA_DIRECTORY": str(self._api_data)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                return base
            except Exception:
                time.sleep(0.2)
        self.stop_api()
        raise RuntimeError("incumbent API did not come up on 8971")

    def stop_api(self) -> None:
        if self._api_proc:
            self._api_proc.terminate()
            try:
                self._api_proc.wait(timeout=5)
            except Exception:
                self._api_proc.kill()
            self._api_proc = None
        if self._api_data:
            shutil.rmtree(self._api_data, ignore_errors=True)
            self._api_data = None

    def api_probe_endpoints(self) -> dict:
        return {"mutate": "/api/documents/text", "deep": "/stage8-export"}

    def security_probe(self, probe: str, payload: dict) -> dict:
        if probe == "safe_name":
            return self.store_probe("safe_name", payload)
        if probe == "injection_extract":
            doc = payload["document"]
            extract = self.extract(doc, doc.name, "text/markdown")
            if not extract.get("ok"):
                return {"ok": False, "error": extract.get("error", "extract failed")}
            sections = self.split(extract.get("content", ""))
            concepts = self.concepts(sections)
            return {"ok": True, "content": extract.get("content", ""),
                    "concepts": concepts}
        if probe == "dep_audit":
            proc = subprocess.run(["npm", "audit", "--json"], capture_output=True,
                                  timeout=300, cwd=IP_PROJECT)
            return {"ok": True, "raw": proc.stdout.decode(),
                    "exit": proc.returncode}
        return {"ok": False, "error": f"unknown probe {probe}"}

class NaiveBaseline(Candidate):
    name = "naive-baseline"
    stages = {"extract", "split", "concepts", "dedup", "retrieval",
              "graph", "drafting", "tabilify", "persistence"}

    def available(self):
        return True, ""

    def extract(self, file: Path, name: str, mime: str) -> dict:
        data = file.read_bytes()
        if not data:
            return {"ok": False, "error": "empty file"}
        if data.startswith(b"%PDF") or data.startswith(b"PK"):
            return {"ok": False, "error": "binary format unsupported by naive baseline"}
        return {"ok": True, "content": data.decode("utf-8", "replace"),
                    "extractionQuality": "native-text", "engine": "naive-decode"}

    def split(self, content: str) -> list[dict]:
        import re as _re
        sections, current, title = [], [], "Document"
        for line in content.splitlines():
            m = _re.match(r"^#{1,6}\s+(.+)$", line.strip())
            if m:
                if current:
                    sections.append({"title": title, "content": "\n".join(current)})
                title, current = m.group(1), []
            else:
                current.append(line)
        if current:
            sections.append({"title": title, "content": "\n".join(current)})
        return sections

    def concepts(self, sections: list[dict]) -> list[dict]:
        import re as _re
        found = {}
        for section in sections:
            for m in _re.finditer(
                    r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){1,3}\b",
                    section.get("content", "")):
                found.setdefault(m.group(0), 0)
                found[m.group(0)] += 1
        return [{"name": k, "type": "Concept", "mentions": v} for k, v in found.items()]

    def dedup(self, paragraphs: list[str]) -> list[str]:
        seen, out = set(), []
        for p in paragraphs:
            key = " ".join(p.lower().split())
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out

    def retrieve(self, query: str, corpus: list[str]) -> list[str]:
        terms = {t.lower() for t in query.split() if len(t) > 2}
        scored = sorted(
            corpus,
            key=lambda s: -sum(1 for t in terms if t in s.lower()),
        )
        return [s for s in scored if any(t in s.lower() for t in terms)]

    def tabilify(self, content: str) -> list[dict]:
        import re as _re
        records = []
        for sentence in _re.split(r"(?<=[.!?])\s+", content):
            for match in _re.finditer(r"(\d+(?:\.\d+)?)\s*(%|ms|GB|MB|s)\b", sentence):
                names = _re.findall(r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\b",
                                    sentence[:match.start()])
                records.append({"subject": names[-1] if names else "",
                                "metric": "", "value": match.group(1),
                                "unit": match.group(2)})
        return records

    def tabilify_table(self, kind: str, payload: dict) -> list[dict]:
        import re as _re
        if kind == "documents":
            rows = []
            for file in payload["files"]:
                out = self.extract(file["path"], file["name"], file["mime"])
                rows.append({"name": file["name"],
                             "extractionQuality": out.get("extractionQuality", ""),
                             "pages": 1, "engine": "naive-decode"})
            return rows
        if kind == "sections":
            return self.split(payload["content"])
        if kind == "concepts":
            return self.concepts(payload["sections"])
        if kind == "research":
            rows = []
            corpus = payload["documents"][0]["content"]
            sentences = [s.strip() for s in _re.split(r"(?<=[.!?])\s+", corpus) if s.strip()]
            for concept in payload["concepts"]:
                hits = [s for s in sentences
                        if concept["name"].lower() in s.lower()]
                status = ("supported" if len(hits) >= 2
                          else "limited-evidence" if hits else "unverified")
                rows.append({"concept": concept["name"], "status": status,
                             "evidence": [{"excerpt": h} for h in hits[:5]],
                             "sources": []})
            return rows
        raise NotImplementedError(kind)

    def graph(self, concepts: list[dict]) -> dict:
        nodes = [c["name"] for c in concepts]
        edges = []
        for i, left in enumerate(concepts):
            for right in concepts[i + 1:]:
                if set(left.get("sectionIds", [])) & set(right.get("sectionIds", [])):
                    edges.append((left["name"], right["name"]))
        return {"nodes": nodes, "edges": edges}

    def draft(self, sections: list[dict], concepts: list[dict],
              research: dict) -> list[str]:
        import re as _re
        drafts = []
        for section in sections:
            sentences = _re.split(r"(?<=[.!?])\s+", section.get("content", ""))
            body = " ".join(s.strip() for s in sentences[:2] if s.strip())
            drafts.append(f"## {section.get('title', 'Section')}\n\n{body}")
        return drafts

    def store_probe(self, action: str, payload: dict) -> dict:
        """Naive non-atomic JSON file store — the cautionary floor."""
        import tempfile
        import threading
        data_dir = Path(tempfile.mkdtemp(prefix=f"naive-store-{action}-"))
        db = data_dir / "store.json"
        try:
            if action == "write_read":
                n = payload.get("n", 50)
                timings = []
                for i in range(n):
                    started = time.monotonic()
                    db.write_text(json.dumps({"documents": [
                        {"id": f"doc-{i}-{j}"} for j in range(payload.get("docsPerWrite", 40))]}))
                    timings.append((time.monotonic() - started) * 1000)
                timings.sort()
                return {"ok": True, "p50_ms": timings[len(timings) // 2],
                        "p95_ms": timings[int(len(timings) * 0.95)],
                        "documents": payload.get("docsPerWrite", 40)}
            if action == "concurrent":
                writers = payload.get("writers", ["A", "B"])
                ops = payload.get("ops", 20)
                db.write_text(json.dumps({"documents": []}))

                def worker(tag):
                    for i in range(ops):
                        try:
                            state = json.loads(db.read_text())
                            state["documents"].append({"id": f"doc-{tag}-{i}"})
                            db.write_text(json.dumps(state))  # read-modify-write race
                        except Exception:
                            errors.append(f"{tag}-{i}")  # torn read mid-race
                errors: list[str] = []
                threads = [threading.Thread(target=worker, args=(t,)) for t in writers]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                final = json.loads(db.read_text())["documents"]
                expected = len(writers) * ops
                return {"ok": True, "expected": expected,
                        "surviving": len(final), "lost": expected - len(final)}
            if action == "atomicity":
                writes = payload.get("writes", 150)
                torn = 0
                stopped = False

                def reader():
                    nonlocal torn
                    while not stopped:
                        try:
                            json.loads(db.read_text())
                        except Exception:
                            torn += 1
                db.write_text("{}")
                thread = threading.Thread(target=reader)
                thread.start()
                for i in range(writes):
                    db.write_text(json.dumps({"documents": [{"id": f"d{i}"}] * 5}))
                stopped = True
                thread.join()
                return {"ok": True, "torn_reads": torn, "writes": writes}
            if action == "corrupt_read":
                db.write_text('{"version": 1, "documents": [TRUNCATED')
                try:
                    json.loads(db.read_text())
                    return {"ok": True, "behavior": "recovered-default"}
                except Exception as exc:
                    return {"ok": True, "behavior": f"threw:{type(exc).__name__}"}
            return {"ok": False, "error": f"unknown action {action}"}
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# corpus competitors — modules loaded straight from corpus checkouts
# ---------------------------------------------------------------------------

class Last30DaysDedup(Candidate):
    """mvanhorn_last30days-skill: within-source near-dup detection (pure py)."""
    name = "last30days-dedupe"
    stages = {"dedup"}
    LIB_PARENT = "mvanhorn_last30days-skill/code/skills/last30days/scripts"

    def _load(self):
        parent = REPOS / self.LIB_PARENT
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        from lib import dedupe, schema  # noqa: PLC0415
        return dedupe, schema

    def available(self):
        if not (REPOS / self.LIB_PARENT / "lib" / "dedupe.py").exists():
            return False, f"corpus path missing: {self.LIB_PARENT}/lib/dedupe.py"
        try:
            self._load()
        except Exception as exc:
            return False, f"import failed: {exc}"
        return True, ""

    def dedup(self, paragraphs: list[str]) -> list[str]:
        dedupe, schema = self._load()
        items = [
            schema.SourceItem(item_id=f"i{i}", source="web", title=p[:80],
                              body=p, url=f"mem://{i}")
            for i, p in enumerate(paragraphs)
        ]
        kept = dedupe.dedupe_items(items, threshold=0.7)
        return [item.body for item in kept]


class GraphifyDedup(Candidate):
    """Graphify-Labs_graphify: MinHash/LSH + Jaro-Winkler entity dedup.

    Needs rapidfuzz, so it runs in a small venv via subprocess.
    """
    name = "graphify-dedup"
    stages = {"dedup"}
    PKG = "Graphify-Labs_graphify/code"

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        if not (REPOS / self.PKG / "graphify" / "dedup.py").exists():
            return False, f"corpus path missing: {self.PKG}/graphify/dedup.py"
        self._python, reason = provision_venv("graphify", ["rapidfuzz", "numpy"])
        return (self._python is not None), reason

    def dedup(self, paragraphs: list[str]) -> list[str]:
        script = (
            "import sys, json\n"
            f"sys.path.insert(0, {str(REPOS / self.PKG)!r})\n"
            "from graphify.dedup import deduplicate_entities\n"
            "paras = json.load(sys.stdin)\n"
            "nodes = [{'id': f'n{i}', 'label': p} for i, p in enumerate(paras)]\n"
            "kept, _ = deduplicate_entities(\n"
            "    nodes, [], communities={n['id']: 0 for n in nodes})\n"
            "print(json.dumps([n['label'] for n in kept]))\n"
        )
        proc = _run([str(self._python), "-c", script],
                    stdin_data=json.dumps(paragraphs).encode())
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-300:])
        # library warnings may precede the JSON payload on stdout
        last_line = [l for l in proc.stdout.decode().splitlines() if l.strip()][-1]
        return json.loads(last_line)


# ---------------------------------------------------------------------------
# pip-provisioned competitors
# ---------------------------------------------------------------------------

class Docx2Python(Candidate):
    name = "docx2python"
    stages = {"extract"}

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        self._python, reason = provision_venv("docx2python", ["docx2python"])
        return (self._python is not None), reason

    def extract(self, file: Path, name: str, mime: str) -> dict:
        if not name.lower().endswith(".docx"):
            return {"ok": False, "error": "docx2python handles docx only"}
        proc = _run(
            [str(self._python), "-c",
             "import sys, docx2python; r = docx2python.docx2python(sys.argv[1]);"
             "print(r.text)", str(file)],
        )
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr.decode()[-300:]}
        return {"ok": True, "content": proc.stdout.decode(),
                "extractionQuality": "native-text", "engine": "docx2python"}


class PythonDocx(Candidate):
    name = "python-docx"
    stages = {"export_docx"}

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        self._python, reason = provision_venv("python-docx", ["python-docx"])
        return (self._python is not None), reason

    def export_docx(self, markdown: str, citations: list[dict]) -> bytes:
        script = (
            "import sys, json, re, io, base64\n"
            "from docx import Document\n"
            "req = json.load(sys.stdin)\n"
            "doc = Document()\n"
            "for line in req['markdown'].splitlines():\n"
            "    m = re.match(r'^(#{1,6})\\s+(.*)$', line)\n"
            "    if m: doc.add_heading(m.group(2), level=min(len(m.group(1)),4))\n"
            "    elif line.strip(): doc.add_paragraph(line)\n"
            "for c in req['citations']:\n"
            "    doc.add_paragraph(str(c.get('key','')) + ' ' + str(c.get('title','')))\n"
            "buf = io.BytesIO(); doc.save(buf)\n"
            "sys.stdout.write(base64.b64encode(buf.getvalue()).decode())\n"
        )
        proc = _run([str(self._python), "-c", script],
                    stdin_data=json.dumps({"markdown": markdown, "citations": citations}).encode())
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-300:])
        import base64
        return base64.b64decode(proc.stdout.decode())


class Haystack(Candidate):
    name = "haystack-splitter"
    stages = {"split"}

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        self._python, reason = provision_venv("haystack", ["haystack-ai"])
        return (self._python is not None), reason

    def split(self, content: str) -> list[dict]:
        script = (
            "import sys, json\n"
            "from haystack import Document\n"
            "from haystack.components.preprocessors import DocumentSplitter\n"
            "content = sys.stdin.read()\n"
            "splitter = DocumentSplitter(split_by='word', split_length=450, split_overlap=40)\n"
            "docs = splitter.run(documents=[Document(content=content)])['documents']\n"
            "print(json.dumps([{'title': '', 'content': d.content} for d in docs]))\n"
        )
        proc = _run([str(self._python), "-c", script],
                    stdin_data=content.encode(), timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-300:])
        return json.loads(proc.stdout.decode())


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

def all_candidates() -> list[Candidate]:
    core = [
        InformationProcesser(),
        NaiveBaseline(),
        Docx2Python(),
        Haystack(),
        PythonDocx(),
        Last30DaysDedup(),
        GraphifyDedup(),
    ]
    # plugin discovery: ip_eval/candidates_extra/*.py each expose CANDIDATES,
    # a list of Candidate subclasses. Lets race families land without
    # touching this file.
    extra: list[Candidate] = []
    pkg_dir = Path(__file__).resolve().parent / "candidates_extra"
    if pkg_dir.is_dir():
        import importlib
        for file in sorted(pkg_dir.glob("*.py")):
            if file.name.startswith("_"):
                continue
            try:
                module = importlib.import_module(f".candidates_extra.{file.stem}",
                                                 package="ip_eval")
                extra.extend(cls() for cls in getattr(module, "CANDIDATES", []))
            except Exception as exc:
                print(f"[candidates_extra] {file.name} failed to load: {exc}",
                      file=sys.stderr)
    return core + extra


def candidates_for(stage: str) -> tuple[list[Candidate], list[dict]]:
    """(available candidates for stage, unavailable records)."""
    ready, unavailable = [], []
    provision_report = {}
    for cand in all_candidates():
        if stage not in cand.stages:
            continue
        started = time.monotonic()
        try:
            ok, reason = cand.available()
        except Exception as exc:  # available() itself must never crash a race
            ok, reason = False, f"available() raised: {exc}"
        provision_report[cand.name] = {
            "available": ok, "reason": reason,
            "provision_s": round(time.monotonic() - started, 2),
        }
        if ok:
            ready.append(cand)
        else:
            unavailable.append({"candidate": cand.name, "reason": reason})
    record_provision(provision_report)
    return ready, unavailable
