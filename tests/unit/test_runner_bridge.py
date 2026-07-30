import os
from pathlib import Path

from evo.language_adapters import RUST
from evo.runner_bridge import RustRunnerClient, run_adapter


def test_rust_runner_controls_python_or_rust_process_boundary(tmp_path: Path):
    binary = (
        Path(__file__).parents[2]
        / "plugins/evo/bin/evo-env-runner/target/debug/evo-env-runner"
    )
    if not binary.exists():
        return
    # The runner clears env and only forwards the manifest env, so a PATH-
    # dependent command (`cargo`) needs PATH passed through to spawn at all;
    # without it the runner reports a spawn_error with returncode None.
    result = run_adapter(RUST, root=tmp_path, env={"PATH": os.environ["PATH"]})
    assert result["schema"] == "evo.test-result"
    assert result["language"] == "rust"
    assert result["returncode"] is not None
    assert result["status"] == "exited"
    assert result["timed_out"] is False


def test_missing_runner_is_actionable(tmp_path: Path):
    missing = tmp_path / "missing-runner"
    try:
        RustRunnerClient(missing)
    except FileNotFoundError as exc:
        assert "EVO_ENV_RUNNER" in str(exc)
    else:
        raise AssertionError("missing runner should fail before spawning")
