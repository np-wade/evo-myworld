"""API family — A10 candidates.

- fastapi-naive: a minimal FastAPI/uvicorn app with the same endpoint shape as
  the incumbent (POST /documents/text). Represents framework defaults.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ip_eval.candidates import Candidate, provision_venv  # noqa: E402

_APP = """
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/")
def root():
    return {"name": "fastapi-naive"}

@app.post("/documents/text")
async def ingest(request: Request):
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("content"), str):
        return JSONResponse({"detail": "content must be a string"}, status_code=422)
    return {"ok": True, "length": len(body["content"])}
"""


class FastApiNaive(Candidate):
    name = "fastapi-naive"
    stages = {"api"}

    def __init__(self):
        self._python: Path | None = None
        self._proc: subprocess.Popen | None = None
        self._tmpdir: Path | None = None

    def available(self):
        self._python, reason = provision_venv("fastapi", ["fastapi", "uvicorn"])
        return (self._python is not None), reason

    def start_api(self) -> str:
        self._tmpdir = Path(tempfile.mkdtemp(prefix="fastapi-naive-"))
        (self._tmpdir / "app.py").write_text(_APP)
        port = 8972
        self._proc = subprocess.Popen(
            [str(self._python), "-m", "uvicorn", "app:app",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=self._tmpdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ},
        )
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                return base
            except Exception:
                time.sleep(0.25)
        self.stop_api()
        raise RuntimeError("fastapi-naive did not come up on 8972")

    def stop_api(self) -> None:
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None
        if self._tmpdir:
            import shutil
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    def api_probe_endpoints(self) -> dict:
        return {"mutate": "/documents/text"}


CANDIDATES = [FastApiNaive]
