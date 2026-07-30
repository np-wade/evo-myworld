# race: triage-cache-eviction
seat: backend-lab
question: which admission/eviction policy minimizes signal recomputation when caching per-repo triage signal rows under a memory cap on the 12GB box?
metric: min number of signal-row recomputes (cache misses) replaying a recorded 10k-lookup trace of triage passes over the 616 repos (zipf-ish access with periodic full-library sweeps)
gate: exit 0 iff every cache hit returns a row byte-identical to a fresh recompute of the same (repo, signal) — no stale reads — and peak RSS stays under 512MB

## candidate: clock-pro
source: arthurprs_quick-cache/code/src/shard.rs
approach: Modified CLOCK-PRO eviction with ghost entries (shard.rs L117-119: bounded cache, evicted items returned for drop outside locks); hot/cold clock hands approximate LRU at near-O(1), no frequency sketch to maintain.

## candidate: w-tinylfu
source: moka-rs_mini-moka/code/src/common/frequency_sketch.rs
approach: Caffeine-style W-TinyLFU: 4-bit frequency sketch gates admission so one-off full-library sweep rows never evict hot re-queried repos; window + segmented LRU resident policy.
