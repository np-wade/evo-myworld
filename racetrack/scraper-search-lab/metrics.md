# Metrics that matter + the scoring model

Loose on purpose right now (weights get locked when we cut the race requests).
The model matches Nicholas's idea: **run each candidate over a fixed ladder,
score every item 0–1, sum to a per-candidate total, then blend a few axes into
one leaderboard number** — so you can look at the table and see whose total wins.

## The core loop (per candidate)

```
for item in ladder:              # each site (scraping) or each query (search)
    result = candidate.run(item)
    q = quality(result, answer_key[item])   # 0.0 .. 1.0
    scores.append(q)
coverage_total = sum(scores)                 # "pages you looked at and actually saw"
normalized     = 100 * coverage_total / len(ladder)   # /100, comparable across candidates
```

Then the blended leaderboard score:

```
LEADERBOARD = w1*normalized_quality
            + w2*evasion            # scraping only
            - w3*latency_norm
            - w4*cost_norm
            + w5*robustness
```

Weights `w*` TBD. Default stance: **quality/evasion dominate, latency & cost are
tie-breakers** (a fast tool that gets blocked is worthless).

---

## Scraping axes

| Axis | How it's measured | 0–1 scale |
|---|---|---|
| **Retrieval success** | Did we get real content vs a block/challenge/empty page | 1 = real content, 0 = blocked/empty |
| **Content completeness** | Chars/blocks captured ÷ ground-truth expected (JS, lazy-load, scroll) | ratio, capped at 1 |
| **Evasion** | Bot-detector pass score (bot.sannysoft / CreepJS / nowsecure) | detector's own pass fraction |
| **Latency** | Wall-clock ms per page | normalized vs field, inverted |
| **Cost / footprint** | Proxy bytes + LLM tokens + peak RAM (WSL is memory-capped) | normalized, inverted |
| **Robustness** | Success stddev over N retries | 1 = deterministic, lower = flaky |

## Search axes

| Axis | How it's measured | 0–1 scale |
|---|---|---|
| **Relevance** | precision@k of returned URLs/results vs answer key | fraction relevant |
| **Coverage / recall** | recall of known-good pages that exist | fraction found |
| **Freshness** | recency of returned results vs a dated query | scored by age band |
| **Self-host / zero-key** | needs a paid API? | 1 = fully self-hosted, 0 = API-gated |
| **Latency** | query round-trip | normalized, inverted |
| **(index/vector)** recall@k, MRR/nDCG | retrieval quality over the scraped corpus | standard IR metrics |
| **(index/vector)** build time + **storage footprint** | index a fixed corpus, measure both | normalized, inverted |

---

## Gate (per race)
Every race needs one executable pass/fail gate so the steward can scratch
non-starters. Draft gates:
- **Scraping:** candidate must retrieve real content on Tier 0 (static) — fail = scratched.
- **Search discovery:** must return ≥1 relevant URL for a control query.
- **Index/vector:** must achieve recall@10 ≥ baseline on the frozen corpus.

## Ground truth / fixtures
- Tiers 0–2: **frozen HTML/HAR** + an **answer key** (expected content/fields) → deterministic, re-runnable.
- Tier 3 (anti-bot) + Tier 4 (detectors): **live**, scored by the detector itself (no answer key needed).
- Tier R (real targets): Nicholas supplies URLs + what "success" means for each.

## Open questions to resolve before locking
1. Exact `w1..w5` weights — or keep per-class leaderboards and skip a global blend?
2. How many retries `N` for the robustness axis (WSL time budget)?
3. Which detectors are the evasion oracle (bot.sannysoft is easy; CreepJS is harsh)?
4. Real Tier-R target URLs + their success definitions.
