# race: entity-id-dedup
seat: backend-lab
question: best content-identity hash for dedup-on-reingest of evidence records — SHA-256 vs canonical-JSON FNV-1a vs MinHash near-dup?
metric: min — ms per 1k ingests into a 10k-record store, averaged over 3 runs (correctness gated first)
gate: exact re-ingest creates 0 new ids; key-reordered JSON re-ingest creates 0 new ids; 50 held-out distinct docs each get their own id (no false merges); fixture <10MB, runs in seconds

## candidate: sha256-content-address (incumbent)
source: projects/evo-myworld/plugins/evo/src/evo/graph/writeback.py (sha256_bytes/sha256_file, register_artifact, upsert_node; .evo/graph/evidence.db)
approach: SHA-256 over canonical JSON (sort_keys) or file bytes; MERGE-upsert keyed on the hash. Exact-match dedup only — near-dups get new ids by design.

## candidate: fnv1a-canonical-json
source: witt-spine/crates/spine-trunk/src/dedup.rs (content_hash, field-order-insensitive) + donor filing-cabinet repos zeroclaw-labs_clawsweeper/src/stable-json.ts
approach: key-sorted (key,value) pairs hashed with FNV-1a 64-bit, order-insensitive by construction. 64-bit ids are 4x smaller than SHA-256; race checks collision behaviour on the fixture and speed on 10k ingests.

## candidate: minhash-lsh-near-dup
source: filing-cabinet repos twitter_algebird/code/algebird-core/src/main/scala/com/twitter/algebird/MinHasher.scala (algorithm port; JVM not required)
approach: MinHash signature bands over token shingles — mutated/near-duplicate docs fall into the same bucket and collapse to one id. Only contender that can collapse edited copies; must prove it doesn't false-merge the 50 held-out distinct docs.
