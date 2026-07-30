# race: embedded-vector-recall
seat: backend-lab
question: best embedded ANN index for the store's vector arm on this 12GB/8-core box — faiss vs annoy vs LEANN?
metric: max — recall@10 against exact brute-force ground truth on 20k×384 seeded synthetic vectors (cosine); tie-break mean query ms
gate: index builds in <120s, mean query <50ms, and recall@10 ≥0.90 vs the brute-force truth

## candidate: faiss-ivf
source: facebookresearch_faiss/code (benchs/ for the recall-vs-speed methodology)
approach: faiss-cpu wheel; IndexFlatIP computes the exact ground truth, then IndexIVFFlat (nprobe tuned) as the candidate. The reference implementation of the entire field — the one to beat.

## candidate: annoy
source: spotify_annoy/src/annoylib.h (+ annoymodule.cc python bindings)
approach: random-projection forest, 50 trees, angular metric; `pip install annoy`. Static mmap-able index with tiny RAM cost — the lightweight counterpoint: how much recall does the simple option give up?

## candidate: leann-hnsw
source: StarTrail-org_LEANN/code/packages/leann (+ packages/leann-backend-hnsw, benchmarks/)
approach: graph-based ANN with recompute-on-demand storage pruning (claims ~97% footprint saving) — races recall AND bytes-on-disk. `pip install leann`; skip-cleanly if no wheel builds for this box.
