"""Python control-plane bridge for the std-only Rust environment runner."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Mapping

from .language_adapters import LanguageAdapter, test_envelope


class RunnerProtocolError(RuntimeError):
    """The runner returned an invalid or unsuccessful protocol response."""


def default_runner_path() -> Path:
    configured = os.environ.get("EVO_ENV_RUNNER")
    if configured:
        return Path(configured)
    # runner_bridge.py lives at <repo>/plugins/evo/src/evo/; parents[4] is the
    # repo root (parents[3] is `plugins`, which double-counted the path below).
    project_root = Path(__file__).resolve().parents[4]
    candidates = (
        project_root / "plugins/evo/bin/evo-env-runner/target/release/evo-env-runner",
        project_root / "plugins/evo/bin/evo-env-runner/target/debug/evo-env-runner",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


class RustRunnerClient:
    """Drive one Rust runner process using one JSON request per line."""

    def __init__(self, runner: Path | str | None = None) -> None:
        binary = Path(runner) if runner is not None else default_runner_path()
        if not binary.exists():
            raise FileNotFoundError(
                f"Rust environment runner not found at {binary}; build "
                "plugins/evo/bin/evo-env-runner first or set EVO_ENV_RUNNER"
            )
        self.process = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._responses: queue.Queue[str | BaseException] = queue.Queue()
        self._next_id = 0
        # Bounded tail of the runner's own stderr. Draining it in a thread is
        # what prevents a full stderr pipe from deadlocking the runner (a large
        # panic backtrace or verbose diagnostic would otherwise block its write
        # while we wait forever for a stdout response).
        self._stderr_tail: deque[str] = deque(maxlen=200)
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self._reader = threading.Thread(
            target=self._read_stdout, args=(self.process.stdout,), daemon=True
        )
        self._reader.start()
        self._stderr_reader = threading.Thread(
            target=self._drain_stderr, args=(self.process.stderr,), daemon=True
        )
        self._stderr_reader.start()

    def _read_stdout(self, stream: Any) -> None:
        try:
            for line in stream:
                if line.strip():
                    self._responses.put(line)
        except BaseException as exc:  # surfaced by request()
            self._responses.put(exc)

    def _drain_stderr(self, stream: Any) -> None:
        try:
            for line in stream:
                self._stderr_tail.append(line.rstrip("\n"))
        except BaseException:  # nothing to surface; stderr is diagnostic only
            pass

    def _stderr_snapshot(self) -> str:
        return "\n".join(self._stderr_tail)[-2000:]

    def request(self, payload: Mapping[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        if self.process.poll() is not None:
            raise RunnerProtocolError(
                f"Rust runner exited with code {self.process.returncode}; "
                f"stderr: {self._stderr_snapshot()!r}"
            )
        assert self.process.stdin is not None
        self._next_id += 1
        corr_id = self._next_id
        body = dict(payload)
        body["id"] = corr_id
        self.process.stdin.write(json.dumps(body, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

        # Read until the matching response arrives. The runner emits exactly one
        # JSON object per request on stdout, but we defend against desync anyway:
        # non-JSON / non-object lines are stray noise and skipped; a response
        # whose echoed `id` belongs to an earlier request is stale and dropped.
        # A response without `id` (older runner) is accepted as the reply.
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.process.kill()
                raise RunnerProtocolError(
                    f"Rust runner timed out after {timeout}s; stderr: {self._stderr_snapshot()!r}"
                )
            try:
                response = self._responses.get(timeout=remaining)
            except queue.Empty:
                self.process.kill()
                raise RunnerProtocolError(
                    f"Rust runner timed out after {timeout}s; stderr: {self._stderr_snapshot()!r}"
                )
            if isinstance(response, BaseException):
                raise RunnerProtocolError("Rust runner stdout reader failed") from response
            try:
                value = json.loads(response)
            except json.JSONDecodeError:
                continue  # stray non-JSON line on stdout; skip
            if not isinstance(value, dict):
                continue  # stray non-object line; skip
            resp_id = value.get("id")
            if resp_id is not None and resp_id != corr_id:
                continue  # response for an earlier request; drop and keep reading
            if value.get("ok") is not True:
                error = value.get("error")
                raise RunnerProtocolError(str(error or value))
            return value

    def prepare(
        self,
        *,
        run_id: str,
        root: Path,
        adapter: LanguageAdapter,
        env: Mapping[str, str] | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        manifest = {
            "schema_version": 1,
            "id": run_id,
            "mode": "host",
            "root": str(root.resolve()),
            "workdir": ".",
            "argv": list(adapter.command),
            "env": dict(env or {}),
            "timeout_ms": timeout_ms,
            "outputs": [],
        }
        return self.request({"op": "prepare", "manifest": manifest})

    def run(self, *, adapter: LanguageAdapter, timeout: float = 60.0) -> dict[str, Any]:
        response = self.request({"op": "run"}, timeout=timeout)
        result = response.get("result")
        if not isinstance(result, dict):
            raise RunnerProtocolError(
                f"Rust runner 'run' returned no result object: {response!r}"
            )
        # `code` is legitimately None when the process timed out or was killed;
        # carry `status`/`timed_out` so a None returncode is never ambiguous
        # downstream (a `returncode == 0` check would otherwise silently read a
        # timeout as a plain failure with no explanation).
        return test_envelope(
            adapter,
            returncode=result.get("code"),
            duration_ms=result.get("duration_ms"),
            stdout=str(result.get("stdout", "")),
            stderr=str(result.get("stderr", "")),
            status=(str(result["status"]) if result.get("status") else None),
            timed_out=bool(result.get("timed_out", False)),
        )

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.request({"op": "destroy"}, timeout=5)
            except (OSError, RunnerProtocolError):
                self.process.kill()
            finally:
                if self.process.stdin is not None:
                    self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def __enter__(self) -> "RustRunnerClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def run_adapter(
    adapter: LanguageAdapter,
    *,
    root: Path,
    run_id: str = "adapter-run",
    env: Mapping[str, str] | None = None,
    runner: Path | str | None = None,
) -> dict[str, Any]:
    with RustRunnerClient(runner) as client:
        client.prepare(run_id=run_id, root=root, adapter=adapter, env=env)
        return client.run(adapter=adapter)
