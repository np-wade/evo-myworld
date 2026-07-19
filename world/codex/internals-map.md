# evo plugin internals map

This map covers the requested surfaces in `/workspace/evo-myworld/plugins/evo/`:
`hooks/`, `bin/`, `src/evo/`, and the `evo direct` / `evo-drain` delivery path.

## Entry points and installation

- `plugins/evo/bin/evo` is the plugin-local shell entry point. Claude Code puts
  the plugin's `bin/` on the Bash-tool `PATH`; the wrapper locates the plugin
  root and executes `uv run --project <plugin-root> evo ...`. The installed CLI
  exposes the same Python command through `plugins/evo/pyproject.toml`.
- `plugins/evo/pyproject.toml` maps `evo` to `evo.cli:main` and `evo-drain` to
  `evo.inject.drain:main`.
- `plugins/evo/hooks/hooks.json` is the shared Claude-style hook declaration.
  It wires `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`,
  `Stop`, and `SubagentStop` to a fail-open Node shim. The shim reads hook JSON
  from stdin, tries the native `evo-hook-drain` with a two-second bound, passes
  through nonempty JSON output, and otherwise returns `{}`. A second
  `PostToolUse`/`Bash` handler invokes `hooks/wait_hint.sh` for a one-shot UX
  reminder.
- `plugins/evo/bin/evo-hook-drain` is the checked-in recovery wrapper. Normal
  installation downloads a platform-native Rust binary to
  `$EVO_HOME/bin/evo-hook-drain` (normally `~/.evo/bin/`) using
  `src/evo/host_install/_hook_drain.py`. If a host refresh restores the wrapper
  over its cached native binary, the wrapper executes the stable copy. If that
  copy is absent it logs a reinstall hint and returns `{}`, preserving the host
  session.
- `plugins/evo/bin/evo-hook-drain-rs/src/main.rs` is the hot-path filter. Its
  purpose is to cheaply resolve the workspace/session and check marker or
  optimize-mode flags before handing stdin to Python. This avoids starting a
  Python interpreter on every tool hook when nothing is pending.

Host installers are adapters, not just file copiers:

- Claude Code: `src/evo/host_install/claude_code.py` drives `claude plugin
  marketplace add/install`, then stages the native helper into the actual
  plugin root/cache. The shared `hooks.json` is used directly.
- Codex: `src/evo/host_install/codex.py` enables `[features]
  plugin_hooks=true` and `[plugins."evo@evo-hq"] enabled=true` in
  `~/.codex/config.toml`. It rewrites cached hook commands to an absolute,
  stable helper path because Codex does not guarantee
  `CLAUDE_PLUGIN_ROOT`; it also removes the Claude-only wait hint. Trusted hook
  hashes matter: untrusted hooks register but do not fire, so `evo direct`
  cannot arrive.
- Cursor: `src/evo/host_install/cursor.py` installs skills separately with
  `npx skills add` and merges native entries into `~/.cursor/hooks.json` for
  `sessionStart`, `beforeSubmitPrompt`, `preToolUse`, `stop`, and
  `subagentStop`. These call `evo-drain --host cursor` directly; Cursor does
  not use the Rust helper or Claude compatibility file.

## `evo direct` delivery lifecycle

1. **Engage/register.** `src/evo/inject/registry.py` records sessions beneath
   the active run's `inject/sessions/`. Claude Code uses
   `CLAUDE_CODE_SESSION_ID`, Codex uses `CODEX_THREAD_ID`; Cursor has no stable
   session environment variable, so `drain.py` resolves its session and
   workspace from hook stdin. Registration seeds a per-session offset so a new
   chat does not receive historical directives.
2. **Queue.** `cmd_direct` in `src/evo/cli.py` appends an event through
   `src/evo/inject/queue.py`. Broadcasts go to
   `<active-run>/inject/events/workspace.jsonl`; targeted messages go to
   `events/<exp_id>.jsonl`. Writes use `O_APPEND`, event IDs are sortable, and
   readers tolerate an incomplete trailing line.
3. **Select recipients and wake them.** Broadcast delivery enumerates the
   registry and filters out stale, unengaged, or subagent sessions where
   appropriate. Targeted delivery selects sessions associated with the
   experiment. `evo direct` touches each recipient's
   `inject/markers/<session>.flag`; the durable JSONL remains the source of
   message content.
4. **Hook fires.** On a frequent host event, the Rust helper sees the marker
   (SessionStart is also used to engage the orchestrator) and invokes the
   Python drain. Cursor invokes Python directly and applies equivalent gating
   there.
5. **Drain once.** `src/evo/inject/drain.py` loads the session record, reads
   only events after that session's stored offset, formats banners containing
   the directive ID and `evo ack <id>` instruction, and chooses a host envelope.
   Orchestrators read the workspace queue; experiment subagents read only their
   `<exp_id>.jsonl` queue.
6. **Record receipt.** After emitting, drain advances the session offset,
   removes the marker, and writes `inject/delivered/<event-id>.json` (L1:
   emitted to a session). When the agent executes `evo ack <id>`, the CLI writes
   `inject/acks/<event-id>.json` (L2: model confirmed receipt). `evo direct
   --wait` waits for L2; `evo direct status` reports queued/delivered/acked.

## What fires when, by host

| Moment | Claude Code | Codex | Cursor |
|---|---|---|---|
| New/resumed session | `SessionStart` registers/engages; CLI calls can also auto-register from `CLAUDE_CODE_SESSION_ID`. | Same shared event shape, keyed by `CODEX_THREAD_ID`; requires enabled and trusted plugin hooks. | `sessionStart` registers new chats; `beforeSubmitPrompt` catches resumed chats because Cursor lacks a session env var. |
| Before a tool | `PreToolUse` is the principal mid-turn drain. When a directive exists, the response adds `permissionDecision: allow`, because Claude drops bare pre-tool `additionalContext`. | `PreToolUse` returns bare `hookSpecificOutput.additionalContext`; unlike Claude, no permission decision is added. | `preToolUse` delivers only for shell tools by rewriting the command to print the directive before running the original command. Non-shell tools defer because Cursor drops reliable context there. |
| After a tool / prompt submission | `PostToolUse` and `UserPromptSubmit` are additional drain opportunities; Bash post-use may show `wait_hint.sh`. | Shared drain events work, but installer strips the Claude-specific wait hint. | No equivalent delivery channel: `beforeSubmitPrompt` registers only. |
| End of turn | `Stop` / `SubagentStop` use `{decision:"block", reason:text}` because these events do not support `additionalContext`; optimize mode can combine a queued directive with a continuation nudge. | Same stop envelope and continuation behavior. | `stop` / `subagentStop` return `followup_message`, which the IDE submits as a visible next message and provides the fallback for turns without a shell call. |

## Important boundaries inside `src/evo/`

- `cli.py` owns public commands and orchestration: initialization, experiment
  execution, gates, direct/ack/status, install/update, and reporting commands.
- `core.py` owns shared run/workspace state and host constants. Notably only
  Claude Code currently appears in `DISPATCH_HOSTS`; Codex and Cursor can run
  the general evo workflow but do not use Claude's cached-fork dispatch path.
- `dispatch.py` builds explorer/execute prompts and implements the Claude Code
  fork-cache dispatch protocol.
- `inject/{paths,registry,queue,marker,drain}.py` is the cross-host message bus:
  filesystem layout, recipient identity, durable events, wake flags, and
  host-specific hook output respectively.
- `host_install/*.py` translates common plugin behavior into each host's
  installation and hook mechanism.
- `backends/` supplies worktree, pool, remote, and sandbox execution adapters;
  `frontier_strategies.py` selects experiment parents; `scratchpad.py` and
  `dashboard.py` expose shared state and the experiment graph.

## Reliability consequences

- A marker is only a wake signal. A lost/repeated hook does not lose the
  directive because queue data and per-session offsets are durable.
- Consumption is deliberately deferred when the host channel is unreliable
  (especially Cursor non-shell pre-tool hooks), preventing a directive from
  being acknowledged internally without reaching the model.
- The native helper, Node shims, and checked-in fallback all fail open and use
  bounded subprocess calls, so a broken injection path should not wedge every
  agent tool call.
- Broadcast is opt-in: a session must be registered and evo-engaged. This
  avoids steering unrelated agent chats merely because global hooks are
  installed.

## Files read

- `/workspace/evo-myworld/CHARTER.md`
- `/workspace/evo-myworld/FIELD-NOTES.md`
- `/workspace/evo-myworld/queues/codex.md`
- `/workspace/evo-myworld/plugins/evo/hooks/hooks.json`
- `/workspace/evo-myworld/plugins/evo/hooks/wait_hint.sh`
- `/workspace/evo-myworld/plugins/evo/bin/evo`
- `/workspace/evo-myworld/plugins/evo/bin/evo-hook-drain`
- `/workspace/evo-myworld/plugins/evo/bin/evo-hook-drain-rs/src/main.rs`
- `/workspace/evo-myworld/plugins/evo/pyproject.toml`
- `/workspace/evo-myworld/plugins/evo/src/evo/cli.py`
- `/workspace/evo-myworld/plugins/evo/src/evo/core.py`
- `/workspace/evo-myworld/plugins/evo/src/evo/dispatch.py`
- `/workspace/evo-myworld/plugins/evo/src/evo/inject/{drain,marker,paths,queue,registry}.py`
- `/workspace/evo-myworld/plugins/evo/src/evo/host_install/{_hook_drain,claude_code,codex,cursor}.py`

