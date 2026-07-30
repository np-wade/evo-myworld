# race: llm-link-rerank
seat: backend-lab
question: does an Ollama rerank of bm25's top-20 improve the final top-10 enough to pay its latency, vs bm25 order alone vs non-LLM hybrid?
metric: max — nDCG@10 over the 20 gold link queries (labeled targets, graded relevance: exact target 2, same-file symbol 1)
gate: no gold exact-target may be demoted out of the top-10 by the rerank; p95 <2s/query; Ollama unreachable must fall back to bm25 order cleanly, not error

## candidate: bm25-only-order (baseline)
source: projects/evo-myworld/world/backend/evo_graph.py (fts5 bm25 + exact/prefix bonus tiers)
approach: no rerank — top-10 straight from the incumbent ranking. Zero added latency; the bar for nDCG.

## candidate: llm-pointwise-rerank
source: filing-cabinet repos TencentCloud_tencentdb-agent-memory/code/src/core/prompts/l1-dedup.ts (batch-judgment prompt shape) adapted to rerank, served by Ollama :11434
approach: one batched Ollama call scores all 20 candidates per query for relevance to the link intent; reorder by score, keep bm25 order as tiebreak. Cached top-20 candidate lists so the race measures rerank, not retrieval.

## candidate: rrf-hybrid-no-llm
source: witt-spine/crates/spine-trunk/src/recall.rs (RRF k=60 vector+FTS fusion)
approach: non-LLM reorder arm: fuse bm25 rank with embedding-cosine rank via RRF and take the fused top-10. If this matches the LLM rerank's nDCG at 1/10th the latency, the LLM loses.
