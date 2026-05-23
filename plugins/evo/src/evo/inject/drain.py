"""Drain entry point: read events for a session, format host-specific
output, update offset, unlink marker.

Invoked by the bash hot-path script via `python3 -m evo.drain` only
after the marker file confirmed there's something to deliver.

Output goes to stdout in the format the host expects:
    Claude Code / Codex: {"hookSpecificOutput": {"hookEventName": "...", "additionalContext": "..."}}
    hermes:              {"context": "..."}
    opencode:            JSON describing the mutation; in-process plugin
                         interprets it and applies to the right hook input.

Hosts call it differently — Claude Code and Codex shell-exec the bash
hook which exec's `python3 -m evo.drain`. hermes and opencode plugins
are in-process and call into Python/TS equivalents directly; for those
hosts this module's logic is mirrored, not invoked via subprocess.

Per `notes/cross-host-inject-design.md`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import sys
from pathlib import Path

from . import marker, queue
from .paths import (
    exp_events_path,
    inject_root,
    offset_file,
    session_file,
    workspace_events_path,
)
from .registry import get_session, register_session

# Hook event names that signal a fresh session — drain unconditionally on
# these to catch directives queued before the session existed. Covers both
# Claude Code's PascalCase and Cursor's camelCase spelling.
_SESSION_START_EVENTS = ("SessionStart", "sessionStart")


def _drain_debug(**fields) -> None:
    """Append a diagnostic line to ~/.cursor/evo-drain.log, but only when the
    opt-in sentinel ~/.cursor/.evo-drain-debug exists (or EVO_DRAIN_DEBUG is
    set). Used to diagnose why a directive isn't reaching a Cursor IDE
    session — shows the hook payload shape and where the drain decided to
    bail. Never logs in normal operation; failures are swallowed."""
    try:
        sentinel = Path.home() / ".cursor" / ".evo-drain-debug"
        if not sentinel.exists() and not os.environ.get("EVO_DRAIN_DEBUG"):
            return
        rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), **fields}
        log = Path.home() / ".cursor" / "evo-drain.log"
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001 — diagnostics must never break the hook
        pass


HOST_HOOK_EVENT_NAMES = {
    # PreToolUse / PostToolUse / UserPromptSubmit / SessionStart use the
    # hookSpecificOutput.additionalContext envelope; Stop / SubagentStop use
    # the {decision: "block", reason: ...} envelope which Claude Code and
    # Codex both feed back as the next continuation prompt (verified via
    # the ralph-loop plugin's stop-hook.sh).
    "claude-code": ("PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionStart", "Stop", "SubagentStop"),
    "codex": ("PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionStart", "Stop", "SubagentStop"),
    # Cursor: sessionStart + beforeSubmitPrompt register the session; preToolUse
    # delivers mid-turn for SHELL tools only (updated_input echo into stdout);
    # every non-shell tool defers (no consume) and is delivered at turn end via
    # stop -> followup_message. subagentStop fires at Task-subagent turn-end
    # (Cursor 1.7+), same envelope as stop. (additional_context is dropped by
    # the IDE, and agent_message-on-deny consumes without the agent acting —
    # both verified.)
    "cursor": ("sessionStart", "beforeSubmitPrompt", "preToolUse", "stop", "subagentStop"),
}


def _detect_host_from_env() -> str:
    """Best-effort host detection from env. Default 'claude-code'.

    Codex exposes the session as CODEX_THREAD_ID (not CODEX_SESSION_ID)
    on codex-cli 0.130. Keep this in sync with
    registry.HOST_SESSION_ENV_VARS.
    """
    if os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude-code"
    if os.environ.get("CODEX_THREAD_ID"):
        return "codex"
    if os.environ.get("HERMES_SESSION_ID"):
        return "hermes"
    if os.environ.get("OPENCODE_SESSION_ID"):
        return "opencode"
    return "claude-code"


def _read_stdin_payload() -> dict:
    """Read the host's hook stdin payload as a dict. Returns {} when stdin
    is a tty, empty, or not JSON. stdin can only be consumed once, so this
    is the single read point — all fields (hook event, session id,
    workspace roots) are derived from the returned dict."""
    if sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _hook_event_from_payload(payload: dict) -> str | None:
    return payload.get("hook_event_name") or payload.get("hookEventName")


def _resolve_root_from_payload(payload: dict) -> Path | None:
    """Locate the workspace root (dir containing `.evo/`) for hosts whose
    hook command runs from outside the project. Cursor's user-level
    `~/.cursor/hooks.json` runs from `~/.cursor/`, not the repo, so cwd is
    useless — the project path arrives in the payload's `workspace_roots`.
    Falls back to walking up from cwd. Returns None if no `.evo/` is found.
    """
    candidates: list[Path] = []
    roots = payload.get("workspace_roots")
    if isinstance(roots, list):
        candidates.extend(Path(r) for r in roots if isinstance(r, str) and r)
    candidates.append(Path.cwd())
    for start in candidates:
        cur = start
        while True:
            if (cur / ".evo").is_dir():
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent
    return None


_DELIVER_EVENTS = ("stop", "subagentStop", "preToolUse")


def _cursor_tool_class(tool_name: str | None) -> str:
    """Classify a Cursor preToolUse tool_name. Only 'shell' has a working
    mid-turn delivery channel — rewrite the command via updated_input so the
    directive prints to stdout (the tool result the model reads); the command
    still runs. Every other tool DEFERS (no consume) and is delivered at the
    turn-end stop: deny+agent_message was tried and consumes the directive
    without the agent acting on it. The 'edit'/'other' split is retained only
    for debug logging. Tool names vary by Cursor version — match substrings.
    """
    t = (tool_name or "").lower()
    if any(k in t for k in ("shell", "bash", "terminal", "run_command", "runterminalcmd")):
        return "shell"
    if any(k in t for k in ("edit", "write", "create_file", "search_replace", "str_replace", "applypatch", "apply_patch")):
        return "edit"
    return "other"


import re as _re

_EVO_CMD_RE = _re.compile(r"^\s*evo(\s|$)")


# Per-host invocation patterns for /evo:optimize. Anchored to prompt
# start so a brief or quoted text containing the invocation mid-string
# doesn't accidentally match. Patterns are case-insensitive (the user
# may type /EVO:OPTIMIZE or /Evo:Optimize).
#
# Each host's value is a list of regexes; the prompt matches if any
# regex matches.
_OPTIMIZE_INVOCATION_PATTERNS: dict[str, list[_re.Pattern[str]]] = {
    "claude-code": [_re.compile(r"^\s*/evo:optimize\b", _re.IGNORECASE)],
    "codex": [
        _re.compile(r"^\s*\$evo:optimize\b", _re.IGNORECASE),
        _re.compile(r"^\s*\$evo\s+optimize\b", _re.IGNORECASE),
    ],
    "cursor": [_re.compile(r"^\s*/optimize\b", _re.IGNORECASE)],
    # hermes / opencode / openclaw / pi: TBD — confirm exact invocation
    # syntax per host. Leaving empty for now means /optimize won't
    # auto-flip on those hosts; manual `evo` commands during the loop
    # will still trigger the existing engagement filter, just not the
    # optimize_mode-specific behaviors (policy nudge, stop continuation).
    "hermes": [_re.compile(r"^\s*/optimize\b", _re.IGNORECASE)],
    "opencode": [_re.compile(r"^\s*/optimize\b", _re.IGNORECASE)],
    "openclaw": [_re.compile(r"^\s*/optimize\b", _re.IGNORECASE)],
    "pi": [_re.compile(r"^\s*/optimize\b", _re.IGNORECASE)],
}


def _extract_user_prompt(payload: dict | None) -> str:
    """Pull the user's prompt text out of a hook payload. Different hosts
    name the field differently. Returns "" if nothing recognizable."""
    if not payload:
        return ""
    for key in ("prompt", "user_prompt", "userPrompt", "message", "input"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _maybe_mark_optimize_from_prompt(
    root: Path,
    session_id: str,
    host: str,
    hook_event: str | None,
    payload: dict | None,
) -> None:
    """If the host hook payload looks like a /evo:optimize invocation,
    flip optimize_mode on the session record.

    Runs on UserPromptSubmit-like events (UserPromptSubmit, sessionStart,
    beforeSubmitPrompt) for any host. Subagent fence is enforced inside
    `mark_optimize_mode` — it refuses to flag a session with exp_id set,
    so a subagent receiving a brief that quotes /evo:optimize won't be
    mistakenly tagged.
    """
    # Only check on prompt-submit-shaped events. Tool-call events have
    # no user prompt to match against.
    prompt_events = (
        "UserPromptSubmit", "userPromptSubmit",
        "beforeSubmitPrompt", "SessionStart", "sessionStart",
    )
    if hook_event not in prompt_events:
        return
    patterns = _OPTIMIZE_INVOCATION_PATTERNS.get(host, [])
    if not patterns:
        return
    prompt = _extract_user_prompt(payload)
    if not prompt:
        return
    if not any(p.search(prompt) for p in patterns):
        return
    # mark_optimize_mode is idempotent and refuses to flag subagents.
    from .registry import mark_optimize_mode
    mark_optimize_mode(root, session_id)


def _maybe_mark_engaged_from_shell(
    root: Path,
    session_id: str,
    host: str,
    hook_event: str | None,
    payload: dict | None,
) -> None:
    """For self-contained hosts (currently Cursor): if the agent's about
    to run an `evo` shell command, mark the session as evo-engaged and
    seed the workspace offset to the queue tail. Mirrors what
    `auto_register_from_env` does for hosts that route engagement
    through the Python CLI path.
    """
    if host != "cursor":
        return
    if hook_event != "preToolUse":
        return
    if _cursor_tool_class((payload or {}).get("tool_name")) != "shell":
        return
    cmd = ((payload or {}).get("tool_input") or {}).get("command", "")
    if not isinstance(cmd, str) or not _EVO_CMD_RE.match(cmd):
        return
    # Idempotent: mark_engaged returns False after the first transition.
    from .registry import mark_engaged
    if mark_engaged(root, session_id):
        queue.init_offset_to_latest(root, session_id)


def _self_contained_gate(
    root: Path, session_id: str, host: str, hook_event: str | None,
    tool_name: str | None = None,
) -> bool:
    """Gate for hosts wired directly to `evo-drain` (no `evo-hook-drain`
    binary in front). Returns True when the caller should proceed to drain.

    Registers the session on the FIRST event of any kind, seeding its offset
    to the current queue tail. `sessionStart` only fires for brand-new chats —
    a *resumed* Cursor chat never fires it, so registration must also happen on
    the other wired events (beforeSubmitPrompt, stop); otherwise the session
    stays unregistered and `evo direct` can never reach it. Seeding the offset
    avoids replaying directives queued before this session existed.

    Delivery events are `_DELIVER_EVENTS` (preToolUse / stop / subagentStop).
    Everything else (sessionStart, beforeSubmitPrompt) is register-only — the
    IDE drops additional_context so there's nothing to deliver, and draining
    there would just consume directives. On `preToolUse`, only a SHELL tool
    delivers (updated_input echo); every non-shell tool is DEFERRED (return
    False, no consume) so the directive waits (peek-don't-pop) for the next
    shell call or the turn-end stop — deny+agent_message consumes without
    delivering on non-shell tools.
    """
    fresh = not session_file(root, session_id).exists()
    if fresh:
        register_session(root, session_id, host)
        queue.init_offset_to_latest(root, session_id)
    if hook_event not in _DELIVER_EVENTS:
        return False  # register-only (sessionStart, beforeSubmitPrompt, …)
    if hook_event == "preToolUse" and _cursor_tool_class(tool_name) != "shell":
        # Only shell delivers mid-turn (updated_input echo into stdout, which
        # the model reliably reads). For every other tool, deny+agent_message
        # CONSUMES the directive without actually delivering it (verified: a
        # Read deny clears the marker but the agent never gets the message).
        # So defer (no consume) — the directive waits for the next shell call
        # or the turn-end `stop`, both of which deliver reliably.
        return False
    if fresh:
        return False  # just registered on this event; nothing marked yet
    return marker.exists(root, session_id)


def format_directive_text(events: list[dict]) -> str:
    """Format events as a single text block to splice into the agent's
    next turn.

    Wraps each event with the `[EVO DIRECTIVE id=<id>]` / `[END EVO DIRECTIVE]`
    banner pair. The banner is the authenticity signal — `optimize` and
    `subagent` skills tell the agent that text inside this banner is
    user-authoritative (issued via `evo direct`), not tool-output prompt
    injection. Without the banner, models like gpt-5 / opus-4-7 may
    refuse the directive as suspicious.

    The trailing `evo ack <id>` instruction tells the agent how to ack
    the directive after acting on it; the CLI command writes
    inject/acks/<id>.json which `evo direct status` and `evo direct --wait`
    surface. Acks are best-effort — models sometimes forget — but presence
    of an ack is a positive signal that the directive landed.
    """
    lines = []
    for ev in events:
        text = ev.get("text", "")
        if not text:
            continue
        ev_id = ev.get("id", "")
        if ev_id:
            lines.append(f"[EVO DIRECTIVE id={ev_id}]")
            lines.append(text)
            lines.append(f"[END EVO DIRECTIVE — when done, run: evo ack {ev_id}]")
        else:
            # Legacy fallback for events without an id (shouldn't occur
            # with the current queue, but be defensive).
            lines.append("[EVO DIRECTIVE]")
            lines.append(text)
            lines.append("[END EVO DIRECTIVE]")
    return "\n".join(lines)


def _write_delivery_records(
    root: Path,
    events: list[dict],
    session_id: str,
    host: str,
    hook_event: str | None,
) -> None:
    """L1 ACK: record per-event delivery. Best-effort; never raises.

    Writes one file per event delivered, keyed by event id. Multiple
    sessions delivering the same event each leave their own record
    keyed by sid (the file's session_id field); since file names are
    keyed only on event_id, later writes for the same event overwrite
    earlier ones — `evo direct status` queries the file to know "this
    event was delivered to at least one session," not exhaustive routing.
    Good enough for the diagnostic role.
    """
    from .paths import delivered_file, delivered_dir
    try:
        delivered_dir(root).mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        for ev in events:
            ev_id = ev.get("id")
            if not ev_id:
                continue
            rec = {
                "event_id": ev_id,
                "session_id": session_id,
                "host": host,
                "hook_event": hook_event,
                "delivered_at": now,
            }
            delivered_file(root, ev_id).write_text(json.dumps(rec))
    except OSError:  # pragma: no cover — never break the hot path
        pass


def emit_for_host(host: str, hook_event: str | None, text: str, payload: dict | None = None) -> None:
    """Write the host-specific JSON payload to stdout. `payload` is the raw
    hook stdin (needed by the cursor preToolUse branch for tool_name/command)."""
    if not text:
        sys.stdout.write("{}")
        return
    if host in ("claude-code", "codex"):
        # Stop / SubagentStop don't support additionalContext — they must
        # return `{decision: "block", reason: text}`, which both hosts feed
        # back as the next continuation prompt (verified via the ralph-loop
        # plugin's stop-hook.sh on Claude Code; documented for Codex).
        if hook_event in ("Stop", "SubagentStop"):
            out = {"decision": "block", "reason": text}
            sys.stdout.write(json.dumps(out, separators=(",", ":")))
            return
        # All other events (PreToolUse / PostToolUse / UserPromptSubmit /
        # SessionStart) honor the same hookSpecificOutput envelope. Default
        # to PreToolUse if we couldn't read it from stdin.
        evt = hook_event or "PreToolUse"
        payload = {
            "hookSpecificOutput": {
                "hookEventName": evt,
                "additionalContext": text,
            }
        }
        sys.stdout.write(json.dumps(payload, separators=(",", ":")))
        return
    if host == "hermes":
        payload = {"context": text}
        sys.stdout.write(json.dumps(payload, separators=(",", ":")))
        return
    if host == "cursor":
        # Cursor delivery, routed around the IDE's broken additional_context:
        #   stop/subagentStop -> followup_message (auto-submitted at turn end)
        #   preToolUse + shell -> updated_input: prepend an echo of the directive
        #     so it lands in the command's stdout (the tool result the model
        #     reads); command still runs (exit code preserved by ordering last).
        # Non-shell preToolUse never reaches here — the gate defers it (deny+
        # agent_message consumes without delivering, so we let stop deliver).
        p = payload or {}
        if hook_event in ("stop", "subagentStop"):
            out: dict = {"followup_message": text}
        elif hook_event == "preToolUse" and _cursor_tool_class(p.get("tool_name")) == "shell":
            tool_input = dict(p.get("tool_input") or {})
            orig = tool_input.get("command", "")
            tool_input["command"] = "printf '%s\\n' " + shlex.quote(text) + " ; " + orig
            out = {"permission": "allow", "updated_input": tool_input}
        else:
            out = {"additional_context": text}
        sys.stdout.write(json.dumps(out, separators=(",", ":")))
        return
    # opencode and other in-process hosts: this entry point shouldn't
    # normally be invoked there. Fall through to a generic envelope.
    sys.stdout.write(json.dumps({"text": text}, separators=(",", ":")))


def drain_session(root: Path, session_id: str, host: str | None = None, hook_event: str | None = None, payload: dict | None = None) -> int:
    """Read events for `session_id`, format, emit, update offset,
    unlink marker. Returns 0 on success. `payload` is the raw hook stdin,
    passed through to emit_for_host (cursor preToolUse needs tool_name/command)."""
    if not inject_root(root).exists():
        sys.stdout.write("{}")
        return 0
    sess = get_session(root, session_id)
    if sess is None:
        # Session somehow not registered but marker existed. Be lenient.
        marker.unlink(root, session_id)
        sys.stdout.write("{}")
        return 0

    host = host or sess.get("host") or _detect_host_from_env()
    # Codex and Claude Code use the same hookSpecificOutput envelope.
    # If host is "unknown" (e.g. legacy registry entry), default to that
    # envelope since it's the more common case for shell-hook hosts.
    if host == "unknown":
        host = "claude-code"
    exp_id = sess.get("exp_id")

    # Seed offset to the current queue tail for sessions that don't yet
    # have an offset file. Closes the SessionStart-unconditional-drain
    # leak: the Rust binary skips the marker check on SessionStart and
    # hands off to this drain regardless, so without seeding, a fresh
    # session would backfill every event in workspace.jsonl — bypassing
    # the engagement filter. Contract: a session only sees events queued
    # after it registered.
    if not offset_file(root, session_id).exists():
        queue.init_offset_to_latest(root, session_id)

    events: list[dict] = []
    new_workspace_offset: str | None = None
    new_exp_offset: str | None = None

    if exp_id:
        # Subagent: drain its scoped queue only
        last_id = queue.read_offset(root, session_id, "exp")
        new_events = queue.read_events_after(exp_events_path(root, exp_id), last_id)
        events.extend(new_events)
        if new_events:
            new_exp_offset = new_events[-1]["id"]
    else:
        # Orchestrator-class session: drain workspace queue
        last_id = queue.read_offset(root, session_id, "workspace")
        new_events = queue.read_events_after(workspace_events_path(root), last_id)
        events.extend(new_events)
        if new_events:
            new_workspace_offset = new_events[-1]["id"]

    text = format_directive_text(events)

    # Policy block: orchestrator in optimize_mode tried Edit/Write or
    # non-evo Bash. Hard-deny on the 1st violation and every 5th after.
    # Short-circuits the normal emit — the agent sees the deny + banner.
    if _should_policy_block(root, session_id, sess, host, hook_event, payload):
        sys.stdout.write(json.dumps(_policy_block_envelope(host), separators=(",", ":")))
        # Don't unlink marker / advance offset on a policy block — the
        # inject directive (if any) hasn't actually been delivered to
        # the model; the tool was denied before that point. Leave the
        # state so the next non-violating tool call can drain it.
        return 0

    # Stop-nudge: if this is a Stop/SubagentStop on an orchestrator in
    # optimize_mode, augment (or override) the emit with a continuation
    # prompt so the agent keeps driving the loop autonomously. Loop guard
    # is progress-gated — consecutive Stop fires with no new experiment
    # since the last nudge let the agent actually stop.
    nudge_text = _maybe_stop_nudge_text(root, session_id, sess, host, hook_event)
    if nudge_text:
        # Replace the emit text with the nudge — Stop/SubagentStop on
        # claude-code/codex use the {decision: block, reason} envelope,
        # not the additionalContext envelope. emit_for_host honors that
        # for the host-event combination.
        emit_for_host(host, hook_event, nudge_text, payload)
    else:
        emit_for_host(host, hook_event, text, payload)

    # L1 ACK: record delivery for each event so `evo direct status <id>`
    # can show whether the drain emitted the directive to a session.
    if events:
        _write_delivery_records(root, events, session_id, host, hook_event)

    # Update offset and unlink marker — only after successful emit
    if new_workspace_offset or new_exp_offset:
        queue.write_offset(
            root,
            session_id,
            workspace_id=new_workspace_offset,
            exp_id=new_exp_offset,
        )
    marker.unlink(root, session_id)
    return 0


# ---------------------------------------------------------------------------
# Policy nudge — block orchestrator strays from /optimize protocol
# ---------------------------------------------------------------------------


_EDIT_TOOL_NAMES = frozenset({
    # claude-code / codex
    "edit", "write", "notebookedit", "notebook_edit",
    # cursor
    "edit_file", "create_file", "search_replace", "applypatch", "apply_patch",
    "str_replace", "delete_file",
    # opencode / openclaw / pi / hermes — these tend to use the same set
    "file_write", "file_edit",
})

_BASH_TOOL_NAMES = frozenset({
    "bash", "shell", "exec",
    "run_terminal_cmd", "runterminalcmd",
    "run_command", "terminal",
    "execute_code", "execute",
})

_READ_TOOL_NAMES = frozenset({
    "read", "read_file", "glob", "grep",
    "find_files", "list_files", "list_dir", "ls",
    "search", "web_search", "web_fetch",
})


def _classify_tool(host: str, tool_name: str | None) -> str:
    """Classify a tool call into 'edit' | 'bash' | 'read' | 'other'.

    Cross-host: each host names its tools differently. claude-code uses
    Edit/Write/Bash; cursor uses edit_file/run_terminal_cmd; codex uses
    similar names plus 'shell'/'exec'. Uses exact-name matching against
    known sets to avoid false positives like "TodoWrite" matching "write".
    """
    if not tool_name:
        return "other"
    t = tool_name.lower()
    if t in _EDIT_TOOL_NAMES:
        return "edit"
    if t in _BASH_TOOL_NAMES:
        return "bash"
    if t in _READ_TOOL_NAMES:
        return "read"
    return "other"


# Bash commands the orchestrator is allowed to run in optimize_mode.
# These are: any `evo` invocation, any host's headless subagent spawn,
# and read-only inspection commands. Anything else looks like "running
# experiments by hand" and gets blocked.

_ORCHESTRATOR_BASH_ALLOWLIST_RE = _re.compile(
    r"^\s*(?:nohup\s+)?"  # optional nohup wrapper
    r"(?:"
        r"evo(?:\s|$)"           # any evo command
        r"|claude(?:\s|$)"        # claude -p / claude --print
        r"|codex(?:\s|$)"         # codex exec
        r"|cursor-agent(?:\s|$)"  # cursor-agent -p
        r"|opencode(?:\s|$)"      # opencode run
        r"|hermes(?:\s|$)"        # hermes chat
        r"|openclaw(?:\s|$)"      # openclaw agent
        r"|pi(?:\s|$)"            # pi-coding-agent (alias `pi`)
        r"|pi-coding-agent(?:\s|$)"
        # Read-only inspection
        r"|git\s+(?:status|log|diff|show|branch|remote|stash|config\s+--get)\b"
        r"|ls(?:\s|$)"
        r"|cat(?:\s|$)"
        r"|find(?:\s|$)"
        r"|grep(?:\s|$)"
        r"|head(?:\s|$)"
        r"|tail(?:\s|$)"
        r"|wc(?:\s|$)"
        r"|which(?:\s|$)"
        r"|pwd(?:\s|$)"
        r"|env(?:\s|$)"
        r"|printenv(?:\s|$)"
        r"|echo(?:\s|$)"
        r"|true(?:\s|$)"
        r"|false(?:\s|$)"
    r")"
)


def _is_allowed_orchestrator_bash(command: str | None) -> bool:
    """Return True if the bash command looks like a legitimate orchestrator
    action: evo invocation, headless subagent spawn, or read-only inspection.
    """
    if not command or not isinstance(command, str):
        return False
    return bool(_ORCHESTRATOR_BASH_ALLOWLIST_RE.match(command))


_POLICY_NUDGE_TEMPLATE = """[EVO POLICY]
Preventative block. You may have strayed from /evo:optimize protocol.

When /optimize is active, the orchestrator should NOT edit files directly
or run experiment commands by hand. The protocol is: write briefs, spawn
subagents, let them do the edits and runs, then read the results.

If you need to wait for subagents to finish, use `evo wait` — it blocks
until any experiment concludes, max 1h.

Manual edits and non-evo shell commands are discouraged unless they're
operations evo doesn't already expose. If this block was actually
warranted (rare), run `evo exit-optimize-mode` first to disable the
safety nudges, then retry the tool.

(Reminder: next nudge fires after 5 more violations.)
[END EVO POLICY]
"""


def _policy_state_file(root: Path, session_id: str) -> Path:
    """Per-session policy bookkeeping: violation_count."""
    return inject_root(root) / "policy_state" / f"{session_id}.json"


def _read_policy_state(root: Path, session_id: str) -> dict:
    p = _policy_state_file(root, session_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _write_policy_state(root: Path, session_id: str, data: dict) -> None:
    p = _policy_state_file(root, session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))


def _should_policy_block(
    root: Path, session_id: str, sess: dict | None, host: str | None,
    hook_event: str | None, payload: dict | None,
) -> bool:
    """Decide whether to hard-deny the current tool call as a policy
    violation. Increments the per-session violation counter; returns
    True on violations #1, #6, #11, etc. (block on first, then every
    5th).

    Conditions for considering a tool call a violation:
      - hook_event is PreToolUse (only block before tool fires).
      - session is orchestrator-class (no exp_id).
      - optimize_mode is true on the session record.
      - tool is "edit" OR ("bash" AND command not allowlisted).
    """
    if hook_event != "PreToolUse":
        return False
    if not sess:
        return False
    if sess.get("exp_id"):
        return False  # subagent — exempt
    if not sess.get("optimize_mode"):
        return False
    if not payload:
        return False

    tool_name = payload.get("tool_name") or ""
    tool_class = _classify_tool(host or "", tool_name)
    tool_input = payload.get("tool_input") or {}

    is_violation = False
    if tool_class == "edit":
        is_violation = True
    elif tool_class == "bash":
        cmd = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not _is_allowed_orchestrator_bash(cmd):
            is_violation = True

    if not is_violation:
        return False

    # Counter-based cadence: block on the 1st violation and every 5th
    # after (i.e., 1, 5, 10, 15, …). The 1st blocks immediately to give
    # the agent a preventative reminder; the modular gating spaces the
    # follow-ups so we don't nag on every single tool call.
    state = _read_policy_state(root, session_id)
    count = int(state.get("violation_count", 0)) + 1
    state["violation_count"] = count
    state["last_violation_tool"] = tool_name
    _write_policy_state(root, session_id, state)
    return count == 1 or count % 5 == 0


def _policy_block_envelope(host: str | None) -> dict:
    """Per-host hard-deny envelope. claude-code/codex use {permission:
    deny, reason}. Cursor uses {permission: deny, reason} too in its
    current preToolUse contract."""
    return {"permission": "deny", "reason": _POLICY_NUDGE_TEMPLATE}


# ---------------------------------------------------------------------------
# Stop-hook self-continuation nudge for /optimize orchestrators
# ---------------------------------------------------------------------------

_STOP_EVENTS = ("Stop", "SubagentStop", "stop", "subagentStop")


def _experiment_count(root: Path) -> int:
    """Count experiment dirs under <run_dir>/experiments/. Used as the
    progress signal for the stop-nudge loop guard.
    """
    # Find the active run dir (lexicographically last run_*).
    evo_dir = root / ".evo"
    if not evo_dir.is_dir():
        return 0
    runs = sorted(
        p for p in evo_dir.iterdir()
        if p.is_dir() and p.name.startswith("run_")
    )
    if not runs:
        return 0
    exp_dir = runs[-1] / "experiments"
    if not exp_dir.is_dir():
        return 0
    try:
        return sum(1 for p in exp_dir.iterdir() if p.is_dir())
    except OSError:
        return 0


def _stop_nudge_state_file(root: Path, session_id: str) -> Path:
    """Per-session stop-nudge bookkeeping: last_nudge_at_exp_count."""
    return inject_root(root) / "policy_state" / f"{session_id}.json"


def _read_stop_nudge_state(root: Path, session_id: str) -> dict:
    p = _stop_nudge_state_file(root, session_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _write_stop_nudge_state(root: Path, session_id: str, data: dict) -> None:
    p = _stop_nudge_state_file(root, session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))


_STOP_NUDGE_TEMPLATE = """[EVO LOOP]
You are driving /evo:optimize autonomously. Don't stop, and don't ask
the user for direction — they explicitly invoked /optimize for hands-off
operation. They'll intervene via `evo direct` if they need to.

If subagents are still running: run `evo wait` to block until the next
experiment concludes (or up to 1h). Then resume planning.

If subagents are done and you have unread results: read `evo scratchpad`,
update annotations as needed, and plan + spawn the next round.

Stop only if `evo status` shows the budget exhausted or you've hit the
stall limit. If so, print a final summary first. To suppress this
continuation loop for a legitimate one-off task, run
`evo exit-optimize-mode`.
[END EVO LOOP]
"""


def _maybe_stop_nudge_text(
    root: Path,
    session_id: str,
    sess: dict | None,
    host: str | None,
    hook_event: str | None,
) -> str | None:
    """Return continuation-prompt text if this Stop/SubagentStop should
    re-prompt the agent, or None to let the agent stop normally.

    Conditions:
      - hook event must be Stop or SubagentStop (case-sensitive per host).
      - session must be orchestrator-class (no exp_id).
      - optimize_mode must be true on the session record.
      - host must support the {decision: block, reason} envelope today —
        claude-code and codex. Cursor uses a different stop envelope.
      - loop guard: if a previous stop-nudge fired and the experiment
        count hasn't increased since, suppress.
    """
    if hook_event not in _STOP_EVENTS:
        return None
    if not sess:
        return None
    if sess.get("exp_id"):
        return None  # subagent — not our session to force-continue
    if not sess.get("optimize_mode"):
        return None
    if host not in ("claude-code", "codex"):
        return None  # only these hosts honor the block-reason envelope

    state = _read_stop_nudge_state(root, session_id)
    current_count = _experiment_count(root)
    last_count = state.get("last_nudge_at_exp_count")

    if last_count is not None and current_count <= last_count:
        # Previous nudge fired; no new experiment since. Let agent stop.
        return None

    # Record this nudge for the progress gate.
    state["last_nudge_at_exp_count"] = current_count
    _write_stop_nudge_state(root, session_id, state)
    return _STOP_NUDGE_TEMPLATE


def main(argv: list[str] | None = None) -> int:
    """Two invocation modes:

    1. Front-ended by the `evo-hook-drain` Rust binary (claude-code/codex):
       it passes `--run-dir` and `--session` and has already done the marker
       gate, so this just drains.
    2. Self-contained (cursor): the host's hooks.json calls `evo-drain
       --host cursor` directly with no Rust binary in front. `--run-dir` and
       `--session` are omitted; they're resolved from the hook stdin payload
       (`workspace_roots`, `conversation_id`) and the marker gate runs here.
    """
    parser = argparse.ArgumentParser(prog="evo.drain")
    parser.add_argument("--run-dir", default=None, help="Path to .evo/run_*/ directory (omit for self-contained hosts)")
    parser.add_argument("--session", default=None, help="session_id to drain (omit to read from stdin payload)")
    parser.add_argument("--host", default=None, help="host name (claude-code/codex/hermes/opencode/cursor); auto-detected if omitted")
    args = parser.parse_args(argv)

    payload = _read_stdin_payload()
    hook_event = _hook_event_from_payload(payload)

    # Mode 1: Rust-driven — run-dir + session supplied, gate already done.
    if args.run_dir:
        run_dir = Path(args.run_dir)
        # run_dir is .../.evo/run_*; the workspace root is its grandparent.
        root = run_dir.parent.parent
        # Detect /evo:optimize invocation from the prompt payload, before
        # we drain. Idempotent + subagent-safe inside mark_optimize_mode.
        if args.session and args.host:
            _maybe_mark_optimize_from_prompt(
                root, args.session, args.host, hook_event, payload,
            )
        return drain_session(root, args.session, host=args.host, hook_event=hook_event)

    # Mode 2: self-contained — resolve everything from args + stdin payload.
    # Key on conversation_id: it's present in EVERY Cursor hook event, whereas
    # session_id only appears in sessionStart. Keying on session_id would
    # register the session under one id at sessionStart and then look up a
    # different id at postToolUse (where session_id is absent), so mid-run
    # directives would never be delivered.
    host = args.host or "cursor"
    session = args.session or payload.get("conversation_id") or payload.get("session_id")
    root = _resolve_root_from_payload(payload)
    if not session or root is None or not inject_root(root).parent.exists():
        _drain_debug(stage="resolve", host=host, hook_event=hook_event,
                     payload_keys=sorted(payload.keys()), session=session,
                     root=str(root) if root else None, decision="bail")
        sys.stdout.write("{}")
        return 0
    tool_name = payload.get("tool_name")
    registered = session_file(root, session).exists()
    has_marker = marker.exists(root, session)
    # Cursor has no session-id env var that Python `auto_register_from_env`
    # can detect, so the engagement signal can't be set via the CLI path
    # used by other hosts. Detect it here instead: if the agent runs any
    # `evo …` shell command, flip engagement on this session's record.
    _maybe_mark_engaged_from_shell(root, session, host, hook_event, payload)
    gate = _self_contained_gate(root, session, host, hook_event, tool_name)
    # Detect /optimize invocation from the prompt payload for cursor's
    # self-contained path. Must run AFTER the gate because the gate is
    # what lazily registers the cursor session on first event (without
    # registration, mark_optimize_mode finds no session file). The
    # mark_optimize_mode helper is idempotent + refuses to flag subagents.
    _maybe_mark_optimize_from_prompt(root, session, host, hook_event, payload)
    _drain_debug(stage="gate", host=host, hook_event=hook_event, session=session,
                 root=str(root), tool_name=tool_name,
                 tool_class=_cursor_tool_class(tool_name) if hook_event == "preToolUse" else None,
                 registered_before=registered, marker=has_marker, gate=gate)
    if not gate:
        sys.stdout.write("{}")
        return 0
    return drain_session(root, session, host=host, hook_event=hook_event, payload=payload)


if __name__ == "__main__":
    sys.exit(main())
