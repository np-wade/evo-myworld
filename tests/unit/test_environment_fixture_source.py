from __future__ import annotations

import os
from pathlib import Path

import pytest

from evo.backends.environment import EnvironmentSpec, _fixture_from_value


def _fixtures(spec: EnvironmentSpec) -> dict[str, bytes]:
    return {fixture.path: fixture.data for fixture in spec.fixtures}


def test_in_root_source_fixture_is_read(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    secret = tmp_path / "data" / "config.txt"
    secret.write_bytes(b"in-root\n")

    spec = EnvironmentSpec.from_manifest(
        {"fixtures": [{"path": "config.txt", "source": "data/config.txt"}]},
        root=tmp_path,
    )

    assert _fixtures(spec) == {"config.txt": b"in-root\n"}


def test_absolute_source_escaping_root_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_bytes(b"top secret\n")

    with pytest.raises(ValueError, match="escapes root"):
        EnvironmentSpec.from_manifest(
            {"fixtures": [{"path": "x", "source": str(outside)}]},
            root=tmp_path,
        )


def test_dotdot_traversal_source_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").write_bytes(b"nope\n")

    with pytest.raises(ValueError, match="escapes root"):
        EnvironmentSpec.from_manifest(
            {"fixtures": [{"path": "x", "source": "../secret.txt"}]},
            root=root,
        )


def test_symlink_escaping_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"leak\n")
    link = root / "link.txt"
    os.symlink(outside, link)

    with pytest.raises(ValueError, match="escapes root"):
        EnvironmentSpec.from_manifest(
            {"fixtures": [{"path": "x", "source": "link.txt"}]},
            root=root,
        )


def test_source_without_root_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_bytes(b"data\n")

    with pytest.raises(ValueError, match="requires a manifest root"):
        _fixture_from_value("x", {"source": str(target)}, None)


def test_inline_content_fixtures_still_work() -> None:
    spec = EnvironmentSpec.from_manifest(
        {
            "fixtures": [
                {"path": "a.txt", "content": "hello"},
                {"path": "b.bin", "content_base64": "aGVsbG8="},
            ]
        }
    )
    assert _fixtures(spec) == {"a.txt": b"hello", "b.bin": b"hello"}
