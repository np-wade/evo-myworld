# BR + Witt handoff

Created 2026-07-19 by kimi.

## New repos

- `/projects/bertrand-hussle` — BH CLI.
- `/projects/witt-brain` — Witt thinking organ.

Both have `git init` + first commit on branch `main`.

## Seam

Both repos carry an identical `INTERFACE.md` defining:

- Crate API (`witt_brain::WittBrain`) consumed by BH.
- JSON-RPC over Unix socket (`~/.config/bertrand-hussle/witt.sock`).
- Request/response types: `ThinkRequest`, `ThinkResponse`, `ToolCall`, `Usage`,
  `StreamEvent`, `Health`, `MemoryHit`, `MemoryEntry`.

## Design notes

- BH visual system is in `src/theme.rs`: 3-line header, `✦` sigil, braille
  spinner, `NO_COLOR` respect.
- BH bridge has an optional `python` feature using PyO3; default is socket RPC.
- Witt-brain depends only on standard crates; ZeroClaw traits are referenced by
  name in `DESIGN.md` and mirrored as placeholder traits in code.
- No heavy builds were run; code is structurally clean scaffold.

## Source reads

- Raven: `ui-tui/src/theme.ts`, `ui-tui/src/banner.ts`,
  `ui-tui/src/components/appChrome.tsx`, `raven/tui_rpc/server.py`,
  `raven/tui_rpc/models.py`, `raven/cli/tui_commands.py`,
  `bridge/src/server.ts`.
- Witt: `/projects/witt/Cargo.toml`, `/projects/witt/src/main.rs`,
  `/projects/witt/src/router.rs`, `/projects/witt/src/memory.rs`,
  `/projects/witt/src/intent.rs`.
- ZeroClaw: `zeroclaw-api/src/tool.rs`, `zeroclaw-api/src/model_provider.rs`,
  `zeroclaw-api/src/memory_traits.rs`, `zeroclaw-memory/src/lib.rs`,
  `zeroclaw-providers/src/ollama.rs`, `zeroclaw-runtime/src/agent/agent.rs`.
- Corpus: `Canop_broot`, `Julien-cpsn_ATAC`, `Nukesor_pueue`,
  `GyulyVGC_sniffnet`, `BurntSushi_ripgrep`, `PyO3_pyo3`.
