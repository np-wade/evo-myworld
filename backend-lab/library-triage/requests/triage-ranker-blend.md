# race: triage-ranker-blend
seat: backend-lab
question: which ranker turns the 8-signal triage table into the most human-aligned keep/cull ordering of the 616 library repos?
metric: max Kendall tau between the candidate's ordering and a 20-repo human-labeled fixture ordering (planted keep/cull/edge cases)
gate: exit 0 iff the output ranks every fixture repo exactly once, is deterministic across two runs with the recorded seed, and no repo kept solely on one weak signal reaches the top-keep tier

## candidate: weighted-blend
source: racetrack/scrapler-eval/scrapler_eval/leaderboard.py
approach: Per-signal min-max normalization then weighted sum (DEFAULT_WEIGHTS pattern, leaderboard.py L31-38); weights tuned on the fixture. Pure stdlib, already battle-tested in scrapler-eval races.

## candidate: ucb1-frontier
source: world/gemini/ucb.py
approach: pick_ucb1-style score + c*sqrt(ln(N)/(n_i+1)) exploration bonus, treating signal-lookup count per repo as n_i; under-evidenced repos get boosted into review instead of auto-culled. Seeded rng for determinism.

## candidate: centrality-first
source: Graphify-Labs_graphify/code/graphify/analyze.py
approach: Rank primarily by graph reachability (index.db degree/centrality aggregates, betweenness/pagerank lineage in analyze.py L344-470), using other signals only as tie-break tiers.
