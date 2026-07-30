from pathlib import Path

from evo.language_adapters import RUST, adapter_for, detect_adapters, test_envelope


def test_detects_python_and_rust_projects(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    assert detect_adapters(tmp_path) == (
        adapter_for("python"),
        adapter_for("rust"),
    )


def test_rust_alias_and_shared_envelope():
    assert adapter_for("rs") == RUST
    result = test_envelope(RUST, returncode=0, duration_ms=12)
    assert result["schema"] == "evo.test-result"
    assert result["language"] == "rust"
    assert result["command"] == ["cargo", "test", "--all-targets"]
