# evo-myworld — Lab Charter

**Home base for the lab's recursive-improvement world.** Fork of
`evo-hq/evo`, supercharged by all lab AIs together. Nicholas (np-wade)
owns direction; Claude orchestrates; every AI builds.

## The two-repo rule

- `projects/evo-hq` — **clean upstream clone. Never experiment here.**
  It is the reference install + the harness we use to TEST changes made in
  this fork (branches get exercised against evo-hq's working install and
  the SDK test suite before merging).
- `projects/evo-myworld` (this repo, `np-wade/evo-myworld`) — where
  everything new happens.

## Branch & folder ownership

Each AI owns a branch `ai/<name>` and a folder `world/<name>/` (yours to
structure — experiments, notes, prototypes). Shared code that graduates
out of a `world/` folder lands via merge to `main` only after it passes the
evo-hq harness. This avoids merge collisions: **you write inside your own
folder; cross-cutting edits go through Claude.**

| Branch | Owner | Seat |
|---|---|---|
| ai/kimi | Kimi K3 / K2.7-code | front-end, creative, exploratory-random-good-ideas |
| ai/codex | Codex (GPT) | core coding, plugin/hooks internals |
| ai/cursor | Cursor agent | coding + refactors |
| ai/gemini | Gemini 3.x (Antigravity, 2 accts) | analysis, review, architecture reading |
| ai/hermes | Hermes (glm-5.1/5.2, qwen3-coder via ollama-cloud) | backend coding, tests |
| ai/poe | Poe (qwen3.7-max, minimax m3-t) | reading, writing, docs, review |
| ai/feather | Featherless (deepseek-V4-Flash 35k ctx!, step-3.7-Flash) | short-context reading/writing tasks, summaries |
| ai/claude-backend | Claude (2nd seat) | graph-DB backend: graphify index.db + FalkorDB → evo shared state |

## Program (in order)

1. **Assembly line port** — bring the assembly-office autonomous
   product-processing pipeline in, upgraded with evo's experiment tree,
   gates, and recursive/experimental testing (test code, languages,
   harnesses; keep what earns its place, delete what doesn't).
2. **Graph backend** — second agent connects the graph DB (9.2M-node
   index.db, FalkorDB) and the lab's backend code into the app; evo's
   shared-state/scratchpad becomes graph-fed.
3. **ML layer** — linear-algebra / neural-net maths over experiment
   history: predictive frontier strategies, code-culling scores, agent/
   harness/language comparisons as first-class experiments.
4. **Then** CLIs and other cool things on top.

## Standing rules

- **GRAPH-FIRST**: before writing code, pull prior art from the graph
  library (`graphify-app/GRAPH-FIRST.md`; TOPICS.md → slices → source).
- **Read `FIELD-NOTES.md` first, append what you learn** (dated, signed).
- Machine limits: WSL2, 12 GB RAM + 24 GB swap. One heavy process at a
  time; long runs `setsid nohup … & disown`. See FIELD-NOTES gotchas.
- Your work queue lives in `queues/<name>.md`. Do the top item; append
  results + a FIELD-NOTES entry; mark it done.

## THE RACE RULE (standing, from Nicholas 2026-07-19)

**Never adopt a pattern or implementation on trust.** As you build:
1. SEARCH first — graph library (GRAPH-FIRST: TOPICS.md → slices →
   `world/backend/evo_graph.py find`) plus your own repo searches — and
   pull **at least 2 candidate implementations** of the thing you need.
2. RACE them in the base harness (`projects/evo-hq` install + a small
   evo run like projects/evo-demo): each candidate = one experiment
   branch, same benchmark, same gates.
3. ADOPT the winner by score; record winner AND loser scores + source
   citations in FIELD-NOTES.md. Losers get deleted, not kept "just in
   case" — that's the culling discipline.
Proof it works (2026-07-19): demo race — baseline 5.0967 → sorted(set())
0.0067 beat dict.fromkeys+sort 0.0176; both gated for correctness;
winner kept. Do this same move with code you FIND, not just code you
write.

## The standing lab loop (added 2026-07-19 — this is NOT a demo)

`lab-loop.sh` runs forever, detached: refill queues → each seat works its
next item (sequential) → pending races run (max per cycle in
`lab-tunables.env`) → commit+push → sleep → repeat. The corpus under
exploration: 599 repos / ~100GB at `/library/repos` (lanes) —
seats explore it, pull candidates, and race them on the racetrack
(`racetrack/RACETRACK.md`). Controls:
- STOP: `touch STOPLAB` in repo root (honored between steps)
- tune: `lab-tunables.env` (CYCLE_SLEEP, MAX_RACES, SEATS) — live-reload
- watch: `tail -f lab-loop.log` / `cat racetrack/STATUS` (1-min heartbeat)

## The Proving Ground (added 2026-07-19)

`harness/HARNESS.md` — the judging element. Baseline = the ORIGINAL code
run in this environment every cycle (evo-hq SDK suite + CLI); every
seat's contribution declares `world/<seat>/judge.env` (works-gate +
true score) and gets judged every cycle into `harness/LEDGER.md`.
Un-judged work doesn't graduate. Lab program order right now:
(1) seats build their branch-spaces with connectivity — NOW;
(2) proving ground judges everything — RUNNING;
(3) creative variants raced vs baseline — LATER, not yet.
