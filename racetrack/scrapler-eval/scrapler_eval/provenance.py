"""provenance.py — run stamping + heartbeat for the Scrapler Eval Harness.

Donor lineage (pattern ported, not code):
  - rustyhorde_vergen (vergen-gitcl/src/gitcl/mod.rs): the IDEA of a build/run
    provenance stamp. Vergen shells out to `git rev-parse HEAD` for the SHA and
    `git status --porcelain` for the dirty flag, gates on
    `git rev-parse --is-inside-work-tree`, and emits key/value provenance
    (there as `cargo:rustc-env` vars). Here we port that idea into a pure-stdlib
    Python dict stamp (git sha, dirty flag, host, python version, platform, ts).
  - hertzbeat (not in corpus): the IDEA of a lightweight heartbeat — a 1-line
    per-interval status writer, ported as an atomic single-line status file.

Pure stdlib. subprocess is used only to shell out to git, and every git call is
guarded so a missing git binary or a non-repo directory degrades to "unknown"
rather than crashing (anti-cheat rule 4: never crash the race).

This module NEVER calls time.time() itself — the caller stamps the epoch second
(`ts`) so tests are deterministic (interface.py: "harness never calls time
itself in tests").
"""

from __future__ import annotations

import os
import platform
import subprocess
from datetime import datetime, timezone

__all__ = ["stamp", "stamp_line", "Heartbeat", "result_header"]

_GIT_TIMEOUT = 5  # seconds; git should be instant, but never hang a race


def _iso8601(ts: float) -> str:
    """UTC ISO-8601 string for an epoch second (no wall-clock read)."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _git(args: list[str], repo_dir: str | None) -> str | None:
    """Run `git <args>` in repo_dir, returning stripped stdout or None.

    None means: git absent, not a repo, or the command failed. Ported from
    vergen's guarded `run_cmd` -> `is_ok_and(status.success())` pattern.
    """
    cwd = repo_dir or os.getcwd()
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        # FileNotFoundError => git binary missing; OSError => bad cwd; etc.
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _in_work_tree(repo_dir: str | None) -> bool:
    """Vergen gate: `git rev-parse --is-inside-work-tree` == true."""
    out = _git(["rev-parse", "--is-inside-work-tree"], repo_dir)
    return out is not None and out.strip() == "true"


def stamp(ts: float, repo_dir: str | None = None) -> dict:
    """Build a run provenance stamp for the epoch second `ts`.

    Returns a dict with keys: git_sha, git_dirty, host, python, platform, ts,
    utc. git_sha is the full HEAD SHA, or "unknown" if git is absent / this is
    not a repo. git_dirty is True iff `git status --porcelain` is non-empty.

    `ts` is passed in (never read from the clock) so results are reproducible
    and tests are deterministic.
    """
    git_sha = "unknown"
    git_dirty = False

    if _in_work_tree(repo_dir):
        sha = _git(["rev-parse", "HEAD"], repo_dir)
        if sha:
            git_sha = sha
        porcelain = _git(["status", "--porcelain"], repo_dir)
        # porcelain is None on failure (treat as clean/unknown), "" when clean,
        # and a non-empty listing when the work tree is dirty.
        git_dirty = bool(porcelain)

    return {
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "host": platform.node(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "ts": ts,
        "utc": _iso8601(ts),
    }


def stamp_line(stamp_dict: dict) -> str:
    """One compact provenance line for log/result headers.

    e.g. `2026-07-25T00:00:00+00:00 sha=abc1234(dirty) host=box py=3.14.4 <plat>`
    """
    sha = stamp_dict.get("git_sha", "unknown")
    short = sha[:7] if sha and sha != "unknown" else sha
    dirty = "(dirty)" if stamp_dict.get("git_dirty") else ""
    return (
        f"{stamp_dict.get('utc', '')} "
        f"sha={short}{dirty} "
        f"host={stamp_dict.get('host', '')} "
        f"py={stamp_dict.get('python', '')} "
        f"{stamp_dict.get('platform', '')}"
    ).strip()


class Heartbeat:
    """A 1-line-per-interval status writer (the status Nicholas wants mid-run).

    Each `beat` OVERWRITES a single-line status file atomically (write to a temp
    sibling, then os.replace) so a reader always sees a whole, current line and
    never a half-written or ever-growing log. `read` returns that current line.
    """

    def __init__(self, path: str, run_id: str):
        self.path = path
        self.run_id = run_id

    def beat(self, msg: str, ts: float, extra: dict | None = None) -> str:
        """Overwrite the heartbeat file with one status line for epoch `ts`.

        Line: `<utc> [run_id] <msg> <extra>`. Returns the line written.
        `ts` is caller-supplied (no wall-clock read).
        """
        utc = _iso8601(ts)
        extra_str = ""
        if extra:
            extra_str = " " + " ".join(f"{k}={v}" for k, v in extra.items())
        line = f"{utc} [{self.run_id}] {msg}{extra_str}"

        # Atomic overwrite: temp file in the same dir, then rename over target.
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        tmp = f"{self.path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)  # atomic on POSIX; leaves no temp behind
        return line

    def read(self) -> str:
        """Return the current heartbeat line (empty string if never beaten)."""
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except FileNotFoundError:
            return ""


def result_header(
    stamp_dict: dict, bracket_name: str, n_candidates: int, n_tasks: int
) -> str:
    """Markdown header block for a race result file, embedding the stamp.

    Every result file starts with this so the run is reproducible/traceable:
    the git SHA, dirty flag, host, python and timestamp are captured inline.
    """
    dirty = "yes" if stamp_dict.get("git_dirty") else "no"
    lines = [
        f"# Scrapler Eval — {bracket_name}",
        "",
        "| provenance | value |",
        "| --- | --- |",
        f"| bracket | {bracket_name} |",
        f"| candidates | {n_candidates} |",
        f"| tasks | {n_tasks} |",
        f"| git_sha | `{stamp_dict.get('git_sha', 'unknown')}` |",
        f"| git_dirty | {dirty} |",
        f"| host | {stamp_dict.get('host', '')} |",
        f"| python | {stamp_dict.get('python', '')} |",
        f"| platform | {stamp_dict.get('platform', '')} |",
        f"| utc | {stamp_dict.get('utc', '')} |",
        f"| ts | {stamp_dict.get('ts', '')} |",
        "",
        f"<!-- {stamp_line(stamp_dict)} -->",
        "",
    ]
    return "\n".join(lines)
