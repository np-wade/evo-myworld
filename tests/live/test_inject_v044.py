"""Live verification of v0.4.4 inject contracts against real host CLIs in E2B.

This complements ``test_release_smoke.py``: that file verifies the full
optimize loop end-to-end (multi-experiment, mid-run directive consumption,
score-beats-baseline). This file verifies the *new* v0.4.4 safety + ack
contracts that release smoke doesn't cover:

  1. Engagement filter — an unengaged session must NOT receive an
     ``evo direct`` broadcast, even though it auto-registers at
     SessionStart.
  2. SessionStart unconditional drain leak fix — a directive queued
     before a session registers must not deliver to that fresh session
     (offset seeded at registration time).
  3. Pi host string — pi sessions must register with ``host="pi"``, not
     the pre-0.4.4 ``"openclaw"`` mistag.
  4. ACK channel L2 — an agent that runs ``evo ack <id>`` after seeing
     a ``[EVO DIRECTIVE id=…]`` banner must produce
     ``inject/acks/<id>.json``.

Each test installs evo + a host CLI + the host's plugin into a fresh E2B
sandbox, drives a short focused scenario, and asserts on file state +
agent stdout. No full optimize loop — that's what ``test_release_smoke.py``
is for.

Gated:

    EVO_LIVE_TEST_INJECT_V044=1 \\
    E2B_API_KEY=… \\
    ANTHROPIC_API_KEY=… \\
    EVO_RELEASE_SMOKE_SOURCE=local \\
    pytest tests/live/test_inject_v044.py -v -s

``EVO_RELEASE_SMOKE_SOURCE=local`` is required because v0.4.4 isn't on
PyPI yet — the sandbox must install from a tarball of this branch's
working tree.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "evo"


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def _gate() -> None:
    if os.environ.get("EVO_LIVE_TEST_INJECT_V044") != "1":
        pytest.skip("set EVO_LIVE_TEST_INJECT_V044=1 to enable")
    if not os.environ.get("E2B_API_KEY"):
        pytest.skip("E2B_API_KEY not set")
    if os.environ.get("EVO_RELEASE_SMOKE_SOURCE", "").lower() != "local":
        pytest.skip(
            "v0.4.4 isn't on PyPI yet — set EVO_RELEASE_SMOKE_SOURCE=local "
            "so the sandbox installs from this branch's tarball"
        )
    try:
        import e2b  # noqa: F401
    except ImportError:
        pytest.skip("e2b SDK not installed")


# ---------------------------------------------------------------------------
# Local source tarball — mirrors test_release_smoke.py:_make_evo_tarball
# ---------------------------------------------------------------------------


def _make_evo_tarball(out: Path) -> None:
    def filt(tar):
        skip = (".git", ".venv", "node_modules", "__pycache__", "build",
                "dist", ".pytest_cache", ".egg-info")
        if any(s in tar.name for s in skip):
            return None
        return tar

    with tarfile.open(out, "w:gz") as tar:
        tar.add(str(REPO_ROOT / ".claude-plugin"),
                arcname="evo-local-repo/.claude-plugin", filter=filt)
        tar.add(str(PLUGIN_ROOT),
                arcname="evo-local-repo/plugins/evo", filter=filt)


@pytest.fixture(scope="session")
def evo_local_tarball():
    _gate()
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as f:
        path = Path(f.name)
    try:
        _make_evo_tarball(path)
        yield path
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Sandbox harness (lightweight — inject tests don't need fixture repo / baseline)
# ---------------------------------------------------------------------------


class _Sandbox:
    """E2B sandbox helper. Self-contained per the project convention
    (test_release_smoke.py:191-194: "kept deliberately copy-paste rather
    than refactored into a shared module so each test file is
    self-contained for live debugging")."""

    def __init__(self, sbx, evo_local_tarball: Path):
        self.sbx = sbx
        self._evo_local_tarball = evo_local_tarball
        self._sudo = "sudo " if self.run("whoami").strip() != "root" else ""

    def run(self, cmd: str, *, timeout: int = 180, must_succeed: bool = True,
            background: bool = False, envs: dict | None = None):
        short = cmd[:90] + ("…" if len(cmd) > 90 else "")
        prefix = "&" if background else "$"
        print(f"{prefix} {short}", flush=True)
        r = self.sbx.commands.run(
            cmd, timeout=timeout, background=background, envs=envs,
            on_stdout=lambda x: print(f"  | {x.rstrip()}", flush=True),
            on_stderr=lambda x: print(f"  ! {x.rstrip()}", flush=True),
        )
        if not background and must_succeed and r.exit_code != 0:
            raise AssertionError(
                f"command failed (exit {r.exit_code}): {short}\n"
                f"stderr: {r.stderr[-500:]}"
            )
        return r if background else r.stdout

    def read_file(self, path: str) -> str:
        return self.sbx.files.read(path)

    def install_base(self) -> None:
        """Install OS deps + evo from local tarball. v0.4.4 isn't on PyPI."""
        self.run(
            f"{self._sudo}apt-get update -qq && {self._sudo}apt-get install -y "
            f"--no-install-recommends git curl ca-certificates python3 python3-venv "
            f">/dev/null", timeout=300,
        )
        self.run(
            f"{self._sudo}ln -sf $(command -v python3) /usr/local/bin/python "
            f"2>/dev/null || true", timeout=10,
        )
        self.run("curl -LsSf https://astral.sh/uv/install.sh | sh > /tmp/uv.log 2>&1",
                 timeout=120)

        self.sbx.files.write("/tmp/evo-local-repo.tar.gz",
                             self._evo_local_tarball.read_bytes())
        self.run("tar -xzf /tmp/evo-local-repo.tar.gz -C /tmp/")
        self.run(
            "export PATH=$HOME/.local/bin:$PATH; "
            "uv tool install /tmp/evo-local-repo/plugins/evo "
            "> /tmp/evo-tool-install.log 2>&1 || "
            "(cat /tmp/evo-tool-install.log; exit 1)", timeout=300,
        )
        self.run("export PATH=$HOME/.local/bin:$PATH; evo --version")

    def init_workspace(self, host: str) -> str:
        """Create a barebones evo workspace. Returns the run_dir path."""
        self.run("mkdir -p /tmp/ws && cd /tmp/ws && git init -q && "
                 "git config user.email 't@evo' && git config user.name 't' && "
                 "git config commit.gpgsign false && "
                 "echo 'x' > README.md && touch agent.py && "
                 "git add . && git commit -qm 'init'")
        self.run(
            f"export PATH=$HOME/.local/bin:$PATH; cd /tmp/ws && "
            f"evo init --name inject-v044 --target agent.py "
            f"--benchmark 'echo \\\"{{\\\\\\\"score\\\\\\\": 0}}\\\"' "
            f"--metric max --host {host}"
        )
        return "/tmp/ws/.evo/run_0000"


@pytest.fixture
def sandbox(evo_local_tarball):
    _gate()
    from e2b import Sandbox
    sbx = Sandbox.create(timeout=900)
    h = _Sandbox(sbx, evo_local_tarball)
    try:
        h.install_base()
        yield h
    finally:
        try: sbx.kill()
        except Exception: pass  # noqa: BLE001, E701


@pytest.fixture
def sandbox_4g(evo_local_tarball):
    """4GB sandbox for hosts that OOM on 1GB (openclaw, opencode)."""
    _gate()
    from e2b import Sandbox
    sbx = Sandbox.create(template="evo-test-4g", timeout=900)
    h = _Sandbox(sbx, evo_local_tarball)
    try:
        h.install_base()
        yield h
    finally:
        try: sbx.kill()
        except Exception: pass  # noqa: BLE001, E701


# ---------------------------------------------------------------------------
# Per-host install + drive descriptors
# ---------------------------------------------------------------------------


# Each entry: (host, install_steps, drive_template, env_required, sandbox_fixture)
#   drive_template: a bash command with `{prompt}` placeholder. Caller
#   shell-quotes the prompt and substitutes. Must background the agent
#   process and write pid to /tmp/agent.pid, log to /tmp/agent.log.
HOSTS: dict[str, dict] = {
    "claude-code": {
        "install": [
            "curl -fsSL https://deb.nodesource.com/setup_22.x | {sudo}bash - "
            "> /tmp/node-setup.log 2>&1",
            "{sudo}apt-get install -y nodejs >/dev/null",
            "{sudo}npm install -g @anthropic-ai/claude-code > /tmp/cc.log 2>&1",
            "export PATH=$HOME/.local/bin:$PATH; "
            "evo install claude-code --from-path /tmp/evo-local-repo",
        ],
        "drive_template": (
            "export PATH=$HOME/.local/bin:$PATH; "
            "nohup claude --print --dangerously-skip-permissions "
            "--allowedTools Bash --model claude-sonnet-4-5 "
            "--max-budget-usd 2.0 {prompt} > /tmp/agent.log 2>&1 & "
            "echo $! > /tmp/agent.pid"
        ),
        "env_var": "ANTHROPIC_API_KEY",
        "sandbox_fixture": "sandbox",
    },
    "codex": {
        "install": [
            "curl -fsSL https://deb.nodesource.com/setup_22.x | {sudo}bash - "
            "> /tmp/node-setup.log 2>&1",
            "{sudo}apt-get install -y nodejs >/dev/null",
            "{sudo}npm install -g @openai/codex > /tmp/codex.log 2>&1",
            "printenv OPENAI_API_KEY | codex login --with-api-key 2>&1 | tail -3",
            "export PATH=$HOME/.local/bin:$PATH; "
            "evo install codex --from-path /tmp/evo-local-repo --trust-hooks",
        ],
        "drive_template": (
            "export PATH=$HOME/.local/bin:$PATH; "
            "nohup codex exec --dangerously-bypass-approvals-and-sandbox "
            "--model gpt-5 {prompt} > /tmp/agent.log 2>&1 & "
            "echo $! > /tmp/agent.pid"
        ),
        "env_var": "OPENAI_API_KEY",
        "sandbox_fixture": "sandbox",
    },
    "opencode": {
        "install": [
            "curl -fsSL https://deb.nodesource.com/setup_22.x | {sudo}bash - "
            "> /tmp/node-setup.log 2>&1",
            "{sudo}apt-get install -y nodejs >/dev/null",
            "curl -fsSL https://opencode.ai/install | bash > /tmp/opencode.log 2>&1",
            "export PATH=$HOME/.local/bin:$HOME/.opencode/bin:$PATH; "
            "evo install opencode --from-path /tmp/evo-local-repo",
        ],
        "drive_template": (
            "export PATH=$HOME/.local/bin:$HOME/.opencode/bin:$PATH; "
            "nohup opencode run --model anthropic/claude-sonnet-4-5 "
            "{prompt} > /tmp/agent.log 2>&1 & "
            "echo $! > /tmp/agent.pid"
        ),
        "env_var": "ANTHROPIC_API_KEY",
        "sandbox_fixture": "sandbox_4g",
    },
    "hermes": {
        "install": [
            "curl -fsSL "
            "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh "
            "| bash > /tmp/hermes.log 2>&1",
            "export PATH=$HOME/.local/bin:$PATH; "
            "evo install hermes --from-path /tmp/evo-local-repo",
        ],
        "drive_template": (
            "export PATH=$HOME/.local/bin:$PATH; "
            "nohup hermes chat -q {prompt} -Q "
            "--provider anthropic --model claude-sonnet-4-5 "
            "> /tmp/agent.log 2>&1 & "
            "echo $! > /tmp/agent.pid"
        ),
        "env_var": "ANTHROPIC_API_KEY",
        "sandbox_fixture": "sandbox",
    },
    "openclaw": {
        "install": [
            "curl -fsSL https://deb.nodesource.com/setup_22.x | {sudo}bash - "
            "> /tmp/node-setup.log 2>&1",
            "{sudo}apt-get install -y nodejs >/dev/null",
            "{sudo}npm install -g openclaw > /tmp/openclaw.log 2>&1",
            "export PATH=$HOME/.local/bin:$PATH; "
            "evo install openclaw --from-path /tmp/evo-local-repo",
        ],
        "drive_template": (
            "export PATH=$HOME/.local/bin:$PATH; "
            "nohup openclaw agent --local --message {prompt} "
            "--model anthropic/claude-sonnet-4-5 "
            "> /tmp/agent.log 2>&1 & "
            "echo $! > /tmp/agent.pid"
        ),
        "env_var": "ANTHROPIC_API_KEY",
        "sandbox_fixture": "sandbox_4g",
    },
    "pi": {
        "install": [
            "curl -fsSL https://deb.nodesource.com/setup_22.x | {sudo}bash - "
            "> /tmp/node-setup.log 2>&1",
            "{sudo}apt-get install -y nodejs >/dev/null",
            "{sudo}npm install -g @earendil-works/pi-coding-agent > /tmp/pi.log 2>&1",
            "export PATH=$HOME/.local/bin:$PATH; "
            "evo install pi --from-path /tmp/evo-local-repo",
        ],
        "drive_template": (
            "export PATH=$HOME/.local/bin:$PATH; "
            "nohup pi -p {prompt} --provider anthropic "
            "--model claude-sonnet-4-5 > /tmp/agent.log 2>&1 & "
            "echo $! > /tmp/agent.pid"
        ),
        "env_var": "ANTHROPIC_API_KEY",
        "sandbox_fixture": "sandbox",
    },
}


def _shell_quote(s: str) -> str:
    """POSIX-safe single-quoting."""
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _do_install(h: _Sandbox, host: str, env_var: str, env_val: str) -> None:
    """Run a host's install steps with sudo + the API key in env."""
    cfg = HOSTS[host]
    env_export = f'export {env_var}="{env_val}"; '
    for step in cfg["install"]:
        h.run(f"{env_export}{step.format(sudo=h._sudo)}", timeout=600)


def _wait_for_agent_to_exit(h: _Sandbox, *, timeout: int = 240) -> None:
    """Poll /tmp/agent.pid until the process exits or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = h.run(
            "if [ -f /tmp/agent.pid ]; then "
            "  kill -0 $(cat /tmp/agent.pid) 2>/dev/null "
            "    && echo ALIVE || echo DEAD; "
            "else echo NOPID; fi",
            must_succeed=False,
        ).strip()
        if state in ("DEAD", "NOPID"):
            return
        time.sleep(3)
    raise AssertionError(f"agent still alive after {timeout}s; killing")


def _agent_stdout(h: _Sandbox) -> str:
    return h.run("cat /tmp/agent.log 2>/dev/null || echo ''",
                 must_succeed=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# The "external direct" pattern: agent prompt includes a `sleep` step
# that gives the test runner a window to issue `evo direct` from outside
# the agent's session. The sleep is itself a Bash tool call, so:
#   - PreToolUse fires (gate stat-checks marker; no marker yet)
#   - sleep runs
#   - During sleep, the test runner queues an evo direct from outside
#   - PostToolUse fires after sleep returns (marker now exists →
#     drain delivers directive into the model's context BEFORE the
#     model reads sleep's output)
# Token in the model's final answer = directive landed via the hook path.

_ENGAGED_PROMPT_TEMPLATE = (
    "Run these Bash commands in order: "
    "1. `evo status` (this engages your evo session). "
    "2. `sleep 8` (gives time for an external directive to arrive). "
    "3. `pwd` (this tool call's hook drains any pending directive). "
    "Then in your final reply, state any unusual word you saw in your context. "
    "If you saw a [EVO DIRECTIVE id=...] banner, follow its instructions exactly."
)

_UNENGAGED_PROMPT = (
    "Run `ls /tmp` using the Bash tool. Then in your final reply, "
    "state any unusual word you saw in your context. Do NOT run any "
    "`evo` commands — your task is only to list and report."
)

_ACK_PROMPT_TEMPLATE = (
    "Run these Bash commands in order: "
    "1. `evo status`. "
    "2. `sleep 8`. "
    "3. `pwd`. "
    "Then if your context contains a [EVO DIRECTIVE id=<id>] banner, "
    "run `evo ack <id>` (substitute the exact id from the banner). "
    "Then in your final reply, state the directive id you saw and acked."
)


@pytest.mark.parametrize("host", list(HOSTS.keys()))
def test_unengaged_session_does_not_receive_directive(host, request):
    """Safety guarantee: a session that never ran any `evo` command must
    NOT receive a workspace-broadcast `evo direct` directive. The
    engagement filter on `cmd_direct` (cli.py) and the SessionStart
    offset-seed (registry.py + drain.py) together close the leak that
    existed pre-0.4.4."""
    cfg = HOSTS[host]
    env_val = os.environ.get(cfg["env_var"])
    if not env_val:
        pytest.skip(f"{cfg['env_var']} required for {host}")

    h = request.getfixturevalue(cfg["sandbox_fixture"])
    _do_install(h, host, cfg["env_var"], env_val)
    run_dir = h.init_workspace(host)

    # Queue a directive BEFORE any host session exists. With no engaged
    # sessions to fan out to, fanout=0; the event sits in workspace.jsonl.
    token = "zedplum"
    h.run(f"cd /tmp/ws && export PATH=$HOME/.local/bin:$PATH && "
          f"evo direct 'respond with the word {token}'")

    # Launch the host with a prompt that does NOT run evo.
    prompt = _shell_quote(_UNENGAGED_PROMPT)
    drive = cfg["drive_template"].format(prompt=prompt)
    h.run(
        f"cd /tmp/ws && export {cfg['env_var']}=\"{env_val}\"; {drive}",
        timeout=30,
    )
    _wait_for_agent_to_exit(h, timeout=180)

    log = _agent_stdout(h).lower()
    assert token not in log, (
        f"SAFETY FAILURE on {host}: unengaged session received a "
        f"directive meant for engaged sessions only.\n"
        f"agent log:\n{log[-2000:]}"
    )


@pytest.mark.parametrize("host", list(HOSTS.keys()))
def test_engaged_session_receives_external_directive(host, request):
    """End-to-end positive case: an engaged session, mid-turn, receives
    a directive queued from OUTSIDE the session via `evo direct`. The
    directive lands via the PostToolUse drain after the agent's `sleep`
    step, and the model echoes the token in its final answer.

    The token comes from an external process, not the model's own
    Bash invocation, so token-in-output proves the inject path worked
    end-to-end (host loaded plugin → hook fired → drain emitted →
    host injected into context → model saw it).
    """
    cfg = HOSTS[host]
    env_val = os.environ.get(cfg["env_var"])
    if not env_val:
        pytest.skip(f"{cfg['env_var']} required for {host}")

    h = request.getfixturevalue(cfg["sandbox_fixture"])
    _do_install(h, host, cfg["env_var"], env_val)
    h.init_workspace(host)

    prompt = _shell_quote(_ENGAGED_PROMPT_TEMPLATE)
    drive = cfg["drive_template"].format(prompt=prompt)
    h.run(
        f"cd /tmp/ws && export {cfg['env_var']}=\"{env_val}\"; {drive}",
        timeout=30,
    )

    # Give the agent time to run `evo status` (engages the session) and
    # enter the sleep step. 5s is comfortably under the prompt's 8s sleep.
    time.sleep(5)

    token = "zedplum"
    h.run(
        f"cd /tmp/ws && export PATH=$HOME/.local/bin:$PATH && "
        f"evo direct 'respond with the word {token}'",
        timeout=30,
    )

    _wait_for_agent_to_exit(h, timeout=240)
    log = _agent_stdout(h).lower()
    assert token in log, (
        f"DELIVERY FAILURE on {host}: engaged session did not receive "
        f"the externally-queued directive.\n"
        f"agent log:\n{log[-2000:]}"
    )


def test_pi_session_registers_with_correct_host_string(sandbox):
    """Pi sessions must register with ``host="pi"`` (not the pre-0.4.4
    ``"openclaw"`` mistag). The shared JS factory in
    ``openclaw_plugin/factory.ts`` is parameterized on host; the pi
    npm bundle (built from ``pi-entry.ts``) binds ``makeRegister("pi")``.
    Verified by checking ``inject/sessions/*.json`` after a pi session
    has registered.
    """
    env_val = os.environ.get("ANTHROPIC_API_KEY")
    if not env_val:
        pytest.skip("ANTHROPIC_API_KEY required for pi host-string check")

    cfg = HOSTS["pi"]
    _do_install(sandbox, "pi", "ANTHROPIC_API_KEY", env_val)
    sandbox.init_workspace("pi")

    # Drive pi briefly so its session registers. The exact prompt content
    # doesn't matter — we only care that the bundle loaded and called
    # registerSession.
    prompt = _shell_quote("Say hello and exit.")
    drive = cfg["drive_template"].format(prompt=prompt)
    sandbox.run(
        f"cd /tmp/ws && export ANTHROPIC_API_KEY=\"{env_val}\"; {drive}",
        timeout=30,
    )
    _wait_for_agent_to_exit(sandbox, timeout=180)

    # Inspect the session record(s) — every one written by the pi
    # extension must have host="pi", not "openclaw".
    records_raw = sandbox.run(
        "for f in /tmp/ws/.evo/run_0000/inject/sessions/*.json; do "
        "  cat \"$f\"; echo; "
        "done",
        must_succeed=False,
    )
    assert records_raw.strip(), "no session records — pi extension did not register"

    found_pi = False
    for line in records_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        host_tag = rec.get("host")
        sid = rec.get("session_id", "")
        # Pi bundle prefixes session ids with the host string:
        # see openclaw_plugin/factory.ts:deriveSessionId.
        if sid.startswith("pi-"):
            assert host_tag == "pi", (
                f"pi session registered with host={host_tag!r}, "
                f"expected 'pi'. Record: {rec}"
            )
            found_pi = True
        assert host_tag != "openclaw" or not sid.startswith("openclaw-"), (
            "pre-0.4.4 pi-tagged-as-openclaw bug regressed: "
            f"found openclaw-prefixed session id in pi run. Record: {rec}"
        )
    assert found_pi, (
        f"no pi-prefixed session id found in registry. "
        f"Records:\n{records_raw}"
    )


def test_ack_recorded_when_agent_runs_evo_ack(sandbox):
    """ACK channel L2: an agent that runs `evo ack <id>` after seeing a
    [EVO DIRECTIVE id=…] banner must produce inject/acks/<id>.json with
    the right session attribution. Tested on claude-code as a reference
    implementation; the path is host-agnostic.
    """
    env_val = os.environ.get("ANTHROPIC_API_KEY")
    if not env_val:
        pytest.skip("ANTHROPIC_API_KEY required for ack test")

    cfg = HOSTS["claude-code"]
    _do_install(sandbox, "claude-code", "ANTHROPIC_API_KEY", env_val)
    sandbox.init_workspace("claude-code")

    prompt = _shell_quote(_ACK_PROMPT_TEMPLATE)
    drive = cfg["drive_template"].format(prompt=prompt)
    sandbox.run(
        f"cd /tmp/ws && export ANTHROPIC_API_KEY=\"{env_val}\"; {drive}",
        timeout=30,
    )

    # Inject mid-sleep.
    time.sleep(5)
    sandbox.run(
        "cd /tmp/ws && export PATH=$HOME/.local/bin:$PATH && "
        "evo direct 'this is the ack test directive'",
        timeout=30,
    )

    _wait_for_agent_to_exit(sandbox, timeout=240)

    # An ack file must exist for at least one directive id.
    ack_listing = sandbox.run(
        "ls /tmp/ws/.evo/run_0000/inject/acks/ 2>/dev/null | head -5",
        must_succeed=False,
    )
    assert ack_listing.strip(), (
        f"no ack files written — agent didn't run `evo ack <id>` after "
        f"seeing the directive.\nagent log:\n{_agent_stdout(sandbox)[-2000:]}"
    )

    # Pick the first ack file and verify its contents.
    first = ack_listing.strip().splitlines()[0].strip()
    rec_raw = sandbox.read_file(f"/tmp/ws/.evo/run_0000/inject/acks/{first}")
    rec = json.loads(rec_raw)
    assert rec.get("event_id"), f"ack record missing event_id: {rec}"
    assert rec.get("host") == "claude-code", (
        f"ack record attribution wrong: host={rec.get('host')!r}, "
        f"expected 'claude-code'"
    )
    assert rec.get("session_id"), f"ack record missing session_id: {rec}"
    assert rec.get("acked_at"), f"ack record missing acked_at: {rec}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
