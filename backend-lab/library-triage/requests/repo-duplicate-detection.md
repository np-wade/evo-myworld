# race: repo-duplicate-detection
seat: backend-lab
question: which near-duplicate detection method best flags true duplicate/mirror repos in the library before triage scoring (so dupes share one score)?
metric: max F1 on a planted fixture of duplicate and non-duplicate repo pairs (ground truth: iOfficeAI_OfficeCLI vs iOfficeAI_OfficeCli mirror pair from catalog cat. 27, plus 3 planted near-dup pairs and 4 distinct pairs)
gate: exit 0 iff the known mirror pair scores above the duplicate threshold AND every distinct pair scores below it, with runtime under 120s on the fixture corpus (<10MB)

## candidate: minhash-lsh
source: Graphify-Labs_graphify/code/graphify/dedup.py
approach: 3-shingle MinHash (128 perms) + band-LSH over repo file contents, datasketch-compatible drop-in in code/graphify/_minhash.py (Mersenne-prime hash family, no scipy). Union-find merges candidate pairs.

## candidate: difflib-fuzzy
source: PJDude_librer/code/src/record.py
approach: difflib.SequenceMatcher ratio over sorted filename lists and size histograms (record.py L259,297 pattern: ratio()>threshold), tuned threshold per pair. Pure stdlib, no hashing pipeline.

## candidate: graph-label-jaccard
source: world/backend/evo_graph.py
approach: Jaccard similarity over each repo's norm_label set from graphify index.db (read-only mode=ro pattern, evo_graph.py L65); near-identical symbol inventories imply a mirror. No file reads; blind only to repos whose graph status is not 'ok'.
