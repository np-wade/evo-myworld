"""Regression: claude_code.install path helpers must honor CLAUDE_CONFIG_DIR.

Without this, evo install runs in a container with CLAUDE_CONFIG_DIR=/persistent/path
silently look at ~/.claude (which is empty), can't find the freshly-installed
plugin cache, and skip ensure_hook_drain_binary. The hook then fires with
exit 127 at runtime and `evo direct` delivery is permanently broken.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from evo.host_install import claude_code


@pytest.fixture
def env_with_config_dir(tmp_path, monkeypatch):
    cfg = tmp_path / "alt-claude"
    cfg.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    return cfg


def test_claude_config_dir_honors_env_var(env_with_config_dir):
    assert claude_code._claude_config_dir() == env_with_config_dir


def test_claude_config_dir_defaults_to_home(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert claude_code._claude_config_dir() == Path.home() / ".claude"


def test_latest_cache_dir_returns_none_when_cache_absent(env_with_config_dir):
    assert claude_code._latest_cache_dir() is None


def test_latest_cache_dir_finds_versioned_cache_under_config_dir(env_with_config_dir):
    versioned = (
        env_with_config_dir
        / "plugins" / "cache" / claude_code._MARKETPLACE_NAME / "evo" / "0.4.4"
    )
    versioned.mkdir(parents=True)
    assert claude_code._latest_cache_dir() == versioned


def test_latest_cache_dir_picks_latest_version(env_with_config_dir):
    base = env_with_config_dir / "plugins" / "cache" / claude_code._MARKETPLACE_NAME / "evo"
    for v in ("0.4.1", "0.4.2", "0.4.4", "0.4.3"):
        (base / v).mkdir(parents=True)
    # `sorted()` over directory names gives lex order; for 3-part SemVer with
    # single-digit minors/patches, lex == numeric. Latest is "0.4.4".
    assert claude_code._latest_cache_dir() == base / "0.4.4"


def test_latest_cache_dir_does_not_leak_to_home_when_env_set(env_with_config_dir, monkeypatch):
    """If CLAUDE_CONFIG_DIR is set, the helper must not fall back to ~/.claude
    even when ~/.claude exists with a plugin cache. This was the production
    bug: helpers silently looked at the wrong root."""
    fake_home = env_with_config_dir.parent / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    # Populate fake home with a decoy plugin cache.
    decoy = fake_home / ".claude" / "plugins" / "cache" / claude_code._MARKETPLACE_NAME / "evo" / "0.4.4"
    decoy.mkdir(parents=True)
    # _latest_cache_dir must look at env_with_config_dir, not fake_home/.claude.
    # env_with_config_dir has no plugins/ tree -> returns None.
    assert claude_code._latest_cache_dir() is None


# --------------------------------------------------------------------------- #
# _hook_drain_staging_dir: --from-path must target the source tree, not cache
# --------------------------------------------------------------------------- #
def test_staging_dir_from_path_targets_source_plugin_dir(tmp_path):
    """Regression: with --from-path, claude runs the plugin from the source
    tree (${CLAUDE_PLUGIN_ROOT} = <from_path>/plugins/evo). Staging the
    hook-drain binary into the version cache leaves the hook firing exit 127.
    The staging dir must be the source plugin dir."""
    repo = tmp_path / "evo"
    plugin = repo / "plugins" / "evo"
    plugin.mkdir(parents=True)
    assert claude_code._hook_drain_staging_dir(str(repo)) == plugin


def test_staging_dir_from_path_accepts_plugin_dir_directly(tmp_path):
    """Tolerate being handed the plugin dir itself (has bin/ or .claude-plugin)."""
    plugin = tmp_path / "evo-plugin"
    (plugin / "bin").mkdir(parents=True)
    assert claude_code._hook_drain_staging_dir(str(plugin)) == plugin


def test_staging_dir_without_from_path_uses_cache(env_with_config_dir):
    """A normal (no --from-path) install stages into the version cache."""
    base = env_with_config_dir / "plugins" / "cache" / claude_code._MARKETPLACE_NAME / "evo"
    versioned = base / "0.5.0-alpha.12"
    versioned.mkdir(parents=True)
    assert claude_code._hook_drain_staging_dir(None) == versioned
