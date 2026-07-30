from __future__ import annotations

import io
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evo.backends.environment import (
    ENVIRONMENT_MANIFEST_VERSION,
    ENVIRONMENT_SCHEMA,
    EnvironmentEvidence,
    EnvironmentSpec,
)
from evo.backends.protocol import SandboxHandle, SandboxSpec
from evo.backends.remote import RemoteSandboxBackend


def test_environment_manifest_and_evidence_envelopes_are_versioned() -> None:
    spec = EnvironmentSpec.from_manifest({
        "image_ref": "python:3.12",
        "env": {"MODE": "test"},
        "fixtures": {"config/test.txt": "fixture\n"},
        "setup_commands": ["echo setup"],
        "customize_commands": ["echo customize"],
        "identity_command": ["python", "--version"],
    })

    manifest = spec.to_envelope()
    assert manifest["schema"] == ENVIRONMENT_SCHEMA
    assert manifest["version"] == ENVIRONMENT_MANIFEST_VERSION
    assert manifest["kind"] == "manifest"
    assert EnvironmentSpec.from_manifest(manifest).digest() == spec.digest()

    evidence = EnvironmentEvidence(
        digest=spec.digest(),
        identity="Python 3.12.0",
        adapter_metadata={"provider": "fake", "python_test": True},
        identity_command=["python", "--version"],
    )
    assert EnvironmentEvidence.from_envelope(evidence.to_envelope()) == evidence

    with tarfile.open(fileobj=io.BytesIO(spec.fixture_tar()), mode="r:") as archive:
        member = archive.getmember("config/test.txt")
        assert archive.extractfile(member).read() == b"fixture\n"


def test_sandbox_spec_keeps_legacy_positional_fields_and_carries_environment() -> None:
    spec = EnvironmentSpec(env={"MODE": "test"})
    sandbox = SandboxSpec("image", {}, "token", 9090, 20, spec)
    assert sandbox.exposed_port == 9090
    assert sandbox.timeout_seconds == 20
    assert sandbox.environment is spec


@dataclass
class _Result:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""


class _FakeEnvironmentClient:
    def __init__(self, identity: str) -> None:
        self.identity = identity
        self.uploads: list[tuple[str, bytes]] = []
        self.calls: list[dict[str, Any]] = []

    def fs_upload_batch(self, dest_dir: str, tar_bytes: bytes) -> None:
        self.uploads.append((dest_dir, tar_bytes))

    def process_run(self, command: str, **kwargs: Any) -> _Result:
        self.calls.append({"command": command, **kwargs})
        if command == "python":
            return _Result(stdout=self.identity)
        return _Result()


class _FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.specs: list[SandboxSpec] = []

    def provision(self, spec: SandboxSpec) -> SandboxHandle:
        self.specs.append(spec)
        return SandboxHandle(
            provider=self.name,
            base_url="http://sandbox",
            bearer_token="returned-token",
            native_id="fake-1",
            metadata={"adapter": "python-test"},
        )


def test_remote_environment_uploads_runs_commands_and_accepts_runner_evidence(
    tmp_path: Path,
) -> None:
    returned = {
        "schema": ENVIRONMENT_SCHEMA,
        "version": 1,
        "kind": "evidence",
        "digest": "runner-digest",
        "identity": "runner-identity",
        "identity_command": ["python", "--version"],
        "adapter_metadata": {"runner": "rust"},
    }
    spec = EnvironmentSpec.from_manifest({
        "env": {"MODE": "test"},
        "fixtures": [{"path": "fixture.txt", "content": "hello"}],
        "setup": ["echo setup"],
        "customize": ["echo customize"],
        "identity_command": ["python", "--version"],
    })
    client = _FakeEnvironmentClient(json.dumps(returned))
    backend = RemoteSandboxBackend(_FakeProvider())

    evidence = backend._apply_environment(
        client, "/workspace/repo", spec, {"adapter": "python-test"}
    )

    assert client.uploads and client.uploads[0][0] == "/workspace/repo"
    assert [call["command"] for call in client.calls] == ["/bin/sh", "/bin/sh", "python"]
    assert client.calls[0]["args"] == ["-lc", "echo setup"]
    assert client.calls[1]["args"] == ["-lc", "echo customize"]
    assert all(call["env"] == {"MODE": "test"} for call in client.calls)
    assert evidence.digest == "runner-digest"
    assert evidence.identity == "runner-identity"
    assert evidence.adapter_metadata == {"adapter": "python-test", "runner": "rust"}


def test_remote_provision_without_manifest_preserves_legacy_spec(tmp_path: Path) -> None:
    provider = _FakeProvider()
    backend = RemoteSandboxBackend(provider)

    backend._provision_sandbox(0, root=tmp_path)

    spec = provider.specs[0]
    assert spec.image_ref == "evo-sandbox-base"
    assert spec.env == {}
    assert spec.environment is None


# --------------------------------------------------------------------- FLAW 1


class _CountingProvider(_FakeProvider):
    """Fake provider that records how many times provision() is called."""

    def __init__(self) -> None:
        super().__init__()
        self.provision_calls = 0

    def provision(self, spec: SandboxSpec) -> SandboxHandle:
        self.provision_calls += 1
        return super().provision(spec)


def _allocate_ctx(root: Path, exp_id: str) -> Any:
    from evo.backends.protocol import AllocateCtx

    return AllocateCtx(
        root=root,
        exp_id=exp_id,
        parent_node=None,
        parent_commit="deadbeef",
        parent_ref="main",
        branch=f"evo/{exp_id}",
        hypothesis="test",
    )


def _seed_live_free_slot(backend: RemoteSandboxBackend, root: Path) -> None:
    """Simulate a sandbox provisioned by a now-dead process: a free slot
    (leased_by=None) whose persisted record still points at a live container."""
    from evo.backends import remote_state

    backend._ensure_state_file(root)
    with remote_state.locked_state(root, backend.state_key) as state:
        state["next_id"] = 1
        state["sandboxes"].append({
            "id": 0,
            "native_id": "live-container-A",
            "base_url": "http://sandbox-A",
            "bearer_token": "token-A",
            "metadata": {"adapter": "python-test"},
            "leased_by": None,
            "last_branch": "evo/exp_old",
            "provisioned_at": "2026-01-01T00:00:00+00:00",
        })


def test_reclaiming_live_slot_rehydrates_handle_without_reprovisioning(
    tmp_path: Path,
) -> None:
    """FLAW 1 regression: a process with an empty in-memory `_handles` that
    reclaims a free slot backed by a live persisted record must REUSE that
    container (rehydrate the handle) rather than provision a duplicate and
    leak the original."""
    provider = _CountingProvider()
    backend = RemoteSandboxBackend(provider)
    _seed_live_free_slot(backend, tmp_path)

    # Cross-process: process B starts cold with no in-memory handles.
    assert backend._handles == {}

    slot_id, needs_provision, handle = backend._claim_slot(
        _allocate_ctx(tmp_path, "exp_new")
    )

    assert slot_id == 0
    assert needs_provision is False
    assert handle is not None
    assert handle.native_id == "live-container-A"
    assert handle.base_url == "http://sandbox-A"
    # The whole point: no new container was spun up.
    assert provider.provision_calls == 0


def test_reclaiming_unprovisioned_slot_still_needs_provision(tmp_path: Path) -> None:
    """Guard the normal path: a free slot that was never provisioned
    (native_id/base_url unset) must still report needs_provision=True."""
    from evo.backends import remote_state

    backend = RemoteSandboxBackend(_CountingProvider())
    backend._ensure_state_file(tmp_path)
    with remote_state.locked_state(tmp_path, backend.state_key) as state:
        state["next_id"] = 1
        state["sandboxes"].append({
            "id": 0,
            "native_id": None,
            "base_url": None,
            "bearer_token": "",
            "leased_by": None,
            "last_branch": None,
            "provisioned_at": None,
        })

    slot_id, needs_provision, handle = backend._claim_slot(
        _allocate_ctx(tmp_path, "exp_new")
    )

    assert slot_id == 0
    assert needs_provision is True
    assert handle is None


# --------------------------------------------------------------------- FLAW 2


def test_result_helpers_tolerate_dict_and_object_shapes() -> None:
    """FLAW 2 regression: process-run results come back as dicts
    (`{"exitCode": ...}`) from some providers and as objects (`.exit_code`)
    from others. Both must be read the same way."""
    backend = RemoteSandboxBackend(_FakeProvider())

    dict_ok = {"exitCode": 0, "stderr": "d-err"}
    dict_bad = {"exitCode": 3, "stderr": "boom"}
    obj_ok = _Result(exit_code=0, stderr="o-err")
    obj_bad = _Result(exit_code=5, stderr="kaboom")

    assert backend._result_exit_code(dict_ok) == 0
    assert backend._result_exit_code(dict_bad) == 3
    assert backend._result_exit_code(obj_ok) == 0
    assert backend._result_exit_code(obj_bad) == 5

    assert backend._result_stderr(dict_bad) == "boom"
    assert backend._result_stderr(obj_bad) == "kaboom"
    # Missing fields degrade gracefully rather than raising.
    assert backend._result_exit_code({}) is None
    assert backend._result_stderr({}) == ""


# ------------------------------------------------ crashed-owner lease reclaim


def test_pid_alive_and_lease_age_helpers() -> None:
    import os
    import subprocess

    from evo.backends import remote

    assert remote._pid_alive(os.getpid()) is True
    reaped = subprocess.Popen(["true"])
    reaped.wait()
    # A reaped child's pid is (barring reuse) gone.
    assert remote._pid_alive(reaped.pid) is False

    assert remote._lease_age_seconds(None) is None
    assert remote._lease_age_seconds("not-a-timestamp") is None
    assert remote._lease_age_seconds("2020-01-01T00:00:00+00:00") > 1_000_000


def _seed_leased_slot(backend: RemoteSandboxBackend, root: Path, lease: dict) -> None:
    from evo.backends import remote_state

    backend._ensure_state_file(root)
    with remote_state.locked_state(root, backend.state_key) as state:
        state["next_id"] = 1
        state["sandboxes"].append({
            "id": 0,
            "native_id": "live-container-A",
            "base_url": "http://sandbox-A",
            "bearer_token": "token-A",
            "leased_by": lease,
            "last_branch": "evo/exp_crashed",
            "provisioned_at": "2026-01-01T00:00:00+00:00",
        })


def _lease_state(backend: RemoteSandboxBackend, root: Path) -> Any:
    from evo.backends import remote_state

    with remote_state.locked_state(root, backend.state_key) as state:
        return state["sandboxes"][0]["leased_by"]


def test_reconcile_reclaims_dead_owner_on_this_host_when_stale(tmp_path, monkeypatch) -> None:
    """A process that crashed WITHOUT reaching a terminal graph status (dead
    pid, this host, stale lease) has its slot reclaimed so it isn't pinned
    forever; the sandbox record survives for the next claim to reuse."""
    from evo.backends import remote

    backend = RemoteSandboxBackend(_FakeProvider())
    _seed_leased_slot(backend, tmp_path, {
        "exp_id": "exp_crashed", "pid": 424242,
        "host": remote._this_host(), "leased_at": "2020-01-01T00:00:00+00:00",
    })
    monkeypatch.setattr(remote, "_pid_alive", lambda pid: False)

    backend._reconcile_orphaned(tmp_path)

    assert _lease_state(backend, tmp_path) is None
    # Record (and its live container) is kept, not destroyed.
    from evo.backends import remote_state
    with remote_state.locked_state(tmp_path, backend.state_key) as state:
        assert state["sandboxes"][0]["native_id"] == "live-container-A"


def test_reconcile_keeps_live_owner_lease(tmp_path, monkeypatch) -> None:
    from evo.backends import remote

    backend = RemoteSandboxBackend(_FakeProvider())
    _seed_leased_slot(backend, tmp_path, {
        "exp_id": "exp_running", "pid": 424242,
        "host": remote._this_host(), "leased_at": "2020-01-01T00:00:00+00:00",
    })
    monkeypatch.setattr(remote, "_pid_alive", lambda pid: True)  # still running

    backend._reconcile_orphaned(tmp_path)

    assert _lease_state(backend, tmp_path) is not None


def test_reconcile_keeps_fresh_dead_lease(tmp_path, monkeypatch) -> None:
    """Dead pid but the lease is younger than the stale threshold: do not
    reclaim (guards the brief window around lease creation / pid handoff)."""
    from evo.backends import remote
    from evo.core import utc_now

    backend = RemoteSandboxBackend(_FakeProvider())
    _seed_leased_slot(backend, tmp_path, {
        "exp_id": "exp_fresh", "pid": 424242,
        "host": remote._this_host(), "leased_at": utc_now(),
    })
    monkeypatch.setattr(remote, "_pid_alive", lambda pid: False)

    backend._reconcile_orphaned(tmp_path)

    assert _lease_state(backend, tmp_path) is not None


def test_reconcile_ignores_other_host_lease(tmp_path, monkeypatch) -> None:
    """A pid is host-local, so a dead pid on a DIFFERENT host proves nothing;
    never reclaim a cross-host lease on pid liveness."""
    from evo.backends import remote

    backend = RemoteSandboxBackend(_FakeProvider())
    _seed_leased_slot(backend, tmp_path, {
        "exp_id": "exp_other", "pid": 424242,
        "host": "some-other-host", "leased_at": "2020-01-01T00:00:00+00:00",
    })
    monkeypatch.setattr(remote, "_pid_alive", lambda pid: False)

    backend._reconcile_orphaned(tmp_path)

    assert _lease_state(backend, tmp_path) is not None


def test_reconcile_still_frees_terminal_status_lease(tmp_path) -> None:
    """The original reclaim path (terminal graph status) is unaffected."""
    from evo.core import default_graph, save_graph

    backend = RemoteSandboxBackend(_FakeProvider())
    _seed_leased_slot(backend, tmp_path, {
        "exp_id": "exp_done", "pid": 424242,
        "host": "any-host", "leased_at": "2020-01-01T00:00:00+00:00",
    })
    graph = default_graph()
    graph["nodes"]["exp_done"] = {"id": "exp_done", "status": "committed"}
    save_graph(tmp_path, graph)

    backend._reconcile_orphaned(tmp_path)

    assert _lease_state(backend, tmp_path) is None

