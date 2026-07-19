# selfdev — the lab's self-development loop, ported from raven

Source of the design: `EverMind-AI_raven` in the library corpus
(`~/coding/docker-envs/filing-cabinet/library-base/repos/EverMind-AI_raven/code/`,
cited below as `raven:<path>`). Raven's evolver is a budget-bounded loop that
improves an agent HARNESS (prompts, tools, hooks, memory — not the model)
against a benchmark: diagnose failing trajectories → design 1-2 small candidate
patches → prune the inert ones free → screen cheap → confirm expensive → pass
three gates → promote only real, attributed, significant wins — with the test
set physically sealed so nobody can grade themselves on it.
(`raven:raven/evolver/README.md`, `raven:docs/specs/self-evolution-loop-sop.md`,
`raven:raven/evolver/orchestrator/DESIGN.md`.)

## 1. Raven's actual mechanisms (what we're porting)

| # | Raven mechanism | Where it lives (read these) |
|---|---|---|
| R1 | **Seven-step funnel as code, not prompt discipline** — the loop's control flow (rounds, per-candidate fork, parent choice, stop) is a deterministic state machine; the model only answers one small schema-validated question per step | `raven:raven/evolver/orchestrator/loop.py` (EvolutionOrchestrator), `raven:raven/evolver/orchestrator/nodes/semantic.py` (schema + bounded repair retries), DESIGN.md §2 "inversion of control" |
| R2 | **Cross-round living failure map** — diagnosis reads the previous round's failing trajectories and appends to an accumulating `failure_map.json`; drift is auditable; next round's designer sees flip feedback (who got rescued/broken) | `raven:raven/evolver/orchestrator/nodes/diagnose.py` (`merge_failure_maps`), `raven:raven/evolver/analysis/failure_map_builder.py`, `scoring.flip_summary` per DESIGN.md §3 |
| R3 | **Small candidates, few per round** — 1-2 WHYs × 2-3 candidates, each a tiny patch across levers (prompt/config/runtime); every candidate is a git commit + a node-ledger JSON (`nodes/<id>.json`: status, gate stats, WHY/WHERE) | SOP §2 ②④, `raven:raven/evolver/tree/store.py` (`create_child_node`), SOP §3.1 node-ledger schema |
| R4 | **Free pruning before spend** — a candidate whose trigger never fires in historical trajectories is culled at zero cost (`make_zero_hit_preflight`); AST/import smoke kills crashers | `raven:raven/evolver/orchestrator/production.py`, DESIGN.md §3 row ③ |
| R5 | **Path whitelist + immutable kernel** — candidate edits are constrained to a per-bench whitelist; everything else the designer touches is REVERTED; the measurement surface (the evolver itself, the scorer/grader) can never be edited by a candidate | `raven:raven/evolver/applier/path_guard.py`, evolver README "Security notes" |
| R6 | **Three gates before adoption** — Gate-f: infra failures are not scored as 0-and-dropped (denominator = all tasks); Gate-b: credit only where the mechanism actually FIRED (activation_beacon); Gate2: paired significance vs a fixed baseline | `raven:raven/evolver/orchestrator/gates/pipeline.py`, `gates/paired.py`, `raven:raven/evolver/applier/beacon_guard.py` |
| R7 | **Sealed test + honest termination** — test scores are written where no decision step can read them (score() returns None); stop = patience (N rounds nobody beat vanilla) or hard cap, decided by code, never by the test set | `raven:raven/evolver/orchestrator/sealed/runner.py` (`assert_no_test_leak`), `raven:raven/evolver/orchestrator/termination.py` |
| R8 | **Everything resumable, everything a ledger** — per-round journal, `findings.md` human log, config fingerprint refuses to resume under a changed config | `raven:raven/evolver/orchestrator/state/journal.py`, `raven:raven/evolver/launch/state.py` (`RunMeta.check_config`) |
| R9 | **Gated skill/memory injection elsewhere in raven** — the skill forge routes candidates through RRF fusion then an LLM gate that may pick 0 (inject nothing is valid; infra failure falls back to top-k, never silently empties); the context curator/history-trimmer prune context by budget with protected messages | `raven:raven/memory_engine/skill_forge/gate.py`, `raven:raven/context_engine/curator.py`, `raven:raven/context_engine/history_trimmer.py` |

Their ecosystem: EverOS is the durable-memory OS the skills/memory ride on
(`EverMind-AI_EverOS/code`), and EvoAgentBench / EverMemBench are the test
environments the loop is scored in (`EverMind-AI_EvoAgentBench/code` — "agent
self-evolution via ability transfer", train/test splits per domain;
`EverMind-AI_EverMemBench/code`). The pattern is always the same:
**the thing being improved is the harness; the improvement is only believed
when an eval it cannot touch says so.**

## 2. The mapping onto OUR loop

Our loop (`lab-loop.sh`): refill → dispatch seats → bench trail → races →
commit. Raven's roles land like this:

| Raven role | Ours |
|---|---|
| subject harness being evolved | the lab machinery's *editable soft parts*: queue items (`queues/*.md`), seat prompt/call shapes (`queues/dispatch.sh` prompts), gate designs (`world/hermes/gates/`), race candidates, FIELD-NOTES |
| benchmark / eval environment | the **bench** (`bench/BENCH.md` — behavior diffs), the **racetrack** (`racetrack/RACETRACK.md` — competing designs scored in the evo harness), **hermes gates** (`world/hermes/gates/` — correctness/budget/regression/held_out) |
| failing trajectories | `lab-loop.log` (SOFT-FAILs, lane errors), `queues/escalations.md` (2-strike items), `bench/trail.md` (same/different across cycles), `racetrack/results/*.md` (winners AND losers) |
| driver model | one bounded `claude -p` call per cycle (`selfdev/cycle-review.sh`) |
| node ledger / findings.md | `selfdev/CHANGELOG.md` (append-only: date, what, why, evidence) + `selfdev/proposals/` |

### What gets refined across runs, and how each refinement is CHECKED

Raven's rule (SOP §2 ②): change one small thing per round, across levers, and
never adopt without a gate. Ours, per refinement class:

1. **Queue items** (lever: config). Symptom: a seat SOFT-FAILs twice and the
   item lands in `queues/escalations.md`. Refinement: rewrite the item smaller
   or re-route it to a stronger seat's queue. Check: next cycle's dispatch —
   the item either gets ticked (adopted) or escalates again (revert/re-write).
   This is R2's flip feedback: rescued = ticked, regressed = re-escalated.
2. **Seat prompts / call shapes** (lever: prompt). Symptom: repeated soft-fails
   or truncation for one seat class in `lab-loop.log` / `queues/logs/`.
   Refinement: cycle-review may NOT edit `dispatch.sh` (it is our immutable
   kernel, R5) — it writes a concrete diff-shaped proposal to
   `selfdev/proposals/` for the orchestrator. Check: after the orchestrator
   applies it, the seat's tick-rate over the next cycles is the paired
   comparison (before/after on the same queue class), logged in CHANGELOG.
3. **Gate designs** (lever: runtime). Symptom: a race result shows a gate
   passing something wrong or blocking something right. Refinement: proposal
   for `world/hermes/gates/` (hermes's folder, not ours). Check: hermes's
   `test_gates.py` (15 stdlib tests) + a re-race — same discipline raven uses
   in `gates/pipeline.py`: the gate itself is part of the measurement surface,
   so it gets the strictest review.
4. **Race candidates** (lever: knowledge). Symptom: a race ran with weak or
   missing candidates, or a repeated question. Refinement: file/fix a
   `racetrack/requests/*.md` (this IS a queue-adjacent .md edit — allowed).
   Check: the race itself — `run-race.sh` scores it in the evo harness; the
   result file is the gate verdict (R6: winner by score, losers culled,
   append-only results = our honest denominator).
5. **FIELD-NOTES pruning / shaping** (lever: memory). Symptom: the tail-150
   read window (dispatch v2) fills with low-signal entries; seats miss
   standing gotchas. Refinement: consolidate — like raven's curator/trimmer
   (R9), protected entries (standing rules, gotchas) stay, episodic noise gets
   compressed into one dated summary bullet. Check: the bench of behavior —
   do seats stop repeating known mistakes in subsequent cycle logs; CHANGELOG
   records what was compressed so it is reversible from git history.

### The guardrails we copied verbatim

- **One change per cycle** (raven: 3-4 candidates/round on a big budget; we
  are one seat on a 12GB box, so n=1). Small edits only.
- **Whitelist + revert** (R5): cycle-review's claude call may only edit
  `queues/*.md`, `selfdev/**`, `FIELD-NOTES.md`. Anything else it touches is
  reverted by the script (path_guard behavior), and the intended change is
  re-expressed as a proposal file. `lab-loop.sh`, `queues/dispatch.sh`,
  `queues/refill.sh`, `bench/`, `racetrack/*.sh` are the immutable kernel —
  the measurement surface never edits itself.
- **No-op on no evidence** (R4): the script fingerprints the gathered
  evidence; unchanged fingerprint = zero-cost exit, no LLM call. A candidate
  refinement with no failing trajectory behind it would be inert — culled free.
- **Append-only ledger** (R8): every run appends to `selfdev/CHANGELOG.md`
  (date, what, why, evidence), including no-ops with a reason. Nothing is
  adopted silently; everything is auditable and revertible via git.
- **Sealed-eval spirit** (R7): cycle-review never edits race results, trail,
  or gate code, and never marks its own refinement "adopted" — adoption is
  what the NEXT cycle's evidence shows. The termination analogue: if the same
  refinement class keeps failing its check, the CHANGELOG trail is the
  patience counter and the orchestrator (not the script) decides to stop or
  redesign.

## 3. Wiring

The orchestrator adds one line to the lab loop (per Nicholas's instruction we
do not touch `lab-loop.sh` ourselves — proposal:
`selfdev/proposals/` will carry it when ready):

```sh
status "cycle $CYCLE: selfdev review"
./selfdev/cycle-review.sh >>"$LOG" 2>&1 || true
```

Best slot: after races, before commit — the cycle's full evidence exists and
the commit then carries the refinement. Tunables via env:
`SELFDEV_TIMEOUT` (default 600s), `SELFDEV_MODEL` (default: CLI default).
