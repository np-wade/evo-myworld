"""Versioned environment manifests shared by Python orchestration and runners.

The manifest is deliberately a small JSON envelope.  Python owns resolving
local fixture sources and orchestrating the sandbox, while another runner
(including the Rust runner) can consume ``EnvironmentSpec.to_envelope()`` and
return an ``EnvironmentEvidence`` envelope without needing Python types.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


ENVIRONMENT_SCHEMA = "evo.environment"
ENVIRONMENT_MANIFEST_VERSION = 1
ENVIRONMENT_EVIDENCE_VERSION = 1
DEFAULT_IDENTITY_COMMAND = "python --version"


def _as_string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise ValueError(f"environment manifest {field_name} must be a string or list")
    result = tuple(str(item) for item in value)
    if any(not item.strip() for item in result):
        raise ValueError(f"environment manifest {field_name} contains an empty command")
    return result


def _safe_fixture_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise ValueError(f"environment fixture path is unsafe: {path!r}")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"environment fixture path is unsafe: {path!r}")
    return "/".join(parts)


@dataclass(frozen=True)
class EnvironmentFixture:
    """One file injected below the sandbox workspace root."""

    path: str
    data: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _safe_fixture_path(self.path))
        object.__setattr__(self, "data", bytes(self.data))

    def to_manifest(self) -> dict[str, str]:
        try:
            content = self.data.decode("utf-8")
        except UnicodeDecodeError:
            return {
                "path": self.path,
                "content_base64": base64.b64encode(self.data).decode("ascii"),
            }
        return {"path": self.path, "content": content}


def _safe_fixture_source(source: Path, root: Path | None) -> Path:
    """Resolve a fixture ``source`` path and confine it to ``root``.

    This mirrors the strict traversal/symlink posture in ``evo.artifacts``:
    the source must resolve (via realpath, following any symlinks) to a real,
    regular file that stays inside the manifest root.  Absolute paths that
    escape the root, ``..`` traversal, and symlinks pointing outside the root
    are all rejected so a manifest cannot read arbitrary host files.
    """
    if root is None:
        raise ValueError(
            f"environment fixture source requires a manifest root: {str(source)!r}"
        )
    base = Path(root).resolve()
    candidate = source if source.is_absolute() else base / source
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"environment fixture source escapes root: {str(source)!r}")
    if not resolved.is_file():
        raise ValueError(
            f"environment fixture source is not a regular file: {str(source)!r}"
        )
    return resolved


def _fixture_from_value(path: str, value: Any, root: Path | None) -> EnvironmentFixture:
    if isinstance(value, Mapping):
        if "source" in value:
            source = _safe_fixture_source(Path(str(value["source"])), root)
            return EnvironmentFixture(path, source.read_bytes())
        if "content_base64" in value:
            return EnvironmentFixture(path, base64.b64decode(str(value["content_base64"])))
        value = value.get("content", "")
    if isinstance(value, bytes):
        data = value
    else:
        data = str(value).encode("utf-8")
    return EnvironmentFixture(path, data)


def _parse_fixtures(value: Any, root: Path | None) -> tuple[EnvironmentFixture, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return tuple(_fixture_from_value(str(path), item, root) for path, item in value.items())
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("environment manifest fixtures must be a mapping or list")
    fixtures: list[EnvironmentFixture] = []
    for item in value:
        if not isinstance(item, Mapping) or "path" not in item:
            raise ValueError("environment manifest fixture entries need a path")
        fixtures.append(_fixture_from_value(str(item["path"]), item, root))
    return tuple(fixtures)


@dataclass(frozen=True)
class EnvironmentSpec:
    """Resolved, content-addressed description of a sandbox environment."""

    image_ref: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    fixtures: tuple[EnvironmentFixture, ...] = ()
    setup_commands: tuple[str, ...] = ()
    customize_commands: tuple[str, ...] = ()
    identity_command: str | tuple[str, ...] = DEFAULT_IDENTITY_COMMAND

    @classmethod
    def from_manifest(
        cls, manifest: Mapping[str, Any], *, root: Path | None = None
    ) -> "EnvironmentSpec":
        raw: Mapping[str, Any] = manifest
        if manifest.get("kind") == "manifest" and "spec" in manifest:
            if manifest.get("schema") != ENVIRONMENT_SCHEMA:
                raise ValueError("unsupported environment manifest schema")
            if manifest.get("version") != ENVIRONMENT_MANIFEST_VERSION:
                raise ValueError(
                    f"unsupported environment manifest version: {manifest.get('version')!r}"
                )
            raw = manifest["spec"]
        elif "manifest" in manifest and isinstance(manifest["manifest"], Mapping):
            raw = manifest["manifest"]

        env_raw = raw.get("env", raw.get("environment", {})) or {}
        if not isinstance(env_raw, Mapping):
            raise ValueError("environment manifest env must be a mapping")
        env = {str(key): str(value) for key, value in env_raw.items()}
        identity = raw.get("identity_command", raw.get("identity", DEFAULT_IDENTITY_COMMAND))
        if isinstance(identity, Sequence) and not isinstance(identity, str):
            identity_value: str | tuple[str, ...] = tuple(str(item) for item in identity)
        else:
            identity_value = str(identity)
        if not identity_value or (isinstance(identity_value, str) and not identity_value.strip()):
            raise ValueError("environment manifest identity_command cannot be empty")
        return cls(
            image_ref=(str(raw["image_ref"]) if raw.get("image_ref") is not None else
                       (str(raw["image"]) if raw.get("image") is not None else None)),
            env=env,
            fixtures=_parse_fixtures(raw.get("fixtures"), root),
            setup_commands=_as_string_list(raw.get("setup_commands", raw.get("setup")), "setup_commands"),
            customize_commands=_as_string_list(
                raw.get("customize_commands", raw.get("customize", raw.get("customization"))),
                "customize_commands",
            ),
            identity_command=identity_value,
        )

    @classmethod
    def from_config(cls, config: Mapping[str, Any], *, root: Path) -> "EnvironmentSpec | None":
        raw = config.get("environment_manifest")
        if raw is None:
            raw = config.get("environment")
        if raw is None:
            return None
        if isinstance(raw, Mapping):
            return cls.from_manifest(raw, root=root)
        if isinstance(raw, Path) or isinstance(raw, str):
            text = str(raw)
            manifest_path = Path(text)
            if text.lstrip().startswith("{"):
                return cls.from_manifest(json.loads(text), root=root)
            if not manifest_path.is_absolute():
                manifest_path = root / manifest_path
            with manifest_path.open("r", encoding="utf-8") as handle:
                return cls.from_manifest(json.load(handle), root=root)
        raise ValueError("environment_manifest must be a JSON object or path")

    def _spec_payload(self) -> dict[str, Any]:
        identity: str | list[str]
        if isinstance(self.identity_command, tuple):
            identity = list(self.identity_command)
        else:
            identity = self.identity_command
        return {
            "image_ref": self.image_ref,
            "env": dict(sorted(self.env.items())),
            "fixtures": [fixture.to_manifest() for fixture in self.fixtures],
            "setup_commands": list(self.setup_commands),
            "customize_commands": list(self.customize_commands),
            "identity_command": identity,
        }

    def to_envelope(self) -> dict[str, Any]:
        return {
            "schema": ENVIRONMENT_SCHEMA,
            "version": ENVIRONMENT_MANIFEST_VERSION,
            "kind": "manifest",
            "spec": self._spec_payload(),
        }

    # ``to_manifest`` is intentionally an alias for callers that use the
    # shorter persisted-manifest terminology.
    to_manifest = to_envelope

    def digest(self) -> str:
        encoded = json.dumps(
            self.to_envelope(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def fixture_tar(self) -> bytes:
        """Return a deterministic tar stream for ``fs_upload_batch``."""
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for fixture in sorted(self.fixtures, key=lambda item: item.path):
                info = tarfile.TarInfo(fixture.path)
                info.size = len(fixture.data)
                info.mode = 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(fixture.data))
        return buffer.getvalue()


# A descriptive name for adapters that deal in manifests rather than specs.
EnvironmentManifest = EnvironmentSpec


@dataclass(frozen=True)
class EnvironmentEvidence:
    """Versioned result envelope returned by an environment runner."""

    digest: str
    identity: str
    adapter_metadata: dict[str, Any] = field(default_factory=dict)
    identity_command: str | list[str] | None = None

    def to_envelope(self) -> dict[str, Any]:
        return {
            "schema": ENVIRONMENT_SCHEMA,
            "version": ENVIRONMENT_EVIDENCE_VERSION,
            "kind": "evidence",
            "digest": self.digest,
            "identity": self.identity,
            "identity_command": self.identity_command,
            "adapter_metadata": dict(self.adapter_metadata),
        }

    @classmethod
    def from_envelope(cls, envelope: Mapping[str, Any]) -> "EnvironmentEvidence":
        if envelope.get("schema") != ENVIRONMENT_SCHEMA:
            raise ValueError("unsupported environment evidence schema")
        if envelope.get("version") != ENVIRONMENT_EVIDENCE_VERSION:
            raise ValueError(f"unsupported environment evidence version: {envelope.get('version')!r}")
        if envelope.get("kind") != "evidence":
            raise ValueError("environment envelope is not evidence")
        metadata = envelope.get("adapter_metadata", {}) or {}
        if not isinstance(metadata, Mapping):
            raise ValueError("environment evidence adapter_metadata must be a mapping")
        return cls(
            digest=str(envelope.get("digest", "")),
            identity=str(envelope.get("identity", "")),
            adapter_metadata=dict(metadata),
            identity_command=envelope.get("identity_command"),
        )
