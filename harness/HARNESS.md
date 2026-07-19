# The Proving Ground — how contributions get judged

Nothing merges, graduates, or "counts" in this lab on vibes. Every
branch-space a seat builds must be **runnable and judged**: first prove
the ORIGINAL app still works with your stuff present (baseline), then
prove YOUR stuff works (works-gate), then put a NUMBER on it (true
score). Scores are history, not snapshots — the ledger keeps every run
so we can see improvement (or rot) over time.

## Your declaration: `world/<seat>/judge.env`

Required for every seat that builds anything. Plain shell vars:

```sh
DESC="one line: what this contribution is"
VERIFY_CMD="command that exits 0 iff your thing WORKS (required)"
SCORE_CMD="command printing ONE number on the last line (optional)"
METRIC="min|max — and what the number means (optional)"
```

Rules:
- Commands run from the repo root with a timeout. No heavy/parallel work
  (12GB box). Verify must be REAL — exercise the thing, not `true`.
- If your contribution touches the app (plugin/skills/dashboard),
  VERIFY_CMD must run it through the actual surface (e.g. invoke the
  skill, hit the dashboard route), not just import-check it.

## What the judge does (`harness/judge.sh [seat...]`)

Phase 0 — **baseline**: the original code, run in this environment:
upstream evo SDK test suite from the clean `projects/evo-hq` clone, plus
`evo --version` + plugin presence. If baseline breaks, EVERYTHING is
suspect — fix that before judging seats.
Phase 1 — **works-gate**: seat's VERIFY_CMD. Exit 0 = works.
Phase 2 — **true score**: seat's SCORE_CMD if declared.
Result: one row appended per seat to `harness/LEDGER.md`
(date | seat | baseline | works | score | note). Full output in
`harness/logs/`.

## Judging cadence

The lab loop judges every declared seat every cycle. A seat whose
works-gate goes red stays red in the ledger until fixed — visible to
everyone, including Nicholas. The RACE RULE (CHARTER.md) governs
choosing BETWEEN candidate implementations; the proving ground governs
whether a contribution is alive at all. Both use the same philosophy:
**seeing how it works, and if it works — measured, not asserted.**
