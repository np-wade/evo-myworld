# race: cross-app-entity-resolution
seat: backend-lab
question: best way to resolve the same repo across filing-cabinet CARDs, graphify-app cloned__library__ dirs, and assembly-runs manifests to ONE canonical id?
metric: max — F1 on 200 gold pairs (100 same-entity across apps, 100 hard negatives), ties broken by wall-clock
gate: the Graphify-Labs_graphify / cloned__library__Graphify-Labs__graphify__htef7z triple must resolve to one id; EverMind-AI_HyperMem vs EverMind-AI_EverMemBench must NOT merge; <60s total including any Ollama calls

## candidate: normalized-name-exact (baseline)
source: filing-cabinet/library-base/CARDS-META.json + repos/*/CARD.md (owner_repo naming) matched against projects/graphify-app/data/graphs/cloned__library__* dir names
approach: lowercase, strip cloned__library__ prefix and hash suffix, normalize _/- separators, exact-match join. Deterministic, free, and the bar every smarter contender must beat.

## candidate: cosine-threshold-gate
source: filing-cabinet repos TencentCloud_tencentdb-agent-memory/code/src/core/record/l1-dedup.ts (recall-then-gate shape) + witt-spine/crates/spine-trunk/src/dedup.rs (SKIP 0.97 / UPDATE 0.85 thresholds)
approach: embed name+one-liner via Ollama :11434, recall top-k by cosine, threshold maps pair to same/update/new. One embedding pass over 616 CARDs, then pairwise gates on the 200 gold pairs.

## candidate: llm-batch-judge
source: filing-cabinet repos TencentCloud_tencentdb-agent-memory/code/src/core/prompts/l1-dedup.ts (batch conflict prompt, single-call shape)
approach: candidate pairs pre-filtered by name similarity, then one batched Ollama call judges same/different with reasons. Slowest per pair but should win the hard negatives (same-owner, near-name repos).

## candidate: embedding-cluster-align
source: filing-cabinet repos growgraph_ontocast/code/ontocast/tool/agg/entity_aligner.py (EntityAligner: normalize -> embed -> cluster at cosine 0.80)
approach: cluster ALL app-side representations globally; each cluster gets one canonical id. Unsupervised — no pairwise gate — so the race measures whether cluster purity beats the threshold gate on the same gold pairs.
