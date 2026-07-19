# Kimi-3 mission: the Bertrand Hussle CLI + the Witt Brain

You (Kimi K3, the creative/exploratory seat) own this. DESIGN + SCAFFOLD:
make it real enough to build from, beautiful enough to feel like the
characters. This is a 2-minute-read brief; the doing is the point.

## TWO NEW GIT REPOS (Nicholas's instruction)

Create them as their OWN standalone project repos (they are not part of
evo-myworld — they just gestate here):
- `/projects/bertrand-hussle` — the Bertrand Hussle CLI. `git init` it,
  first commit.
- `/projects/witt-brain` — the Witt agent/brain (holds the ~9B model).
  `git init` it, first commit.

**Compatibility is required:** they are separate repos but must fit
together — Witt is meant to live INSIDE Bertrand Hussle (BH) as its
thinking organ. So define a clean seam: Witt exposes a stable interface
(a Rust crate API and/or a CLI/RPC contract) that BH consumes. Write that
contract down in BOTH repos (`INTERFACE.md`) so they can evolve
independently and still snap together. Leave short design notes/pointers
under `world/kimi/` in evo-myworld so the lab can follow along, but the
real code lives in the two new repos.

## The characters (this drives the whole aesthetic)

- **Bertrand Hussle** — Bertrand Russell (analytic clarity, logic, the
  precise thinker) FUSED with **Nipsey Hussle** (the marathon, ownership,
  build-your-own-ecosystem, patient hustle, dignity). Rigorous AND
  soulful; disciplined AND street-smart. Terse, every word earns its
  place.
- **Witt** — **Wittgenstein**: language-games, "the limits of my language
  are the limits of my world," meaning-as-use, showing vs saying. The
  Witt Brain is the thinking organ meant to HOLD A ~9B-PARAM MODEL
  locally; the BH CLI is its mouth/hands.

Design the interface to FEEL like these minds. Minimal-ish header
(token-cheap — real hardware) but with special, deliberate visual
touches: considered color, a signature glyph/sigil, restrained
motion/spinner, a voice in the copy. A thing with a soul, not corporate.

## Starting points (real code on this box — READ before designing)

- **Raven** = EverMind's "Self-Improving Agent Harness" (on EverOS), at
  `/library/repos/EverMind-AI_raven/code` — Nicholas: THIS is the
  starting point for the CLI, re-expressed in Rust. Study `ui-tui/`,
  `bridge/`, `raven/`, `AGENTS.md`, `CONTEXT-MAP.md`. Steal the good
  bones, not the branding.
- **Witt (existing)** = `/projects/witt` — Nicholas's Rust orchestration
  CLI (edition 2021, clap), already wrapping ZeroClaw crates (see
  `Cargo.toml`, `src/main.rs`, `src/router.rs`, `src/memory.rs`,
  `src/intent.rs`). Witt "uses ZeroClaw as its starting point then
  improves around it." Your `/projects/witt-brain` builds on/around this
  — reuse, don't duplicate.
- **ZeroClaw** = `/library/repos/zeroclaw-labs_zeroclaw/code/crates/*` —
  the Rust agent stack witt already depends on.
- **Rust corpus** for CLI/TUI craft: `Canop_broot`, `Julien-cpsn_ATAC`,
  `Nukesor_pueue`, `GyulyVGC_sniffnet`, `BurntSushi_ripgrep` (args +
  output), `PyO3_pyo3` (Rust↔Python — HOW you keep a Rust base but still
  call good Python, incl. an eventual 9B model via a python inference
  layer). `world/backend/evo_graph.py find <term>` searches all 599 repos.

## Deliverables

In `/projects/bertrand-hussle`:
1. `DESIGN.md` — concept, character voice, visual system (palette, sigil,
   header, spinner, how output reads), command surface (verbs), and WHY
   Rust-with-Python (the PyO3/RPC boundary). Cite the raven/witt/corpus
   files behind each idea.
2. Rust skeleton: `Cargo.toml`, `src/main.rs` (clap stubs), `theme.rs`
   (visual system AS CODE — colors, glyph, header render), `bridge.rs`
   (Python-call boundary stub). Aim for structurally-`cargo check`-clean;
   note if it couldn't compile here.
3. `PERSONA/` — the soul as editable files: `about-me.md` (first-person
   who BH/Witt are), `rules.md`, `protocols.md`, `guardrails.md`,
   `automations.md` (nice automations riding the strong structure — each
   with its trigger). Authored, not templated.
4. `INTERFACE.md` — the BH↔Witt contract from BH's side.

In `/projects/witt-brain`:
5. `DESIGN.md` — how it holds a ~9B model (where inference lives —
   python/llama side — and how Rust talks to it), memory, and its
   Wittgensteinian character. Relate to `/projects/witt`.
6. Rust skeleton stub + `INTERFACE.md` (the same contract from Witt's
   side — must match BH's).

## Rules

- Read real files first; cite them. Don't invent APIs — quote actual
  crate/module names from witt/zeroclaw/raven.
- Rust is the base; Python where it earns it (inference, graph tools) —
  show the boundary explicitly.
- Token-lean at RUNTIME; the DESIGN docs can be rich. Beautiful AND
  functional.
- `git init` + first commit in BOTH repos. Append 2-3 findings to
  evo-myworld `FIELD-NOTES.md` signed "kimi". Don't commit in evo-myworld.
