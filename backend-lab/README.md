# Backend Lab — the generalized everything suite

One question, four sections: **how should all data in this ecosystem get stored,
processed, interlinked, retrieved, and culled — measured, not asserted?**

This is the "big everything" counterpart to the scraping suite
(`racetrack/scrapler-eval`) and the paper suite (`racetrack/arxiv-eval`):
candidates are real repos from the 616-repo library corpus
(`repository-catalog.md` / `repository-catalog.index.json` at the repo root,
converted from `racetrack_repository_catalog.html`), each section identifies
what to test and which candidates to race, and winners graduate through the
racetrack (`racetrack/RACETRACK.md`) by score, not opinion.

## Sections

| Section | Question it answers |
|---|---|
| `storage-engine/` | What is the ONE store (or tier-set) where AI-processed data, scraped data, and code knowledge all land? |
| `interlinking/` | How does every entity get one canonical identity and get linked/retrieved across all apps? |
| `pipelines/` | How does data flow to the right spots — and can we see every hop (contract tests for the 10 live seams)? |
| `library-triage/` | Which of the 616 library repos earn their disk — keep, cull, or quarantine? |

Each section holds:
- `CANDIDATES.md` — every plausible candidate mined from the catalog, with
  verified repo paths and a verdict (RACE NOW / RACE LATER / SKIP + reason).
- `TESTS.md` — the numbered test specs to build (question, metric, gate,
  fixture, budget) — identification first, implementation later.
- `requests/*.md` — race requests in exact `racetrack/RACETRACK.md` format,
  ready to file into `racetrack/requests/` after human review.

## Standing rules (inherited from scrapler-eval CONTRACT)

- Benchmarks are small: seconds not minutes, data generated or <10MB (12GB box,
  max 2 heavy jobs in parallel).
- Real citations only: every candidate names a repo path that exists in
  `library-base/repos` and that the author actually read.
- No auto-deletion anywhere; triage outputs quarantine lists for a human.
- Big real stores (26GB index.db) are exercised skip-cleanly, never copied
  (pattern: `world/backend/test_evo_graph.py`).

Status: **identification pass complete** — see each section's CANDIDATES.md and
TESTS.md. Race requests await review in `*/requests/`.
