"""Platform-extra family — pack 09 candidates (persistence / api / security).

Persistence (corpus pointer traces; native-code stores):
- turso-store:    tursodatabase_turso  core/storage/{wal,pager}.rs — probed via
                  the pip-installable libsql binding (libsql-experimental).
- opendal-store:  apache_opendal       core/services/fs/src/{backend,writer}.rs —
                  probed via the pip `opendal` binding over its fs service.
- filecache-store: gdt050579_filecache code/filecache/src/file_cache.rs — Rust
                  crate with no Python binding; honest unavailable.
- spotcache-store: spotify_SPTPersistentCache Sources/SPTPersistentCacheFileManager.m —
                  Objective-C for Apple platforms; honest unavailable on Linux.

API:
- hayhooks-api:   deepset-ai_hayhooks code/tests/{test_pipeline_run,
                  test_run_api_streaming}.py — hayhooks server hosting one
                  minimal local echo pipeline (no LLM config).

Security (binary-gated via shutil.which; corpus: aquasecurity_trivy
code/pkg/misconf/scanner.go, projectdiscovery_nuclei code/FUZZING.md,
usestrix_strix code/strix/skills/vulnerabilities/):
- trivy-scan / nuclei-scan: scanners are only ever run against payload-provided
  local paths or self-created temp dirs — never the network or wider filesystem.
- strix-scan: LLM-driven agent; honest unavailable without credentials/sandbox.

Honesty: no score or probe output is fabricated. Where a dependency cannot
provision on this box, available() reports (False, "<truthful reason>") and any
partial venv is purged by provision_venv. available() never raises.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate, provision_venv  # noqa: E402


# ---------------------------------------------------------------------------
# shared stdlib helpers
# ---------------------------------------------------------------------------

def _safe_name(value: str) -> str:
    """Confine an upload name to a single bare filename (no /, \\, or ..)."""
    segment = re.split(r"[/\\]+", value)[-1].strip()
    if segment in ("", ".", ".."):
        return "upload"
    return segment


def _safe_name_results(payload: dict) -> dict:
    return {"ok": True, "results": [
        {"input": v, "output": _safe_name(v)} for v in payload.get("inputs", [])]}


def _run_driver(python: Path | None, script: str, action: str,
                payload: dict, label: str) -> dict:
    """Run a probe driver inside the candidate's venv python."""
    if python is None:
        return {"ok": False, "error": f"{label} venv not provisioned"}
    try:
        proc = subprocess.run(
            [str(python), "-c", script, action, json.dumps(payload)],
            capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{label} driver timed out (300s)"}
    try:
        return json.loads(proc.stdout.decode())
    except Exception:
        return {"ok": False,
                "error": f"{label} driver: {proc.stderr.decode()[-300:]}"}


# ---------------------------------------------------------------------------
# persistence — store_probe contract mirrors SqliteStore (persistence.py:21-120)
# ---------------------------------------------------------------------------

_TURSO_DRIVER = r"""
import json, shutil, sys, tempfile, threading, time
from pathlib import Path
import libsql_experimental as libsql

action, payload = sys.argv[1], json.loads(sys.argv[2])

def connect(path):
    conn = libsql.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS kv (id TEXT PRIMARY KEY, blob TEXT)")
    return conn

data_dir = Path(tempfile.mkdtemp(prefix=f"turso-{action}-"))
out = {}
try:
    db = data_dir / "store.db"
    if action == "write_read":
        n, docs = payload.get("n", 50), payload.get("docsPerWrite", 40)
        conn, timings = connect(db), []
        for i in range(n):
            blob = json.dumps({"documents": [{"id": f"doc-{i}-{j}"} for j in range(docs)]})
            t0 = time.monotonic()
            conn.execute("REPLACE INTO kv (id, blob) VALUES ('workspace', ?)", (blob,))
            conn.commit()
            timings.append((time.monotonic() - t0) * 1000)
        conn.close()
        timings.sort()
        out = {"ok": True, "p50_ms": timings[len(timings) // 2],
               "p95_ms": timings[int(len(timings) * 0.95)], "documents": docs}
    elif action == "concurrent":
        writers, ops = payload.get("writers", ["A", "B"]), payload.get("ops", 20)
        conn, errors = connect(db), []

        def worker(tag):
            c = connect(db)
            for i in range(ops):
                try:
                    c.execute("INSERT INTO kv (id, blob) VALUES (?, '{}')",
                              (f"doc-{tag}-{i}",))
                    c.commit()
                except Exception as exc:
                    errors.append(str(exc))
            c.close()
        threads = [threading.Thread(target=worker, args=(t,)) for t in writers]
        for t in threads: t.start()
        for t in threads: t.join()
        surviving = conn.execute(
            "SELECT COUNT(*) FROM kv WHERE id != 'workspace'").fetchone()[0]
        conn.close()
        expected = len(writers) * ops
        out = {"ok": True, "expected": expected, "surviving": surviving,
               "lost": expected - surviving, "errors": len(errors)}
    elif action == "atomicity":
        writes = payload.get("writes", 150)
        conn = connect(db)
        conn.execute("REPLACE INTO kv (id, blob) VALUES ('workspace', '{}')")
        conn.commit()
        torn, stopped = 0, False

        # libsql-experimental local files raise "database is locked" under
        # tight two-connection contention instead of waiting on a busy
        # timeout (unlike stdlib sqlite3). Lock contention is not a torn
        # read: retry it; only count actually corrupted fetched rows.
        def _locked(exc):
            return "locked" in str(exc).lower()

        def reader():
            global torn  # module-level script: no enclosing function scope,
            # so `nonlocal` is a SyntaxError here; `torn` is a module global.
            c = connect(db)
            while not stopped:
                try:
                    json.loads(c.execute(
                        "SELECT blob FROM kv WHERE id='workspace'").fetchone()[0])
                except Exception as exc:
                    if _locked(exc):
                        time.sleep(0.001)
                    else:
                        torn += 1
            c.close()
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        for i in range(writes):
            for _attempt in range(1000):
                try:
                    conn.execute("REPLACE INTO kv (id, blob) VALUES ('workspace', ?)",
                                 (json.dumps({"i": i}),))
                    conn.commit()
                    break
                except Exception as exc:
                    if _locked(exc):
                        time.sleep(0.001)
                    else:
                        raise
        stopped = True
        thread.join(timeout=10)
        conn.close()
        out = {"ok": True, "torn_reads": torn, "writes": writes}
    elif action == "corrupt_read":
        db.write_bytes(b'{"version": 1, TRUNCATED GARBAGE')
        try:
            conn = libsql.connect(str(db))
            conn.execute("SELECT * FROM kv LIMIT 1").fetchall()
            conn.close()
            out = {"ok": True, "behavior": "recovered-default"}
        except Exception as exc:
            out = {"ok": True, "behavior": f"threw:{type(exc).__name__}"}
    else:
        out = {"ok": False, "error": f"unknown action {action}"}
finally:
    shutil.rmtree(data_dir, ignore_errors=True)
print(json.dumps(out))
"""


class TursoStore(Candidate):
    """Turso/libsql embedded store (corpus tursodatabase_turso)."""

    name = "turso-store"
    stages = {"persistence"}

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        try:
            # pip route: libsql-experimental ships prebuilt native wheels, so
            # no cargo build is attempted. On failure provision_venv purges.
            self._python, reason = provision_venv(
                "turso-store", ["libsql-experimental"])
            return (self._python is not None), reason
        except Exception as exc:
            return False, f"available() error: {exc}"

    def store_probe(self, action: str, payload: dict) -> dict:
        if action == "safe_name":
            return _safe_name_results(payload)
        return _run_driver(self._python, _TURSO_DRIVER, action, payload,
                           "turso-store")


_OPENDAL_DRIVER = r"""
import json, shutil, sys, tempfile, threading, time
from pathlib import Path
import opendal

action, payload = sys.argv[1], json.loads(sys.argv[2])
data_dir = Path(tempfile.mkdtemp(prefix=f"opendal-{action}-"))
out = {}
try:
    op = opendal.Operator("fs", root=str(data_dir))
    if action == "write_read":
        n, docs = payload.get("n", 50), payload.get("docsPerWrite", 40)
        timings = []
        for i in range(n):
            blob = json.dumps({"documents": [{"id": f"doc-{i}-{j}"} for j in range(docs)]})
            t0 = time.monotonic()
            op.write("workspace", blob.encode())
            timings.append((time.monotonic() - t0) * 1000)
        timings.sort()
        out = {"ok": True, "p50_ms": timings[len(timings) // 2],
               "p95_ms": timings[int(len(timings) * 0.95)], "documents": docs}
    elif action == "concurrent":
        writers, ops = payload.get("writers", ["A", "B"]), payload.get("ops", 20)
        errors = []

        def worker(tag):
            for i in range(ops):
                try:
                    op.write(f"doc-{tag}-{i}", b"{}")
                except Exception as exc:
                    errors.append(str(exc))
        threads = [threading.Thread(target=worker, args=(t,)) for t in writers]
        for t in threads: t.start()
        for t in threads: t.join()
        surviving = sum(1 for e in op.list("") if e.path.startswith("doc-"))
        expected = len(writers) * ops
        out = {"ok": True, "expected": expected, "surviving": surviving,
               "lost": expected - surviving, "errors": len(errors)}
    elif action == "atomicity":
        writes = payload.get("writes", 150)
        op.write("workspace", b"{}")
        torn, stopped = 0, False

        def reader():
            global torn  # module-level script: `nonlocal` is a SyntaxError
            # here (no enclosing function scope); `torn` is a module global.
            while not stopped:
                try:
                    json.loads(op.read("workspace"))
                except Exception:
                    torn += 1
        thread = threading.Thread(target=reader)
        thread.start()
        for i in range(writes):
            op.write("workspace", json.dumps({"i": i}).encode())
        stopped = True
        thread.join()
        out = {"ok": True, "torn_reads": torn, "writes": writes}
    elif action == "corrupt_read":
        op.write("corrupt", b'{"version": 1, TRUNCATED GARBAGE')
        try:
            data = op.read("corrupt")
            json.loads(data)
            out = {"ok": True, "behavior": "recovered-default"}
        except Exception as exc:
            # the fs service returns stored bytes verbatim; report what happened
            out = {"ok": True, "behavior": f"threw:{type(exc).__name__}"}
    else:
        out = {"ok": False, "error": f"unknown action {action}"}
finally:
    shutil.rmtree(data_dir, ignore_errors=True)
print(json.dumps(out))
"""


class OpenDalStore(Candidate):
    """Apache OpenDAL store over its fs service (corpus apache_opendal)."""

    name = "opendal-store"
    stages = {"persistence"}

    def __init__(self):
        self._python: Path | None = None

    def available(self):
        try:
            # pip route: `opendal` ships prebuilt native wheels, no cargo build.
            self._python, reason = provision_venv("opendal-store", ["opendal"])
            return (self._python is not None), reason
        except Exception as exc:
            return False, f"available() error: {exc}"

    def store_probe(self, action: str, payload: dict) -> dict:
        if action == "safe_name":
            return _safe_name_results(payload)
        return _run_driver(self._python, _OPENDAL_DRIVER, action, payload,
                           "opendal-store")


class _UnprovisionedStore(Candidate):
    """Base for native stores that cannot provision on this box.

    store_probe still honours the contract: safe_name is pure stdlib and
    always answered truthfully; storage actions report not-provisioned
    instead of fabricating results. (These candidates are only raced when
    available() is True, so the storage actions are never actually called.)
    """

    _reason = "not provisioned"

    def available(self):
        return False, self._reason

    def store_probe(self, action: str, payload: dict) -> dict:
        if action == "safe_name":
            return _safe_name_results(payload)
        return {"ok": False, "error": f"{self.name}: {self._reason}"}


class FilecacheStore(_UnprovisionedStore):
    """gdt050579/filecache — Rust crate, no Python binding exists."""

    name = "filecache-store"
    stages = {"persistence"}

    def available(self):
        if not shutil.which("cargo"):
            return False, ("cargo not installed; filecache is a Rust crate "
                           "with no pip-installable Python binding")
        return False, ("filecache (gdt050579/filecache) is a Rust crate with "
                       "no pip-installable binding; a from-source cargo build "
                       "is not provisioned in this lane (no vendored deps, "
                       "disk-constrained)")


class SpotcacheStore(_UnprovisionedStore):
    """spotify/SPTPersistentCache — Objective-C for Apple platforms."""

    name = "spotcache-store"
    stages = {"persistence"}

    def available(self):
        if sys.platform != "darwin":
            return False, ("SPTPersistentCache is Objective-C for Apple "
                           "platforms; cannot build on Linux")
        return False, "no Xcode build lane available on this host"


# ---------------------------------------------------------------------------
# api — lifecycle mirrors FastApiNaive (api.py:38-85)
# ---------------------------------------------------------------------------

# Minimal hayhooks pipeline: no LLM, no external services. Hayhooks exposes it
# as POST /echo/run with a pydantic-validated JSON body. hayhooks >= 1.x
# rejects wrappers whose run_api lacks a RETURN TYPE annotation ("Pipeline
# wrapper is missing a return type for 'run_api' method" at deploy time).
_HAYHOOKS_WRAPPER = '''
from hayhooks import BasePipelineWrapper
from haystack import Pipeline


class PipelineWrapper(BasePipelineWrapper):
    def setup(self) -> None:
        self.pipeline = Pipeline()

    def run_api(self, content: str = "") -> dict:
        return {"ok": True, "length": len(str(content))}
'''


class HayhooksApi(Candidate):
    """deepset-ai/hayhooks serving one local echo pipeline."""

    name = "hayhooks-api"
    stages = {"api"}

    def __init__(self):
        self._python: Path | None = None
        self._proc: subprocess.Popen | None = None
        self._tmpdir: Path | None = None

    def available(self):
        try:
            self._python, reason = provision_venv("hayhooks", ["hayhooks"])
            if self._python is None:
                return False, reason
            check = subprocess.run(
                [str(self._python), "-c", "import hayhooks"],
                capture_output=True, timeout=120)
            if check.returncode != 0:
                return False, ("hayhooks installed but import failed: "
                               f"{check.stderr.decode()[-200:]}")
            return True, ""
        except Exception as exc:
            return False, f"available() error: {exc}"

    def start_api(self) -> str:
        if self._python is None:
            raise RuntimeError("hayhooks-api venv not provisioned")
        self._tmpdir = Path(tempfile.mkdtemp(prefix="hayhooks-api-"))
        pdir = self._tmpdir / "pipelines" / "echo"
        pdir.mkdir(parents=True)
        (pdir / "pipeline_wrapper.py").write_text(_HAYHOOKS_WRAPPER)
        port = 8973
        env = {**os.environ,
               "HAYHOOKS_HOST": "127.0.0.1",
               "HAYHOOKS_PORT": str(port),
               "HAYHOOKS_PIPELINES_DIR": str(self._tmpdir / "pipelines")}
        # hayhooks 1.x ships an EMPTY __main__.py, so `python -m hayhooks run`
        # exits 0 immediately without starting anything; the real CLI is the
        # `hayhooks` console script (hayhooks.cli:hayhooks_cli, typer).
        server_log = (self._tmpdir / "server.log").open("w")
        self._proc = subprocess.Popen(
            [str(self._python), "-c",
             "from hayhooks.cli import hayhooks_cli; hayhooks_cli()",
             "run", "--host", "127.0.0.1", "--port", str(port),
             "--pipelines-dir", str(self._tmpdir / "pipelines")],
            cwd=self._tmpdir, stdout=server_log,
            stderr=subprocess.STDOUT, env=env)
        base = f"http://127.0.0.1:{port}"
        for _ in range(120):
            try:
                urllib.request.urlopen(base + "/status", timeout=1)
                return base
            except Exception:
                if self._proc.poll() is not None:
                    break  # server already died; no point waiting
                time.sleep(0.25)
        server_log.flush()
        tail = self._log_tail()
        self.stop_api()
        raise RuntimeError(
            "hayhooks-api did not come up on 8973; server log tail: " + tail)

    def _log_tail(self, max_chars: int = 400) -> str:
        """Last lines of the captured server log (for failure reporting)."""
        log = (self._tmpdir / "server.log") if self._tmpdir else None
        if log is None or not log.exists():
            return "<no server log captured>"
        try:
            return log.read_text(errors="replace")[-max_chars:]
        except Exception as exc:
            return f"<could not read server log: {exc}>"

    def stop_api(self) -> None:
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    def api_probe_endpoints(self) -> dict:
        return {"mutate": "/echo/run"}


# ---------------------------------------------------------------------------
# security — probe names mirror InformationProcesser.security_probe
# (candidates.py:361-378): safe_name / injection_extract / dep_audit
# ---------------------------------------------------------------------------

class _ScannerBase(Candidate):
    """Shared contract for binary-gated scanners.

    Scanners only ever touch payload-provided local paths or temp dirs this
    class creates — never the network or the wider filesystem.
    """

    _binary: str | None = None
    _binary_name = ""

    def available(self):
        try:
            binary = shutil.which(self._binary_name)
            if not binary:
                return False, f"{self._binary_name} binary not installed on this host"
            self._binary = binary
            return True, ""
        except Exception as exc:
            return False, f"available() error: {exc}"

    def security_probe(self, probe: str, payload: dict) -> dict:
        if probe == "safe_name":
            return _safe_name_results(payload)
        if probe == "injection_extract":
            return {"ok": False,
                    "error": f"{self.name} is a vulnerability scanner; "
                             "it does not extract documents"}
        if probe == "dep_audit":
            return self._dep_audit(payload)
        return {"ok": False, "error": f"unknown probe {probe}"}

    def _audit_target(self, payload: dict) -> tuple[Path, Path | None]:
        """(target dir, temp dir to clean up or None)."""
        if payload.get("path"):
            return Path(payload["path"]), None
        tmp = Path(tempfile.mkdtemp(prefix=f"{self.name}-audit-"))
        (tmp / "requirements.txt").write_text("requests==2.31.0\n")
        return tmp, tmp

    def _dep_audit(self, payload: dict) -> dict:
        raise NotImplementedError


class TrivyScan(_ScannerBase):
    """aquasecurity/trivy — dependency/config scanner, binary-gated."""

    name = "trivy-scan"
    stages = {"security"}
    _binary_name = "trivy"

    def _dep_audit(self, payload: dict) -> dict:
        if self._binary is None:
            return {"ok": False, "error": "trivy binary not provisioned"}
        target, cleanup = self._audit_target(payload)
        try:
            proc = subprocess.run(
                [self._binary, "fs", "--scanners", "vuln", "--format", "json",
                 "--quiet", str(target)],
                capture_output=True, timeout=600)
            raw = proc.stdout.decode()
            if proc.returncode != 0:
                return {"ok": False,
                        "error": f"trivy exited {proc.returncode}: "
                                 f"{proc.stderr.decode()[-200:]}",
                        "exit": proc.returncode}
            try:
                json.loads(raw)
            except Exception:
                return {"ok": False, "exit": proc.returncode,
                        "error": "trivy produced non-JSON output"}
            return {"ok": True, "raw": raw, "exit": proc.returncode,
                    "format": "trivy-json"}
        finally:
            if cleanup is not None:
                shutil.rmtree(cleanup, ignore_errors=True)


class NucleiScan(_ScannerBase):
    """projectdiscovery/nuclei — template-based scanner, binary-gated.

    nuclei is not a dependency-manifest auditor; dep_audit runs it against
    the local target and reports the genuine raw output + exit code (a
    template-less run exits non-zero, which is reported truthfully).
    """

    name = "nuclei-scan"
    stages = {"security"}
    _binary_name = "nuclei"

    def _dep_audit(self, payload: dict) -> dict:
        if self._binary is None:
            return {"ok": False, "error": "nuclei binary not provisioned"}
        target, cleanup = self._audit_target(payload)
        try:
            proc = subprocess.run(
                [self._binary, "-target", str(target), "-jsonl", "-silent"],
                capture_output=True, timeout=300)
            raw = proc.stdout.decode()
            if proc.returncode != 0:
                return {"ok": False, "exit": proc.returncode,
                        "error": f"nuclei exited {proc.returncode} "
                                 "(templates/targets not provisioned for a "
                                 f"local manifest): {proc.stderr.decode()[-200:]}"}
            return {"ok": True, "raw": raw, "exit": proc.returncode,
                    "format": "nuclei-jsonl"}
        finally:
            if cleanup is not None:
                shutil.rmtree(cleanup, ignore_errors=True)


class StrixScan(Candidate):
    """usestrix/strix — LLM-driven security agent; cannot provision here."""

    name = "strix-scan"
    stages = {"security"}

    def available(self):
        return False, ("strix is an LLM-driven security agent (usestrix/strix): "
                       "it requires LLM API credentials and a docker sandbox "
                       "lane, neither of which is provisionable on this host")

    def security_probe(self, probe: str, payload: dict) -> dict:
        if probe == "safe_name":
            return _safe_name_results(payload)
        if probe == "injection_extract":
            return {"ok": False,
                    "error": "strix-scan is not provisioned (needs LLM "
                             "credentials); it does not extract documents"}
        if probe == "dep_audit":
            return {"ok": False,
                    "error": "strix-scan is not provisioned (needs LLM "
                             "credentials and a docker sandbox lane)"}
        return {"ok": False, "error": f"unknown probe {probe}"}


CANDIDATES = [TursoStore, OpenDalStore, FilecacheStore, SpotcacheStore,
              HayhooksApi, TrivyScan, NucleiScan, StrixScan]
