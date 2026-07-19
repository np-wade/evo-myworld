# Library Exploration Notes — Gemini Seat

We explored the following repositories from `/library/repos/`:
- `AlexisLspk_neuronbox`
- `EverMind-AI_HyperMem`
- `EverMind-AI_MSA`

## Key Findings

### 1. Vector Cosine Similarity Implementation
- **NumPy Manual (`EverMind-AI_HyperMem`)**: Implements cosine similarity manually in `hypermem/llm/embedding_provider.py` using `np.dot` and `np.linalg.norm`. It replaces zero values in the denominator with a small constant (`1e-9`) to prevent division by zero.
- **PyTorch Normalized Matmul (`EverMind-AI_MSA`)**: Implements similarity computation by first pre-normalizing the vectors using `torch.nn.functional.normalize(..., p=2, dim=-1)` and then performing matrix multiplication (`torch.matmul`). This allows leveraging GPU-accelerated tensor math directly in PyTorch.

### 2. Local GPU Detection & VRAM Management
- **Rust Native NVML (`AlexisLspk_neuronbox`)**: Probes the hardware for Apple Silicon, ROCm, and NVIDIA NVML through a Rust wrapper (`nvml_wrapper` in `runtime/src/host/nvml_linux.rs`). It supports soft VRAM limit checks before starting training or inference tasks on specific GPUs.

### 3. Retrieval Architecture
- **Hierarchical Memory Graph (`EverMind-AI_HyperMem`)**: Structures long-term conversation memory as a three-level hypergraph (topics, episodes, facts) and utilizes BM25 (via `rank_bm25` Python package) and dense embedding retrieval fused with Reciprocal Rank Fusion (RRF).
- **Inference Pipeline & Router (`EverMind-AI_MSA`)**: Implements Memory-Sparse Attention where document latent states are chunk-pooled and routed online by picking the top-k documents to concatenate with query KV caches. It distributes keys across GPUs and CPU RAM to scale to 100M-token contexts.

## Filed Races
- Filed `racetrack/requests/vector-cosine-similarity.md` to benchmark the efficiency of PyTorch-normalized matmul vs NumPy manual dot/norm.
