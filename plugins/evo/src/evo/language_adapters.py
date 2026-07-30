"""Language-neutral test commands and evidence envelopes.

The orchestrator can select a language adapter without knowing whether the
actual process is Python or Rust. Both adapters produce the same command and
metadata shape, which is also understood by the Rust environment runner.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LanguageAdapter:
    language: str
    command: tuple[str, ...]
    package_files: tuple[str, ...]
    evidence_kind: str = "test"

    def as_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "command": list(self.command),
            "package_files": list(self.package_files),
            "evidence_kind": self.evidence_kind,
        }


PYTHON = LanguageAdapter(
    language="python",
    command=("python", "-m", "pytest", "-q"),
    package_files=("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"),
)
RUST = LanguageAdapter(
    language="rust",
    command=("cargo", "test", "--all-targets"),
    package_files=("Cargo.toml", "Cargo.lock"),
)


def detect_adapters(root: Path) -> tuple[LanguageAdapter, ...]:
    """Return deterministic adapters for languages present in ``root``."""
    found: list[LanguageAdapter] = []
    if any((root / name).exists() for name in PYTHON.package_files):
        found.append(PYTHON)
    if any((root / name).exists() for name in RUST.package_files):
        found.append(RUST)
    return tuple(found)


def adapter_for(language: str) -> LanguageAdapter:
    normalized = language.strip().lower()
    if normalized in {"py", "python"}:
        return PYTHON
    if normalized in {"rs", "rust"}:
        return RUST
    raise ValueError(f"unsupported language adapter: {language!r}")


def test_envelope(
    adapter: LanguageAdapter,
    *,
    command: tuple[str, ...] | None = None,
    returncode: int | None = None,
    duration_ms: int | None = None,
    stdout: str = "",
    stderr: str = "",
    status: str | None = None,
    timed_out: bool = False,
) -> dict[str, Any]:
    """Normalize Python/Rust execution into one evidence record.

    ``returncode`` is None when the process timed out or was killed; ``status``
    and ``timed_out`` disambiguate that case so a None code is never read as a
    silent plain failure.
    """
    return {
        "schema": "evo.test-result",
        "version": 1,
        "kind": adapter.evidence_kind,
        "language": adapter.language,
        "command": list(command or adapter.command),
        "returncode": returncode,
        "duration_ms": duration_ms,
        "stdout": stdout,
        "stderr": stderr,
        "status": status,
        "timed_out": timed_out,
    }


# Not a pytest test despite the ``test_`` prefix; this is a factory. Marking it
# stops pytest from collecting the imported helper as a (fixtureless) test case.
test_envelope.__test__ = False
