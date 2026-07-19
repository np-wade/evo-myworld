# The Racetrack — standing race infrastructure

Any seat that finds candidate implementations in the library corpus
(599 repos, ~100GB, `/library/repos` in lanes;
`~/coding/docker-envs/filing-cabinet/library-base/repos` on host) files a
**race request** here. The lab loop runs pending races in the evo harness
(same machinery as the proven evo-demo run) and records results. This is
how "which code deserves to live" gets decided — by score, not opinion.

## Filing a race request

Drop `racetrack/requests/<slug>.md` (slug: short-kebab). Exact format:

```markdown
# race: <slug>
seat: <your seat name>
question: <one line — what capability are we picking the best impl of?>
metric: <min|max> <what the benchmark number means, e.g. "seconds to parse 10MB">
gate: <one line — the correctness condition any candidate must pass>

## candidate: <name-1>
source: <repo>/<path> (from the library corpus or graph slice citation)
approach: <2-3 lines — the technique>

## candidate: <name-2>
source: ...
approach: ...
```

Rules:
- ≥2 candidates, each with a REAL source citation you actually read
  (GRAPH-FIRST slices or direct corpus reads). No invented candidates —
  the point is racing code you FOUND.
- Keep benchmarks small: seconds not minutes, data generated or <10MB.
  This box has 12GB RAM; races run 2 experiments max in parallel.

## What the loop does with it

`run-race.sh <request>` → builds a fresh race repo under
`~/coding/docker-envs/projects/evo-races/<slug>/` (bench.py + gate from
your spec, one experiment branch per candidate), runs it through the evo
harness, then:
- writes `racetrack/results/<slug>.md` (scores, winner, losers, citations)
- moves the request to `racetrack/requests/done/`
- the winner's technique + citation is the ONLY thing that graduates;
  loser code is culled.

Results are append-only lab history — they feed the phase-2 experiment
graph and the ML frontier work.
