"""RemoteSandboxBackend: workspace lifecycle backed by a remote sandbox.

The provider (Modal, E2B, SSH, ...) provisions the
container and owns the corresponding process/filesystem client object
for file ops, process exec, git ops, and teardown.

This module is lifecycle-only -- it owns provisioning, leasing, and
tear-down. State persists in `<run>/remote_state.json` (see
`remote_state.py`).
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core import utc_now, workspace_path
from . import remote_state

#: A crashed owner's lease is reclaimed only once it is at least this old, so a
#: freshly-created lease (or a pid handoff to a forked worker) is never mistaken
#: for a leak. Overridable via EVO_LEASE_STALE_SECONDS.
_DEFAULT_LEASE_STALE_SECONDS = 1800


def _this_host() -> str:
    return socket.gethostname()


def _pid_alive(pid: int) -> bool:
    """True if a process with `pid` exists on this host. `os.kill(pid, 0)`
    delivers no signal but raises ProcessLookupError when the pid is gone."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    except OSError:
        return True  # ambiguous -> conservatively assume alive, do not reclaim
    return True


def _lease_age_seconds(leased_at: str | None) -> float | None:
    """Seconds since `leased_at` (an ISO-8601 timestamp), or None if unparsable."""
    if not leased_at:
        return None
    try:
        started = datetime.fromisoformat(leased_at)
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started).total_seconds()
from .environment import EnvironmentEvidence, EnvironmentSpec
from .protocol import (
    AllocateCtx,
    AllocateResult,
    Backend,
    DiscardCtx,
    SandboxHandle,
    SandboxProvider,
    SandboxSpec,
)
from .state_keys import backend_state_key


class RemoteSandboxBackend:
    """Lease lifecycle for remote sandboxes. Provider-agnostic.

    Lifecycle parallels PoolBackend (pool.py:37-310): an `allocate()` call
    leases a sandbox (provisioning lazily on first use), `release_lease()`
    returns it to the free pool, `discard()` tears it down.

    POC scope: concurrency=1 (one active sandbox per workspace),
    tear-down on release. A `keep_warm` provider_config flag will gate
    warm-reuse in alpha.4.
    """

    name = "remote"

    def __init__(
        self,
        provider: SandboxProvider,
        *,
        provider_name: str | None = None,
        provider_config: dict[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name or provider.name
        self.provider_config = dict(provider_config or {})
        pool_size = self.provider_config.get("pool_size")
        if pool_size in (None, "", "unbounded"):
            self.pool_size: int | None = None
        else:
            try:
                parsed = int(pool_size)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"remote provider_config.pool_size must be an integer, got {pool_size!r}"
                ) from exc
            if parsed <= 0:
                raise RuntimeError("remote provider_config.pool_size must be > 0")
            self.pool_size = parsed
        self.state_key = backend_state_key(
            self.name,
            {
                "provider": self.provider_name,
                "provider_config": self.provider_config,
            },
        )
        # Keyed by sandbox `id` (the local index, not the provider native_id).
        self._tokens: dict[int, str] = {}
        # SandboxHandle objects live in memory too -- the provider needs them
        # for tear_down(), but they include opaque metadata (e.g. modal app
        # references) that aren't safe to serialize. Re-hydrated lazily from
        # remote_state.json's native_id on cold-start.
        self._handles: dict[int, SandboxHandle] = {}

    # ---------------------------------------------------------------- allocate

    def allocate(self, ctx: AllocateCtx) -> AllocateResult:
        """Lease a sandbox for the experiment, provisioning if needed.

        Mirrors PoolBackend.allocate (pool.py:37-72): reconcile orphaned
        leases first, then claim a slot atomically under the state lock,
        then perform slow operations (provision, parent_commit shipping)
        outside the lock with explicit unwind on failure.

        For the POC the parent-commit-shipping + checkout step is stubbed
        out -- commit 4/5 wires it through the sandbox-agent client.
        """
        from ..backends import pool  # for orphan-reconciliation pattern

        # Step 1: reconcile orphaned leases. Same shape as
        # `pool._reconcile_orphaned_leases`; see pool.py:249-270.
        self._ensure_state_file(ctx.root)
        self._reconcile_orphaned(ctx.root)

        # Step 2: under the state lock, find or create a free sandbox slot
        # and stamp the lease atomically. Slow operations (provision call,
        # network IO) happen outside the lock.
        environment = self._environment_for_root(ctx.root)
        slot_id, needs_provision, handle = self._claim_slot(ctx)

        try:
            if needs_provision:
                handle = self._provision_sandbox(
                    slot_id, root=ctx.root, environment=environment
                )
                self._handles[slot_id] = handle
                with remote_state.locked_state(ctx.root, self.state_key) as state:
                    sandbox = next(
                        s for s in state["sandboxes"] if s["id"] == slot_id
                    )
                    sandbox["native_id"] = handle.native_id
                    sandbox["base_url"] = handle.base_url
                    sandbox["bearer_token"] = handle.bearer_token
                    sandbox["metadata"] = dict(handle.metadata or {})
                    sandbox["provisioned_at"] = utc_now()
                    if environment is not None:
                        sandbox["environment_manifest"] = environment.to_envelope()
                        sandbox["environment_digest"] = environment.digest()

            # Step 3: ship parent commit into the sandbox + check out the
            # experiment's branch.
            worktree_path = self._setup_workspace(
                ctx, handle, slot_id, environment=environment
            )
        except Exception:
            # Unwind: release the lease atomically. Provider-side handle
            # stays warm (transient failures shouldn't burn a sandbox).
            self._release_if_matches(ctx.root, slot_id, ctx.exp_id)
            raise

        return AllocateResult(
            worktree=worktree_path,
            commit=ctx.parent_commit,
            branch=ctx.branch,
        )

    # ---------------------------------------------------------------- discard

    def discard(self, ctx: DiscardCtx) -> None:
        """Tear down the sandbox the experiment was running on."""
        node = ctx.node
        slot_id = self._slot_for_exp(ctx.root, node["id"])
        if slot_id is None:
            return  # nothing to do
        handle = self._handle_for_slot(ctx.root, slot_id)
        if handle is not None:
            try:
                self.provider.tear_down(handle)
            except Exception:
                # Best-effort; sandbox may already be gone (network blip,
                # provider-side timeout). State cleanup proceeds regardless.
                pass
        with remote_state.locked_state(ctx.root, self.state_key) as state:
            # Drop the slot entirely on discard. Re-allocate gets a fresh
            # provision; no half-states left around.
            state["sandboxes"] = [
                s for s in state["sandboxes"] if s["id"] != slot_id
            ]
        self._handles.pop(slot_id, None)
        self._tokens.pop(slot_id, None)

    # ---------------------------------------------------------------- release_lease

    def release_lease(self, ctx: DiscardCtx) -> None:
        """Clear the lease without tearing down the sandbox.

        POC behavior: ALSO tears down (no warm-reuse yet). When
        we add `keep_warm` config in alpha.4, this becomes the path that
        retains the sandbox.
        """
        # POC: same as discard.
        self.discard(ctx)

    # ---------------------------------------------------------------- gc

    def gc(self, ctx: DiscardCtx) -> bool:
        """Best-effort cleanup of stale sandboxes whose holders are gone.

        Returns True if anything got cleaned up so cli.cmd_gc reports it.
        """
        cleaned = False
        with remote_state.locked_state(ctx.root, self.state_key) as state:
            keep: list[dict[str, Any]] = []
            for sandbox in state["sandboxes"]:
                if sandbox.get("leased_by") is None:
                    handle = self._handle_from_record(sandbox)
                    if handle is not None:
                        try:
                            self.provider.tear_down(handle)
                            cleaned = True
                        except Exception:
                            pass
                        self._handles.pop(sandbox["id"], None)
                        self._tokens.pop(sandbox["id"], None)
                else:
                    keep.append(sandbox)
            state["sandboxes"] = keep
        return cleaned

    def sweep_orphans(self, root: Path, live_exp_ids: set[str]) -> list[str]:
        """Tear down sandboxes whose `leased_by` exp_id is missing from
        the graph (or is None — already-released but container alive).
        Returns native_ids of torn-down sandboxes."""
        torn: list[str] = []
        with remote_state.locked_state(root, self.state_key) as state:
            keep: list[dict[str, Any]] = []
            for sandbox in state["sandboxes"]:
                lease = sandbox.get("leased_by")
                exp_id = (lease or {}).get("exp_id") if lease else None
                # Reclaim if no holder OR holder is no longer in graph
                if lease is None or (exp_id and exp_id not in live_exp_ids):
                    handle = self._handle_from_record(sandbox)
                    if handle is not None:
                        try:
                            self.provider.tear_down(handle)
                            torn.append(handle.native_id)
                        except Exception:
                            pass
                        self._handles.pop(sandbox["id"], None)
                        self._tokens.pop(sandbox["id"], None)
                    continue
                keep.append(sandbox)
            state["sandboxes"] = keep
        return torn

    # ---------------------------------------------------------------- reset_all

    def reset_all(self, root: Path) -> None:
        """Tear down every recorded sandbox and wipe the workspace dir."""
        try:
            state = remote_state.read_state(root, self.state_key)
        except FileNotFoundError:
            state = {"sandboxes": []}
        for sandbox in state.get("sandboxes", []):
            handle = self._handle_from_record(sandbox)
            if handle is None:
                continue
            try:
                self.provider.tear_down(handle)
            except Exception:
                pass
        self._handles.clear()
        self._tokens.clear()
        shutil.rmtree(workspace_path(root), ignore_errors=True)

    # ---------------------------------------------------------------- internal

    def _claim_slot(
        self, ctx: AllocateCtx
    ) -> tuple[int, bool, SandboxHandle | None]:
        """Atomically claim or create a sandbox slot.

        Claims a free slot if one exists; otherwise provisions a new
        sandbox unless `pool_size` has been reached.

        Returns (slot_id, needs_provision, existing_handle_or_None). If
        needs_provision is True, the caller must call _provision_sandbox
        OUTSIDE the state lock and then update the state with the handle.
        """
        from ..backends.protocol import PoolExhausted

        with remote_state.locked_state(ctx.root, self.state_key) as state:
            free = [s for s in state["sandboxes"] if s.get("leased_by") is None]
            if free:
                sandbox = free[0]
                slot_id = sandbox["id"]
                sandbox["leased_by"] = {
                    "exp_id": ctx.exp_id,
                    "pid": os.getpid(),
                    "host": _this_host(),
                    "leased_at": utc_now(),
                }
                sandbox["last_branch"] = ctx.branch
                handle = self._handles.get(slot_id)
                if handle is None:
                    # Cross-process reclaim: another process may have
                    # provisioned this slot (and left a live container behind)
                    # before our in-memory `self._handles` was populated. If the
                    # persisted record still points at a live sandbox, rehydrate
                    # the handle from it so we REUSE that container instead of
                    # provisioning a duplicate and leaking (and continuing to
                    # bill for) the original. `_handle_from_record` returns None
                    # when the slot was never provisioned (native_id/base_url
                    # unset), which correctly keeps needs_provision True.
                    handle = self._handle_from_record(sandbox)
                return slot_id, handle is None, handle

            if self.pool_size is not None and len(state["sandboxes"]) >= self.pool_size:
                raise PoolExhausted(
                    "remote backend has no free sandbox; pool_size="
                    f"{self.pool_size} reached. Wait for an active experiment "
                    "to finish, or increase provider_config.pool_size."
                )

            slot_id = int(state.get("next_id", 0))
            state["next_id"] = slot_id + 1
            state["sandboxes"].append({
                "id": slot_id,
                "native_id": None,           # filled in after provision
                "base_url": None,
                "bearer_token": "",
                "leased_by": {
                    "exp_id": ctx.exp_id,
                    "pid": os.getpid(),
                    "host": _this_host(),
                    "leased_at": utc_now(),
                },
                "last_branch": ctx.branch,
                "provisioned_at": None,
            })
            return slot_id, True, None

    def _ensure_state_file(self, root: Path) -> None:
        """Create or reconcile remote_state.json for this provider config."""
        state_path = remote_state.remote_state_path(root, self.state_key)
        if state_path.exists():
            state = remote_state.read_state(root, self.state_key)
            if (
                state.get("provider") == self.provider_name
                and (state.get("provider_config", {}) or {}) == self.provider_config
            ):
                return
            leased = [
                sandbox["leased_by"]["exp_id"]
                for sandbox in state.get("sandboxes", [])
                if sandbox.get("leased_by")
            ]
            if leased:
                raise RuntimeError(
                    "cannot switch remote provider config while remote "
                    f"sandboxes are still leased: {', '.join(leased)}"
                )
        remote_state.init_state(
            root,
            provider=self.provider_name,
            provider_config=self.provider_config,
            state_key=self.state_key,
        )

    def _provision_sandbox(
        self,
        slot_id: int,
        *,
        root: Path | None = None,
        environment: EnvironmentSpec | None = None,
    ) -> SandboxHandle:
        """Call the provider to spin up a new container.

        The bearer token is generated here and held in process memory only.
        With an environment manifest, its image and environment variables
        are passed to the provider.  Without one, the historical defaults
        remain unchanged.
        """
        token = secrets.token_urlsafe(32)
        if environment is None and root is not None:
            environment = self._environment_for_root(root)
        spec = SandboxSpec(
            image_ref=(environment.image_ref if environment and environment.image_ref
                       else "evo-sandbox-base"),
            env=dict(environment.env) if environment else {},
            bearer_token=token,
            environment=environment,
        )
        handle = self.provider.provision(spec)
        # Use the handle's token, not the spec's. Manual provider returns
        # its own configured token (the user-managed sandbox-agent was
        # started with that token, not the freshly-generated one).
        self._tokens[slot_id] = handle.bearer_token
        return handle

    def client_for_node(self, root: Path, node: dict[str, Any]):
        """Return the provider-specific client for the sandbox leased by `node`.

        Used by cmd_run to route shell + fs ops through the provider's
        sandbox client. Re-hydrates the SandboxHandle from on-disk state if
        not in memory (different process; common because `evo new` and
        `evo run` are separate subprocess invocations from the agent).
        """
        slot_id = self._slot_for_exp(root, node["id"])
        if slot_id is None:
            raise RuntimeError(
                f"No sandbox leased by {node.get('id')!r}; "
                f"call backend.allocate() first."
            )
        handle = self._handle_for_slot(root, slot_id)
        if handle is None:
            raise RuntimeError(
                f"Sandbox slot {slot_id} for {node.get('id')!r} is missing "
                f"its provisioned handle in remote_state. Re-allocate via "
                f"`evo discard {node['id']} --reason ...` + "
                f"`evo new --parent ...`."
            )
        if not self.provider.is_alive(handle):
            raise RuntimeError(
                f"Sandbox for {node.get('id')!r} is no longer reachable. "
                f"Re-allocate via `evo discard {node['id']} --reason ...` + "
                f"`evo new --parent ...`."
            )
        return self.provider.build_client(handle)

    def _setup_workspace(
        self,
        ctx: AllocateCtx,
        handle: SandboxHandle | None,
        slot_id: int,
        *,
        environment: EnvironmentSpec | None = None,
    ) -> Path:
        """Ship parent commit into the sandbox + checkout the experiment branch.

        Steps:
          1. Ensure the in-sandbox workspace exists and is a git repo.
             The workspace path comes from handle.metadata["workspace_root"]
             when set (manual provider configures this for non-/workspace
             host filesystems); otherwise defaults to /workspace/repo.
          2. Ship parent commit via git bundle.
          3. Check out the experiment's branch at parent commit.

        Returns the in-sandbox workspace path. In remote mode there's no
        separate `git worktree`; the experiment's branch is checked out
        in place in the cloned repo.
        """
        from ..git_bundle import (
            SANDBOX_REPO_ROOT, SANDBOX_BUNDLE_DIR,
            ship_commit_to_sandbox,
        )

        if handle is None:
            raise RuntimeError(
                "_setup_workspace called without a SandboxHandle; "
                "indicates a backend ordering bug."
            )
        meta = handle.metadata or {}
        workspace_root = meta.get("workspace_root", SANDBOX_REPO_ROOT)
        bundle_dir = meta.get("bundle_dir", SANDBOX_BUNDLE_DIR)
        client = self.provider.build_client(handle)
        with client:
            # 1. Ensure the in-sandbox repo dir exists and is a git repo.
            client.fs_mkdir(workspace_root, recursive=True)
            init_check = client.process_run(
                "git", args=["rev-parse", "--git-dir"], cwd=workspace_root,
            )
            if self._result_exit_code(init_check) != 0:
                # Fresh sandbox: init the repo + set committer identity for
                # any subsequent in-sandbox commits.
                init_result = client.process_run(
                    "git", args=["init", "-q"], cwd=workspace_root,
                )
                if self._result_exit_code(init_result) != 0:
                    raise RuntimeError(
                        f"git init failed in sandbox: "
                        f"{self._result_stderr(init_result)[:500]}"
                    )
                client.process_run(
                    "git", args=["config", "user.email", "evo@sandbox"],
                    cwd=workspace_root,
                )
                client.process_run(
                    "git", args=["config", "user.name", "evo"],
                    cwd=workspace_root,
                )

            # 2. Ship the parent commit. Skip if already there (re-leased
            # sandbox case, common when keep_warm lands).
            cat_check = client.process_run(
                "git", args=["cat-file", "-e", ctx.parent_commit],
                cwd=workspace_root,
            )
            if self._result_exit_code(cat_check) != 0:
                ship_commit_to_sandbox(
                    client, local_repo=ctx.root, commit=ctx.parent_commit,
                    sandbox_repo=workspace_root, bundle_dir=bundle_dir,
                )

            # 3. Check out the experiment's branch at parent commit.
            checkout = client.process_run(
                "git",
                args=["checkout", "-B", ctx.branch, ctx.parent_commit],
                cwd=workspace_root,
            )
            if self._result_exit_code(checkout) != 0:
                raise RuntimeError(
                    f"git checkout -B {ctx.branch} {ctx.parent_commit} "
                    f"failed in sandbox: {self._result_stderr(checkout)[:500]}"
                )

            if environment is not None:
                evidence = self._apply_environment(
                    client, workspace_root, environment, handle.metadata or {}
                )
            else:
                evidence = None

        # Persist on the slot's state record so cmd_run can read the same
        # path via the backend client without re-fetching the handle.
        with remote_state.locked_state(ctx.root, self.state_key) as state:
            for sandbox in state["sandboxes"]:
                if sandbox["id"] == slot_id:
                    sandbox["workspace_root"] = workspace_root
                    sandbox["bundle_dir"] = bundle_dir
                    if environment is not None and evidence is not None:
                        sandbox["environment_manifest"] = environment.to_envelope()
                        sandbox["environment_digest"] = environment.digest()
                        sandbox["environment_evidence"] = evidence.to_envelope()
                        sandbox["environment_identity"] = evidence.identity
                        state["environment_manifest"] = environment.to_envelope()
                        state["environment_digest"] = environment.digest()
                        state["environment_evidence"] = evidence.to_envelope()
                        state["environment_identity"] = evidence.identity
                    break
        return Path(workspace_root)

    def _environment_for_root(self, root: Path | None) -> EnvironmentSpec | None:
        if root is None:
            return None
        return EnvironmentSpec.from_config(self.provider_config, root=root)

    def _apply_environment(
        self,
        client: Any,
        workspace_root: str,
        environment: EnvironmentSpec,
        adapter_metadata: dict[str, Any],
    ) -> EnvironmentEvidence:
        """Upload fixtures and run the manifest commands inside the sandbox."""
        if environment.fixtures:
            client.fs_upload_batch(workspace_root, environment.fixture_tar())

        for command in (*environment.setup_commands, *environment.customize_commands):
            self._run_environment_command(client, command, workspace_root, environment)

        identity_result = self._run_environment_command(
            client, environment.identity_command, workspace_root, environment
        )
        identity = self._identity_from_result(identity_result)
        returned_evidence = self._evidence_from_identity(identity)
        if returned_evidence is not None:
            return EnvironmentEvidence(
                digest=returned_evidence.digest or environment.digest(),
                identity=returned_evidence.identity,
                adapter_metadata={
                    **adapter_metadata,
                    **returned_evidence.adapter_metadata,
                },
                identity_command=returned_evidence.identity_command,
            )
        return EnvironmentEvidence(
            digest=environment.digest(),
            identity=identity,
            adapter_metadata=dict(adapter_metadata),
            identity_command=(
                list(environment.identity_command)
                if isinstance(environment.identity_command, tuple)
                else environment.identity_command
            ),
        )

    @staticmethod
    def _run_environment_command(
        client: Any,
        command: str | tuple[str, ...],
        cwd: str,
        environment: EnvironmentSpec,
    ) -> Any:
        if isinstance(command, tuple):
            executable, *args = command
            result = client.process_run(
                executable, args=args, cwd=cwd, env=dict(environment.env)
            )
        else:
            result = client.process_run(
                "/bin/sh", args=["-lc", command], cwd=cwd, env=dict(environment.env)
            )
        exit_code = RemoteSandboxBackend._result_exit_code(result)
        if exit_code != 0:
            stderr = RemoteSandboxBackend._result_stderr(result)
            raise RuntimeError(f"environment command failed ({command!r}): {stderr[:500]}")
        return result

    @staticmethod
    def _result_exit_code(result: Any) -> int | None:
        """Read a process-run result's exit code across shapes.

        Sandbox clients are inconsistent: some return dicts
        (`{"exitCode": ...}`, camelCase), some return objects
        (`.exit_code`). Tolerate both so callers don't AttributeError on a
        provider whose `process_run` returns a dict.
        """
        if isinstance(result, dict):
            return result.get("exitCode")
        return getattr(result, "exit_code", None)

    @staticmethod
    def _result_stderr(result: Any) -> str:
        """Read a process-run result's stderr across dict/object shapes."""
        if isinstance(result, dict):
            return str(result.get("stderr", ""))
        return str(getattr(result, "stderr", ""))

    @staticmethod
    def _identity_from_result(result: Any) -> str:
        if isinstance(result, dict):
            stdout = str(result.get("stdout", ""))
            stderr = str(result.get("stderr", ""))
        else:
            stdout = str(getattr(result, "stdout", ""))
            stderr = str(getattr(result, "stderr", ""))
        return (stdout.strip() or stderr.strip()).strip()

    @staticmethod
    def _evidence_from_identity(identity: str) -> EnvironmentEvidence | None:
        if not identity:
            return None
        try:
            value = json.loads(identity)
        except (TypeError, ValueError):
            return None
        if not isinstance(value, dict) or value.get("kind") != "evidence":
            return None
        try:
            return EnvironmentEvidence.from_envelope(value)
        except ValueError:
            return None

    def _slot_for_exp(self, root: Path, exp_id: str) -> int | None:
        """Return the slot id currently leased by `exp_id`, or None."""
        try:
            state = remote_state.read_state(root, self.state_key)
        except FileNotFoundError:
            return None
        for sandbox in state["sandboxes"]:
            lease = sandbox.get("leased_by")
            if lease and lease.get("exp_id") == exp_id:
                return sandbox["id"]
        return None

    def _release_if_matches(self, root: Path, slot_id: int, exp_id: str) -> None:
        """Atomically release the lease on `slot_id` only if it's currently
        held by `exp_id`. Mirror of pool._release_if_matches (pool.py:240-246).
        """
        with remote_state.locked_state(root, self.state_key) as state:
            for sandbox in state["sandboxes"]:
                if sandbox["id"] == slot_id:
                    lease = sandbox.get("leased_by")
                    if lease and lease.get("exp_id") == exp_id:
                        sandbox["leased_by"] = None
                    break

    def _handle_for_slot(self, root: Path, slot_id: int) -> SandboxHandle | None:
        handle = self._handles.get(slot_id)
        if handle is not None:
            return handle
        try:
            state = remote_state.read_state(root, self.state_key)
        except FileNotFoundError:
            return None
        sandbox = next((s for s in state["sandboxes"] if s["id"] == slot_id), None)
        return self._handle_from_record(sandbox)

    def _handle_from_record(
        self, sandbox_record: dict[str, Any] | None
    ) -> SandboxHandle | None:
        if sandbox_record is None or not sandbox_record.get("base_url"):
            return None
        slot_id = sandbox_record["id"]
        handle = SandboxHandle(
            provider=self.provider_name,
            base_url=sandbox_record["base_url"],
            bearer_token=sandbox_record.get("bearer_token", ""),
            native_id=sandbox_record.get("native_id") or f"slot-{slot_id}",
            metadata=sandbox_record.get("metadata") or {},
        )
        self._handles[slot_id] = handle
        self._tokens[slot_id] = handle.bearer_token
        return handle

    def _reconcile_orphaned(self, root: Path) -> None:
        """Clear leases whose owning process can no longer be using them.

        Mirror of pool._reconcile_orphaned_leases (pool.py:249-270). Defends
        the crash window between `_mark_committed` and `release_lease` in
        `cli.cmd_run`: if the process dies after the graph update but before
        the lease release, the slot would otherwise be pinned forever.

        Two independent reclaim conditions:

        1. The owning experiment reached an explicit terminal graph status. A
           missing node is NOT treated as terminal -- that masks real bugs
           (e.g. a partial graph write would look like a leaked lease).

        2. The owning process is provably gone: the lease was taken on THIS
           host (a pid is host-local, so a cross-host pid is meaningless), its
           pid is no longer alive, and it is older than the stale threshold.
           This covers a crash that never reached a terminal status, which
           clause 1 alone would leave pinned forever. A freed lease keeps its
           sandbox record, so the next `_claim_slot` REUSES the live container
           (see the rehydration there) instead of leaking a duplicate.
        """
        from ..core import load_graph

        try:
            graph = load_graph(root)
        except FileNotFoundError:
            return

        terminal = {"committed", "discarded"}
        this_host = _this_host()
        try:
            stale_seconds = int(
                os.environ.get("EVO_LEASE_STALE_SECONDS", str(_DEFAULT_LEASE_STALE_SECONDS))
            )
        except ValueError:
            stale_seconds = _DEFAULT_LEASE_STALE_SECONDS
        with remote_state.locked_state(root, self.state_key) as state_locked:
            for sandbox in state_locked["sandboxes"]:
                lease = sandbox.get("leased_by")
                if not lease:
                    continue
                exp_id = lease.get("exp_id")
                node = graph["nodes"].get(exp_id)
                if node is not None and node.get("status") in terminal:
                    sandbox["leased_by"] = None
                    continue
                lease_pid = lease.get("pid")
                age = _lease_age_seconds(lease.get("leased_at"))
                if (
                    lease.get("host") == this_host
                    and isinstance(lease_pid, int)
                    and not _pid_alive(lease_pid)
                    and age is not None
                    and age >= stale_seconds
                ):
                    sandbox["leased_by"] = None
