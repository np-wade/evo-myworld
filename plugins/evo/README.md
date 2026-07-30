# evo

The evo plugin for Claude Code and Codex. Ships the evo:discover and
evo:optimize skills plus a bundled `bin/evo` wrapper.

For installation, usage, and documentation, see the main repo README:
https://github.com/evo-hq/evo

## Recursive agent control

This fork adds a durable mission DAG inside the workspace's `.evo/graph.json`.
Missions express bounded research/build/verify/integrate intent and dependencies;
the existing Evo experiment tree remains the only Git/worktree lineage.

```bash
# Create evidence-backed work, then let the dependency state unlock the build.
evo mission create --title 'Find source-backed candidates' --kind research \
  --brief 'Use Graphify slices; attach exact source evidence.'
evo mission create --title 'Implement the winner' --kind build \
  --brief 'Race candidates under the same gates.' --depends-on mission_0000
evo mission list --status ready
evo mission claim mission_0000 --owner-exp exp_0001
evo mission complete mission_0000 --status succeeded --summary 'Evidence recorded.'

# One control surface over the canonical dispatch/directive lifecycle.
evo agent start --parent root -m 'Run the ready mission' --background
evo agent list --running
evo agent steer --exp-id exp_0001 'Read the cited source range before editing.'
evo agent message-status EVENT_ID
```

`evo agent start` has the same host support as `evo dispatch`; it deliberately
does not pretend to launch an unsupported host. Recursive expansion is bounded
by per-mission depth and child caps, and no agent can self-approve a promotion.

## LLM-as-judge (qualitative scoring)

The benchmark metric is a single scalar. `evo judge` adds a qualitative
LLM-as-judge (G-Eval) that scores any output against a rubric, normalized to
`[0, 1]` with a reason. It drives Claude through the same `claude -p` path as
dispatch (no API key; honors `EVO_JUDGE_MODEL` / `EVO_CLAUDE_BIN`).

```bash
# Score with a built-in rubric (see `evo judge --list-presets`).
evo judge --preset diff_matches_brief --output-file change.patch \
  --context 'Brief: add retry with backoff to the HTTP client.'

# Or an ad-hoc rubric; output can come from --output, --output-file, or stdin.
git diff | evo judge --task 'Review this change.' \
  --criteria 'Score 0-10: is it minimal, on-scope, and style-matching?'
```

Set `EVO_JUDGE_ON_COMMIT` (or config `judge_on_commit`) to a preset name to
auto-score every committed diff during `evo run`; the `JudgeResult` is written
onto the node (`node.judge`) and into `result.json`, so the frontier carries
judged evidence alongside the raw metric. It is off by default (each judge is a
model call), best-effort, and never blocks a commit. The judge module is adapted
from comet-ml/opik's G-Eval (Apache-2.0).

## Parameter tuning (`evo tune`)

The experiment tree optimizes *code*; `evo tune` optimizes *numeric/categorical
parameters* of a fixed target (temperature, a LoRA rank, a threshold, a batch
size) by searching a declared space against the same benchmark + metric. Each
trial exposes its sampled params to the benchmark via `EVO_PARAMS` (JSON) and
`EVO_PARAMS_FILE`, and the score is read exactly as `evo run` reads it.

```bash
# space.json: {"temperature": {"type":"float","min":0.0,"max":1.5},
#              "n_examples":  {"type":"int","min":0,"max":8},
#              "strategy":    {"type":"categorical","choices":["a","b","c"]}}
evo tune --params space.json --trials 30 --seed 0
```

Uses Optuna's TPE sampler when `optuna` is installed (`pip install
evo-hq-cli[tune]`); otherwise it falls back to a built-in, seedable random
search. Results (best params/score + every trial) are written to
`.evo/run_*/tuning/<ts>/{result.json,trials.jsonl}`. Adapted from comet-ml/opik's
ParameterOptimizer (Apache-2.0).

## Graphify bridge (`evo graph`)

`evo graph` is the knowledge-and-selection backbone: it **retrieves** proven,
source-backed prior art from a Graphify code-graph library (a read-only index of
many indexed repos) and **writes back** an experiment evidence graph so the next
cycle can learn from what won, lost, and why. Retrieval only proposes candidates;
gates and measured results — never graph centrality — decide winners.

```bash
# Retrieve: ranked full-text search over the immutable library index.
evo graph find "content-addressed artifact store" --limit 5

# Traverse: 1-hop neighbors / bounded 1–2-hop subgraph around a node.
evo graph neighbors <repo_id> <node_id> --direction in      # "who calls X"
evo graph subgraph  <repo_id> <node_id> --hops 2

# Contract: a ranked, deduped, repo-diverse candidate set with provenance.
#   Each candidate carries source_location, degree, and a license marked
#   `unverified` until you check it — vendoring requires a manual license/
#   boundary review.
evo graph candidates "better regression gate" --out candidates.json

# Inject prior art into an experiment brief (read-only). Off by default in the
# library; explicit `evo graph inject` always injects. Auto-injection during a
# run is opt-in per run via EVO_GRAPH_INJECT=1.
evo graph inject --brief-file brief.md --need "faster FTS ranking"

# Write back: record an Evo experiment node into the evidence graph, then query
# its lineage and what it beat. The evidence DB lives at
# `.evo/graph/evidence.db` — a SEPARATE database; the source index stays
# immutable during experiments.
evo show <exp_id> --json | evo graph record --agent claude --environment native
evo graph lineage <exp_id>          # DERIVED_FROM ancestry + BEAT edges
evo graph stats                     # node/edge/artifact counts
evo graph export --out evidence.json
```

The bridge points at a Graphify data dir via `$GRAPHIFY_DATA` (or `--data-root`).
Its node/edge/failure vocabulary lives in `evo.graph.schema`; write-back nodes
are content-addressed (SHA-256) and MERGE-upserted so recursive agents converge
instead of duplicating. Retrieval promotes the phase-1 read-only bridge in
`world/backend/evo_graph.py` (still present); the traversal, candidate contract,
evidence write-back, and injection are adapted with in-file attribution from
graph-first prior art (graphify `serve.py`, tencentdb-agent-memory, apache/airflow
OpenLineage, apache/openwhisk `ArtifactStore`, PostHog `TraceNeighborsQuery`,
HKUDS `SqliteStrategyStore`).
