"""Focused tests for the content-addressed Evo artifact shuttle."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from evo.artifacts import (
    ArtifactError,
    ArtifactStore,
    ImportLimits,
    TransformLimits,
    apply_diff,
    apply_script,
)


def _write_tar(path: Path, members: list[tuple[str, bytes]]) -> Path:
    with tarfile.open(path, mode="w") as archive:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    return path


def test_directory_storage_is_deterministic_and_has_language_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("print('ok')\n")
    (source / "nested").mkdir()
    (source / "nested" / "lib.rs").write_text("fn main() {}\n")
    store = ArtifactStore(tmp_path / "store")

    first = store.store(source)
    second = store.store(source)
    assert first == second
    manifest = store.read_manifest(first)
    assert manifest["language"] == "mixed"
    assert {entry["language"] for entry in manifest["entries"]} == {"python", "rust"}


def test_export_import_restore_and_swap_store_backup(tmp_path: Path) -> None:
    source = tmp_path / "fixture.py"
    source.write_text("old\n")
    store = ArtifactStore(tmp_path / "store")
    old = store.store(source)
    source.write_text("new\n")
    new = store.store(source)
    archive = tmp_path / "fixture.tar"
    store.export(new, archive)
    imported = ArtifactStore(tmp_path / "other-store").import_artifact(archive)
    assert imported == new

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "target").write_text("old\n")
    other = ArtifactStore(tmp_path / "other-store")
    expected_backup = other.store(workspace / "target")
    result = other.swap(imported, workspace, "target")
    assert result.artifact == new
    assert result.backup == expected_backup
    assert (workspace / "target").read_text() == "new\n"
    other.restore(result.backup, workspace, "target")
    assert (workspace / "target").read_text() == "old\n"


def test_import_rejects_archive_exceeding_total_byte_cap(tmp_path: Path) -> None:
    archive = _write_tar(
        tmp_path / "bomb.tar",
        [("objects/a", b"x" * 30), ("objects/b", b"y" * 30)],
    )
    limits = ImportLimits(max_members=100, max_member_bytes=100, max_total_bytes=50)
    with pytest.raises(ArtifactError, match="total size limit"):
        ArtifactStore(tmp_path / "store").import_artifact(archive, limits=limits)


def test_import_rejects_archive_exceeding_member_count_cap(tmp_path: Path) -> None:
    archive = _write_tar(
        tmp_path / "many.tar",
        [(f"objects/{index}", b"z") for index in range(4)],
    )
    limits = ImportLimits(max_members=2)
    with pytest.raises(ArtifactError, match="member limit"):
        ArtifactStore(tmp_path / "store").import_artifact(archive, limits=limits)


def test_import_rejects_single_oversized_member(tmp_path: Path) -> None:
    archive = _write_tar(tmp_path / "big.tar", [("objects/huge", b"q" * 32)])
    limits = ImportLimits(max_member_bytes=10)
    with pytest.raises(ArtifactError, match="member exceeds size limit"):
        ArtifactStore(tmp_path / "store").import_artifact(archive, limits=limits)


def test_import_roundtrips_normal_artifact_with_custom_limits(tmp_path: Path) -> None:
    source = tmp_path / "fixture.py"
    source.write_text("print('ok')\n")
    store = ArtifactStore(tmp_path / "store")
    digest = store.store(source)
    archive = tmp_path / "fixture.tar"
    store.export(digest, archive)
    limits = ImportLimits(max_members=32, max_member_bytes=1024, max_total_bytes=8192)
    imported = ArtifactStore(tmp_path / "other-store").import_artifact(archive, limits=limits)
    assert imported == digest


def test_symlink_is_rejected_at_storage_and_restore_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("secret")
    (source / "link").symlink_to(outside)
    with pytest.raises(ArtifactError, match="symlink"):
        ArtifactStore(tmp_path / "store").store(source)


def test_bounded_diff_rejects_traversal_and_applies_code_change(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "main.py"
    target.write_text("print('old')\n")
    diff = """--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-print('old')\n+print('new')\n"""
    assert apply_diff(workspace, diff.encode()) == ["main.py"]
    assert target.read_text() == "print('new')\n"
    with pytest.raises(ArtifactError):
        apply_diff(workspace, "--- a/../outside\n+++ b/../outside\n@@ -0,0 +1 @@\n+x\n")


def test_script_transform_is_staged_and_failed_transform_does_not_mutate(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "value.txt"
    target.write_text("before\n")
    script = tmp_path / "transform.py"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "root = Path(sys.argv[1])\n"
        "(root / 'value.txt').write_text('after\\n')\n"
    )
    assert apply_script(workspace, script) == [".", "value.txt"]
    assert target.read_text() == "after\n"

    failing = tmp_path / "failing.py"
    failing.write_text("raise SystemExit(3)\n")
    with pytest.raises(ArtifactError, match="transform failed"):
        apply_script(workspace, failing)
    assert target.read_text() == "after\n"


def test_cli_store_outputs_digest(tmp_path: Path) -> None:
    source = tmp_path / "x.rs"
    source.write_text("fn main() {}\n")
    store = tmp_path / "store"
    script = Path(__file__).parents[2] / "plugins" / "evo" / "bin" / "evo-artifact"
    result = subprocess.run(
        [str(script), "store", str(source), "--store", str(store)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["digest"] == ArtifactStore(store).store(source)
