# race: vector-cosine-similarity
seat: gemini
question: which batch cosine similarity calculation pattern (PyTorch normalized-matmul vs NumPy manual dot/norm) is more efficient under CPU execution?
metric: min average milliseconds to compute cosine similarity between a batch of 1000 query vectors and 10000 document vectors of dimension 1536
gate: exit 0 iff the calculated similarity scores from both candidates match the ground truth (analytical cosine similarity) within an absolute tolerance of 1e-5 across random vector inputs of varying dimensions

## candidate: numpy-manual
source: /library/repos/EverMind-AI_HyperMem/code/hypermem/llm/embedding_provider.py:27-52
approach: Manual cosine similarity using NumPy `np.dot` and `np.linalg.norm` with division-by-zero protection. Replaces zero values in the norms product denominator with a small constant (`1e-9`) to avoid division by zero.

## candidate: pytorch-normalize-matmul
source: /library/repos/EverMind-AI_MSA/code/src/msa/memory_sparse_attention.py:635-636
approach: Normalizes query and key/document vectors first using PyTorch's `torch.nn.functional.normalize(..., p=2, dim=-1)` (or equivalent norm-division), and then performs a single matrix multiplication `torch.matmul` (or `torch.mm`) to compute the cosine similarity values in a unified batch operation.
