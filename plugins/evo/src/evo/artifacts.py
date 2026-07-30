"""Content-addressed code and fixture shuttle.

The shuttle deliberately has a small, file-system-only interface.  A stored
artifact consists of a SHA-256 addressed manifest and SHA-256 addressed file
objects.  Directory manifests contain sorted relative paths and therefore do
not depend on traversal order, host paths, or archive metadata.

Symlinks are rejected at every boundary.  This is stricter than copying a
symlink as a symlink, but makes restore, patching, and script staging safe in
the presence of untrusted fixtures.  Writes go through a temporary sibling
and ``os.replace`` wherever an in-place write is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Sequence


FORMAT = "evo-artifact-v1"
MAX_DIFF_BYTES = 4 * 1024 * 1024
MAX_TRANSFORM_FILES = 512
MAX_TRANSFORM_BYTES = 64 * 1024 * 1024
# Ingest bounds mirror the transform bounds above: an imported archive must not
# be able to exhaust memory before its hashes are ever checked.  A single member
# is capped at one transform's worth of bytes, the member count leaves headroom
# above MAX_TRANSFORM_FILES (an archive carries one object plus manifests per
# file), and the total caps aggregate uncompressed bytes against a tar bomb.
MAX_IMPORT_MEMBERS = 8 * MAX_TRANSFORM_FILES
MAX_IMPORT_MEMBER_BYTES = MAX_TRANSFORM_BYTES
MAX_IMPORT_TOTAL_BYTES = 4 * MAX_TRANSFORM_BYTES


class ArtifactError(RuntimeError):
    """Raised when an artifact or workspace fails validation."""


@dataclass(frozen=True)
class SwapResult:
    artifact: str
    backup: str
    target: str

    def as_dict(self) -> dict[str, str]:
        return {"artifact": self.artifact, "backup": self.backup, "target": self.target}


@dataclass(frozen=True)
class TransformLimits:
    max_bytes: int = MAX_DIFF_BYTES
    max_files: int = MAX_TRANSFORM_FILES
    max_output_bytes: int = MAX_TRANSFORM_BYTES
    timeout_seconds: int = 30


@dataclass(frozen=True)
class ImportLimits:
    max_members: int = MAX_IMPORT_MEMBERS
    max_member_bytes: int = MAX_IMPORT_MEMBER_BYTES
    max_total_bytes: int = MAX_IMPORT_TOTAL_BYTES


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _language_for_name(name: str) -> str:
    """Classify a source name without inspecting its contents."""
    lower = name.lower()
    if lower.endswith((".py", ".pyi", ".pyw")) or lower in {"pyproject.toml", "setup.py", "requirements.txt"}:
        return "python"
    if lower.endswith(".rs") or lower in {"cargo.toml", "cargo.lock"}:
        return "rust"
    return "mixed"


def _combine_languages(languages: Iterable[str]) -> str:
    values = set(languages)
    if not values or "mixed" in values or len(values) > 1:
        return "mixed"
    return next(iter(values))


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _atomic_write(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Write ``data`` and publish it with an atomic sibling replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp, mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _reject_symlink(path: Path, *, label: str) -> None:
    try:
        if path.is_symlink():
            raise ArtifactError(f"{label} may not be a symlink: {path}")
    except OSError as exc:
        raise ArtifactError(f"cannot inspect {label} {path}: {exc}") from exc


def _ensure_directory(path: Path, *, label: str) -> Path:
    path = Path(path)
    _reject_symlink(path, label=label)
    if path.exists():
        if not path.is_dir():
            raise ArtifactError(f"{label} is not a directory: {path}")
        return path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_relative(raw: str | os.PathLike[str], *, allow_dot: bool = False) -> str:
    """Return a normalized workspace-relative POSIX path or reject it."""
    value = os.fspath(raw)
    if not isinstance(value, str):
        value = os.fsdecode(value)
    if "\\" in value:
        raise ArtifactError(f"backslash is not allowed in artifact paths: {value!r}")
    posix = PurePosixPath(value)
    if posix.is_absolute() or PureWindowsPath(value).is_absolute() or PureWindowsPath(value).drive:
        raise ArtifactError(f"absolute artifact path is not allowed: {value!r}")
    parts = posix.parts
    if not parts or (parts == (".",) and allow_dot):
        return "."
    if any(part in ("", ".", "..") for part in parts):
        raise ArtifactError(f"unsafe artifact path: {value!r}")
    return "/".join(parts)


def _workspace_path(workspace: Path, relative: str | os.PathLike[str], *, allow_dot: bool = True) -> Path:
    workspace = Path(workspace)
    _ensure_directory(workspace, label="workspace")
    safe = _safe_relative(relative, allow_dot=allow_dot)
    candidate = workspace if safe == "." else workspace.joinpath(*safe.split("/"))
    # Check every existing component, including the leaf, without resolving a
    # symlink into an unrelated tree.
    current = workspace
    for part in () if safe == "." else safe.split("/"):
        current = current / part
        _reject_symlink(current, label="workspace path")
    return candidate


def _check_source_tree(path: Path) -> None:
    """Validate and reject symlinks before reading any source bytes."""
    _reject_symlink(path, label="source")
    if path.is_file():
        return
    if not path.is_dir():
        raise ArtifactError(f"source does not exist or is not a file/directory: {path}")
    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
        root_path = Path(root)
        for name in list(dirs) + list(files):
            child = root_path / name
            _reject_symlink(child, label="source entry")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _object_path(root: Path, digest: str) -> Path:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ArtifactError(f"invalid SHA-256 digest: {digest!r}")
    return root / "objects" / digest


def _manifest_path(root: Path, digest: str) -> Path:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ArtifactError(f"invalid manifest digest: {digest!r}")
    return root / "manifests" / f"{digest}.json"


class ArtifactStore:
    """A local content-addressed store for files and directory trees."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        _reject_symlink(self.root, label="artifact store")

    def _prepare(self) -> None:
        _ensure_directory(self.root, label="artifact store")
        _ensure_directory(self.root / "objects", label="object store")
        _ensure_directory(self.root / "manifests", label="manifest store")

    def _put_object(self, data: bytes) -> str:
        digest = _sha256(data)
        destination = _object_path(self.root, digest)
        if destination.exists():
            _reject_symlink(destination, label="stored object")
            if destination.read_bytes() != data:
                raise ArtifactError(f"content-addressed object collision: {digest}")
        else:
            _atomic_write(destination, data, mode=0o644)
        return digest

    def _put_manifest(self, manifest: dict[str, Any]) -> str:
        payload = _canonical_json(manifest)
        digest = _sha256(payload)
        destination = _manifest_path(self.root, digest)
        if destination.exists():
            _reject_symlink(destination, label="stored manifest")
            if destination.read_bytes() != payload:
                raise ArtifactError(f"manifest collision: {digest}")
        else:
            _atomic_write(destination, payload, mode=0o644)
        return digest

    def store(self, source: Path | str) -> str:
        source_path = Path(source)
        _check_source_tree(source_path)
        self._prepare()
        return self._store_path(source_path)

    put = store

    def _store_path(self, source: Path) -> str:
        if source.is_file():
            data = source.read_bytes()
            blob = self._put_object(data)
            return self._put_manifest(
                {
                    "format": FORMAT,
                    "kind": "file",
                    "language": _language_for_name(source.name),
                    "mode": _mode(source),
                    "size": len(data),
                    "sha256": blob,
                }
            )

        entries: list[dict[str, Any]] = []
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            _reject_symlink(child, label="source entry")
            if child.is_file():
                data = child.read_bytes()
                entries.append(
                    {
                        "kind": "file",
                        "language": _language_for_name(child.name),
                        "mode": _mode(child),
                        "path": child.name,
                        "sha256": self._put_object(data),
                        "size": len(data),
                    }
                )
            elif child.is_dir():
                child_digest = self._store_path(child)
                child_language = self.read_manifest(child_digest)["language"]
                entries.append(
                    {
                        "kind": "directory",
                        "language": child_language,
                        "mode": _mode(child),
                        "path": child.name,
                        "manifest": child_digest,
                    }
                )
            else:
                raise ArtifactError(f"unsupported source entry: {child}")
        return self._put_manifest(
            {
                "format": FORMAT,
                "kind": "directory",
                "language": _combine_languages(entry["language"] for entry in entries),
                "mode": _mode(source),
                "entries": entries,
            }
        )

    def read_manifest(self, digest: str) -> dict[str, Any]:
        path = _manifest_path(self.root, digest)
        _reject_symlink(path, label="manifest")
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ArtifactError(f"manifest not found: {digest}") from exc
        if _sha256(payload) != digest:
            raise ArtifactError(f"manifest hash mismatch: {path}")
        try:
            manifest = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ArtifactError(f"invalid manifest: {path}") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise ArtifactError(f"unsupported artifact manifest: {digest}")
        if manifest.get("language") not in {"python", "rust", "mixed"}:
            raise ArtifactError("manifest language must be python, rust, or mixed")
        self._validate_manifest(manifest, seen=set())
        return manifest

    def _read_object(self, digest: str, expected_size: int | None = None) -> bytes:
        path = _object_path(self.root, digest)
        _reject_symlink(path, label="object")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ArtifactError(f"object not found: {digest}") from exc
        if _sha256(data) != digest:
            raise ArtifactError(f"object hash mismatch: {path}")
        if expected_size is not None and len(data) != expected_size:
            raise ArtifactError(f"object size mismatch: {digest}")
        return data

    def _validate_manifest(self, manifest: dict[str, Any], *, seen: set[str]) -> None:
        kind = manifest.get("kind")
        if kind == "file":
            digest = manifest.get("sha256")
            if not isinstance(digest, str):
                raise ArtifactError("file manifest has no object digest")
            self._read_object(digest, int(manifest.get("size", -1)))
            return
        if kind != "directory" or not isinstance(manifest.get("entries"), list):
            raise ArtifactError("malformed directory manifest")
        paths: list[str] = []
        for entry in manifest["entries"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ArtifactError("malformed directory entry")
            if entry.get("language") not in {"python", "rust", "mixed"}:
                raise ArtifactError("directory entry language must be python, rust, or mixed")
            path = _safe_relative(entry["path"], allow_dot=False)
            paths.append(path)
            if entry.get("kind") == "file":
                self._read_object(entry.get("sha256", ""), int(entry.get("size", -1)))
            elif entry.get("kind") == "directory":
                child_digest = entry.get("manifest")
                if not isinstance(child_digest, str) or child_digest in seen:
                    raise ArtifactError("invalid or cyclic directory manifest")
                seen.add(child_digest)
                self._validate_manifest(self.read_manifest(child_digest), seen=seen)
            else:
                raise ArtifactError("unsupported directory entry kind")
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ArtifactError("directory manifest entries are not deterministic")

    def _collect_manifests(self, digest: str, output: dict[str, bytes], seen: set[str] | None = None) -> None:
        seen = set() if seen is None else seen
        if digest in seen:
            return
        seen.add(digest)
        manifest = self.read_manifest(digest)
        payload = _canonical_json(manifest)
        output[digest] = payload
        if manifest["kind"] == "directory":
            for entry in manifest["entries"]:
                if entry["kind"] == "directory":
                    self._collect_manifests(entry["manifest"], output, seen)

    def export(self, digest: str, destination: Path | str) -> Path:
        manifests: dict[str, bytes] = {}
        self._collect_manifests(digest, manifests)
        members: dict[str, bytes] = {}
        for manifest_digest, payload in manifests.items():
            members[f"manifests/{manifest_digest}.json"] = payload
            manifest = json.loads(payload)
            entries: Iterable[dict[str, Any]] = manifest.get("entries", []) if manifest["kind"] == "directory" else [manifest]
            for entry in entries:
                if entry["kind"] == "file":
                    object_digest = entry["sha256"]
                    members[f"objects/{object_digest}"] = self._read_object(object_digest)
        # A plain tar is intentionally used: fixed TarInfo metadata makes it
        # byte-for-byte deterministic and avoids gzip timestamps.
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_tmp = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent))
        tmp = Path(raw_tmp)
        try:
            with os.fdopen(fd, "wb") as raw:
                with tarfile.open(fileobj=raw, mode="w") as archive:
                    for name in sorted(members):
                        info = tarfile.TarInfo(name)
                        info.size = len(members[name])
                        info.mode = 0o644
                        info.mtime = 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        archive.addfile(info, __import__("io").BytesIO(members[name]))
                raw.flush()
                os.fsync(raw.fileno())
            os.replace(tmp, destination)
        except BaseException:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise
        return destination

    def import_artifact(self, archive_path: Path | str, *, limits: ImportLimits | None = None) -> str:
        limits = limits or ImportLimits()
        archive_path = Path(archive_path)
        _reject_symlink(archive_path, label="artifact archive")
        manifests: dict[str, bytes] = {}
        objects: dict[str, bytes] = {}
        member_count = 0
        total_bytes = 0
        try:
            with tarfile.open(archive_path, mode="r:") as archive:
                # Iterate lazily so a bomb with millions of members fails before
                # the full index is even materialized.
                for member in archive:
                    if not member.isfile() or member.issym() or member.islnk():
                        raise ArtifactError("artifact archive may contain regular files only")
                    member_count += 1
                    if member_count > limits.max_members:
                        raise ArtifactError("artifact archive member limit exceeded")
                    # Enforce the declared size from the header before reading a
                    # single byte of payload into memory.
                    declared = int(member.size)
                    if declared < 0 or declared > limits.max_member_bytes:
                        raise ArtifactError("artifact archive member exceeds size limit")
                    total_bytes += declared
                    if total_bytes > limits.max_total_bytes:
                        raise ArtifactError("artifact archive exceeds total size limit")
                    safe_name = _safe_archive_name(member.name)
                    if safe_name in manifests or safe_name in objects:
                        raise ArtifactError(f"duplicate artifact archive member: {safe_name}")
                    content_file = archive.extractfile(member)
                    if content_file is None:
                        raise ArtifactError(f"cannot read archive member: {safe_name}")
                    # A header may under-declare its payload; bound the read to
                    # the size we already accounted for and reject any overflow.
                    content = content_file.read(declared + 1)
                    if len(content) > declared:
                        raise ArtifactError("artifact archive member exceeds declared size")
                    if safe_name.startswith("manifests/") and safe_name.endswith(".json"):
                        manifests[safe_name] = content
                    elif safe_name.startswith("objects/"):
                        objects[safe_name] = content
                    else:
                        raise ArtifactError(f"unexpected artifact archive member: {safe_name}")
        except (tarfile.TarError, OSError) as exc:
            raise ArtifactError(f"invalid artifact archive: {archive_path}") from exc

        self._prepare()
        for name, content in objects.items():
            digest = name.removeprefix("objects/")
            if _sha256(content) != digest:
                raise ArtifactError(f"artifact object hash mismatch: {digest}")
            self._put_object(content)
        root: str | None = None
        for name, content in manifests.items():
            digest = name.removeprefix("manifests/").removesuffix(".json")
            if _sha256(content) != digest:
                raise ArtifactError(f"artifact manifest hash mismatch: {digest}")
            manifest = json.loads(content)
            if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
                raise ArtifactError("unsupported artifact manifest in archive")
            self._put_manifest(manifest)
        manifest_digests = {
            name.removeprefix("manifests/").removesuffix(".json") for name in manifests
        }
        referenced = {
            entry["manifest"]
            for content in manifests.values()
            for entry in json.loads(content).get("entries", [])
            if isinstance(entry, dict) and entry.get("kind") == "directory"
        }
        roots = sorted(manifest_digests - referenced)
        if len(roots) != 1:
            raise ArtifactError("artifact archive must contain exactly one root manifest")
        root = roots[0]
        if root is None:
            raise ArtifactError("artifact archive contains no manifest")
        # Validate after all members are installed, including nested manifests.
        self.read_manifest(root)
        return root

    def restore(self, digest: str, workspace: Path | str, target: str = ".") -> Path:
        manifest = self.read_manifest(digest)
        workspace_path = _ensure_directory(Path(workspace), label="workspace")
        target_path = _workspace_path(workspace_path, target)
        staged_parent = workspace_path.parent
        staged = Path(tempfile.mkdtemp(prefix=f".evo-restore-{digest[:12]}-", dir=str(staged_parent)))
        stage_target = staged / "payload"
        try:
            self._materialize(manifest, stage_target)
            _replace_path_atomically(stage_target, target_path)
            shutil.rmtree(staged, ignore_errors=True)
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        return target_path

    def _materialize(self, manifest: dict[str, Any], destination: Path) -> None:
        if manifest["kind"] == "file":
            data = self._read_object(manifest["sha256"], int(manifest["size"]))
            _atomic_write(destination, data, mode=int(manifest.get("mode", 0o644)))
            return
        destination.mkdir(parents=True, exist_ok=False)
        os.chmod(destination, int(manifest.get("mode", 0o755)) & 0o7777)
        for entry in manifest["entries"]:
            child = destination / entry["path"]
            if entry["kind"] == "file":
                data = self._read_object(entry["sha256"], int(entry["size"]))
                _atomic_write(child, data, mode=int(entry.get("mode", 0o644)))
            else:
                self._materialize(self.read_manifest(entry["manifest"]), child)

    def swap(self, digest: str, workspace: Path | str, target: str = ".") -> SwapResult:
        workspace_path = _ensure_directory(Path(workspace), label="workspace")
        target_path = _workspace_path(workspace_path, target)
        if not target_path.exists():
            raise ArtifactError(f"swap target does not exist: {target_path}")
        backup = self.store(target_path)
        self.restore(digest, workspace_path, target)
        return SwapResult(artifact=digest, backup=backup, target=str(target_path))


def _safe_archive_name(name: str) -> str:
    if "\\" in name:
        raise ArtifactError(f"unsafe archive member: {name!r}")
    if name.startswith("/"):
        raise ArtifactError(f"absolute archive member: {name!r}")
    parts = PurePosixPath(name).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ArtifactError(f"unsafe archive member: {name!r}")
    return "/".join(parts)


def _replace_path_atomically(staged: Path, target: Path) -> None:
    """Replace a file or tree while retaining a rollback name until success."""
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink(parent, label="target parent")
    old: Path | None = None
    if target.exists() or target.is_symlink():
        _reject_symlink(target, label="restore target")
        fd, raw_old = tempfile.mkstemp(prefix=f".{target.name}.old-", dir=str(parent))
        os.close(fd)
        old = Path(raw_old)
        old.unlink()
        os.replace(target, old)
    try:
        os.replace(staged, target)
    except BaseException:
        if old is not None and not target.exists():
            os.replace(old, target)
        raise
    if old is not None:
        if old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
        else:
            old.unlink(missing_ok=True)


def _read_text_bytes(path: Path) -> tuple[str, bytes]:
    data = path.read_bytes()
    try:
        return data.decode("utf-8"), data
    except UnicodeDecodeError as exc:
        raise ArtifactError(f"unified diff target is not UTF-8 text: {path}") from exc


def _patch_path(raw: str) -> str | None:
    raw = raw.strip().split("\t", 1)[0]
    if raw == "/dev/null":
        return None
    if raw.startswith("a/") or raw.startswith("b/"):
        raw = raw[2:]
    return _safe_relative(raw, allow_dot=False)


def _apply_unified_diff_text(workspace: Path, diff: str, *, limits: TransformLimits) -> dict[str, bytes | None]:
    lines = diff.splitlines(keepends=True)
    changes: dict[str, bytes | None] = {}
    index = 0
    file_count = 0
    hunk_count = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise ArtifactError("unified diff has an incomplete file header")
        old_path = _patch_path(lines[index][4:])
        new_path = _patch_path(lines[index + 1][4:])
        if old_path is None and new_path is None:
            raise ArtifactError("unified diff file has no target")
        if old_path and new_path and old_path != new_path:
            raise ArtifactError("renames are not supported by bounded transforms")
        path = new_path or old_path
        assert path is not None
        file_count += 1
        if file_count > limits.max_files:
            raise ArtifactError("unified diff file limit exceeded")
        target = _workspace_path(workspace, path, allow_dot=False)
        if old_path is None:
            original: list[str] = []
        else:
            if not target.exists():
                raise ArtifactError(f"unified diff target does not exist: {path}")
            _reject_symlink(target, label="unified diff target")
            text, _ = _read_text_bytes(target)
            original = text.splitlines(keepends=True)
        output: list[str] = []
        cursor = 0
        index += 2
        while index < len(lines) and not lines[index].startswith("--- "):
            line = lines[index]
            if line.startswith("diff ") or line.startswith("index "):
                index += 1
                continue
            if not line.startswith("@@ "):
                raise ArtifactError(f"unexpected unified diff line: {line.rstrip()!r}")
            try:
                header = line.split("@@", 2)[1].strip()
                old_spec, new_spec = header.split(" ", 1)
                old_start = int(old_spec.split(",", 1)[0].removeprefix("-"))
                new_start = int(new_spec.split(",", 1)[0].removeprefix("+"))
            except (ValueError, IndexError) as exc:
                raise ArtifactError(f"invalid unified diff hunk header: {line.rstrip()!r}") from exc
            del new_start  # validated for syntax; context is applied sequentially.
            hunk_count += 1
            if hunk_count > limits.max_files * 16:
                raise ArtifactError("unified diff hunk limit exceeded")
            desired_cursor = max(old_start - 1, 0)
            if desired_cursor < cursor or desired_cursor > len(original):
                raise ArtifactError("unified diff hunk is outside target")
            output.extend(original[cursor:desired_cursor])
            cursor = desired_cursor
            index += 1
            while index < len(lines) and not lines[index].startswith("@@ ") and not lines[index].startswith("--- "):
                hunk_line = lines[index]
                if hunk_line.startswith("\\ No newline at end of file"):
                    index += 1
                    continue
                if not hunk_line or hunk_line[0] not in " +-":
                    raise ArtifactError(f"invalid unified diff body line: {hunk_line.rstrip()!r}")
                payload = hunk_line[1:]
                if hunk_line[0] == " ":
                    if cursor >= len(original) or original[cursor] != payload:
                        raise ArtifactError(f"unified diff context mismatch in {path}")
                    output.append(original[cursor])
                    cursor += 1
                elif hunk_line[0] == "-":
                    if cursor >= len(original) or original[cursor] != payload:
                        raise ArtifactError(f"unified diff removal mismatch in {path}")
                    cursor += 1
                else:
                    output.append(payload)
                index += 1
        output.extend(original[cursor:])
        if new_path is None:
            changes[path] = None
        else:
            encoded = "".join(output).encode("utf-8")
            if len(encoded) > limits.max_output_bytes:
                raise ArtifactError("unified diff output limit exceeded")
            changes[path] = encoded
    return changes


def apply_diff(workspace: Path | str, diff: Path | str | bytes, *, limits: TransformLimits | None = None) -> list[str]:
    """Apply a bounded, path-checked unified diff inside ``workspace``."""
    limits = limits or TransformLimits()
    workspace_path = _ensure_directory(Path(workspace), label="workspace")
    if isinstance(diff, Path):
        diff_bytes = diff.read_bytes()
    elif isinstance(diff, str):
        try:
            diff_path = Path(diff)
            diff_bytes = diff_path.read_bytes() if diff_path.is_file() else diff.encode("utf-8")
        except OSError:
            diff_bytes = diff.encode("utf-8")
    elif isinstance(diff, bytes):
        diff_bytes = diff
    else:
        diff_bytes = os.fsencode(str(diff))
    if len(diff_bytes) > limits.max_bytes:
        raise ArtifactError("unified diff exceeds byte limit")
    try:
        diff_text = diff_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactError("unified diff must be UTF-8") from exc
    changes = _apply_unified_diff_text(workspace_path, diff_text, limits=limits)
    for relative, data in changes.items():
        target = _workspace_path(workspace_path, relative, allow_dot=False)
        if data is None:
            if target.exists():
                target.unlink()
        else:
            _atomic_write(target, data, mode=_mode(target) if target.exists() else 0o644)
    return sorted(changes)


def _copy_tree(source: Path, destination: Path) -> tuple[int, int]:
    _check_source_tree(source)
    files = 0
    total = 0
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, _mode(source))
    for child in sorted(source.iterdir(), key=lambda item: item.name):
        dest = destination / child.name
        if child.is_dir():
            child_files, child_bytes = _copy_tree(child, dest)
            files += child_files
            total += child_bytes
        else:
            data = child.read_bytes()
            _atomic_write(dest, data, mode=_mode(child))
            files += 1
            total += len(data)
    return files, total


def apply_script(
    workspace: Path | str,
    script: Path | str | Sequence[str],
    *,
    args: Sequence[str] = (),
    limits: TransformLimits | None = None,
) -> list[str]:
    """Run a trusted transform against a staged workspace and publish it.

    The script receives the staged workspace as its first argument and runs
    with that directory as cwd.  The original workspace is untouched unless
    the script exits successfully and the resulting tree contains no symlinks
    and remains within the declared size/file bounds.
    """
    limits = limits or TransformLimits()
    workspace_path = _ensure_directory(Path(workspace), label="workspace")
    _check_source_tree(workspace_path)
    stage_parent = workspace_path.parent
    stage = Path(tempfile.mkdtemp(prefix=".evo-script-stage-", dir=str(stage_parent)))
    try:
        staged_workspace = stage / "workspace"
        files, total = _copy_tree(workspace_path, staged_workspace)
        if files > limits.max_files or total > limits.max_output_bytes:
            raise ArtifactError("workspace exceeds transform bounds")
        if isinstance(script, (str, Path)):
            script_path = Path(script)
            if not script_path.is_absolute():
                script_path = Path.cwd() / script_path
            _reject_symlink(script_path, label="transform script")
            if not script_path.is_file():
                raise ArtifactError(f"transform script not found: {script_path}")
            command = [sys.executable, str(script_path), str(staged_workspace), *map(str, args)]
        else:
            command = [str(part) for part in script] + [str(staged_workspace), *map(str, args)]
            if not command:
                raise ArtifactError("empty transform command")
        proc = subprocess.run(
            command,
            cwd=str(staged_workspace),
            capture_output=True,
            text=True,
            timeout=limits.timeout_seconds,
            check=False,
        )
        if proc.returncode != 0:
            raise ArtifactError(f"transform failed (exit={proc.returncode}): {proc.stderr[-1000:]}")
        files, total = _count_tree(staged_workspace)
        if files > limits.max_files or total > limits.max_output_bytes:
            raise ArtifactError("transform output exceeds bounds")
        before = {p.relative_to(workspace_path).as_posix() for p in _all_paths(workspace_path)}
        after = {p.relative_to(staged_workspace).as_posix() for p in _all_paths(staged_workspace)}
        changed = sorted(before | after)
        replacement = stage / "replacement"
        os.replace(staged_workspace, replacement)
        _replace_path_atomically(replacement, workspace_path)
        return changed
    except subprocess.TimeoutExpired as exc:
        raise ArtifactError("transform timed out") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _all_paths(root: Path) -> list[Path]:
    paths = [root]
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in sorted(dirs) + sorted(files):
            child = current_path / name
            _reject_symlink(child, label="workspace entry")
            paths.append(child)
    return paths


def _count_tree(root: Path) -> tuple[int, int]:
    paths = _all_paths(root)
    files = sum(1 for path in paths if path.is_file())
    total = sum(path.stat().st_size for path in paths if path.is_file())
    return files, total


def store(source: Path | str, store_root: Path | str) -> str:
    return ArtifactStore(store_root).store(source)


def export_artifact(digest: str, store_root: Path | str, destination: Path | str) -> Path:
    return ArtifactStore(store_root).export(digest, destination)


def import_artifact(archive: Path | str, store_root: Path | str, *, limits: ImportLimits | None = None) -> str:
    return ArtifactStore(store_root).import_artifact(archive, limits=limits)


def restore(digest: str, store_root: Path | str, workspace: Path | str, target: str = ".") -> Path:
    return ArtifactStore(store_root).restore(digest, workspace, target)


def swap(digest: str, store_root: Path | str, workspace: Path | str, target: str = ".") -> SwapResult:
    return ArtifactStore(store_root).swap(digest, workspace, target)


def _cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="content-addressed Evo code/fixture shuttle")
    sub = parser.add_subparsers(dest="command", required=True)

    def store_option(command: argparse.ArgumentParser) -> None:
        command.add_argument("--store", required=True, type=Path, help="content-addressed store directory")

    command = sub.add_parser("store", help="store a file or directory")
    command.add_argument("source", type=Path)
    store_option(command)

    command = sub.add_parser("export", help="export a stored artifact to a deterministic tar")
    command.add_argument("digest")
    command.add_argument("destination", type=Path)
    store_option(command)

    command = sub.add_parser("import", help="import an artifact tar")
    command.add_argument("archive", type=Path)
    store_option(command)

    for name, help_text in (("restore", "restore an artifact"), ("swap", "store a backup then restore an artifact")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("digest")
        command.add_argument("workspace", type=Path)
        command.add_argument("--target", default=".")
        store_option(command)

    command = sub.add_parser("apply-diff", help="apply a bounded unified diff")
    command.add_argument("workspace", type=Path)
    command.add_argument("diff", type=Path)
    command.add_argument("--max-bytes", type=int, default=MAX_DIFF_BYTES)

    command = sub.add_parser("apply-script", help="run a transform in a staged workspace")
    command.add_argument("workspace", type=Path)
    command.add_argument("script", type=Path)
    command.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _cli().parse_args(argv)
    try:
        if args.command == "store":
            result: Any = {"digest": store(args.source, args.store)}
        elif args.command == "export":
            result = {"archive": str(export_artifact(args.digest, args.store, args.destination))}
        elif args.command == "import":
            result = {"digest": import_artifact(args.archive, args.store)}
        elif args.command == "restore":
            result = {"path": str(restore(args.digest, args.store, args.workspace, args.target))}
        elif args.command == "swap":
            result = swap(args.digest, args.store, args.workspace, args.target).as_dict()
        elif args.command == "apply-diff":
            result = {"changed": apply_diff(args.workspace, args.diff, limits=TransformLimits(max_bytes=args.max_bytes))}
        else:
            result = {"changed": apply_script(args.workspace, args.script, args=args.args)}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ArtifactError, OSError, ValueError) as exc:
        print(f"evo-artifact: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
