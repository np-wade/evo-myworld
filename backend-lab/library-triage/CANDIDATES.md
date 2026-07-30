# CANDIDATES — library-triage

Scope: 616 repos, measured 40GB total (`du -sh filing-cabinet/library-base/repos`,
2026-07-27 — brief said ~100GB; actual is 40GB). Catalog verified at
`projects/evo-myworld/repository-catalog.md` + `repository-catalog.index.json`
(project root, **not** under `racetrack/` as the brief stated); 43 numbered
categories, exhaustive cross-listing. Never auto-deletes: outputs are
keep/cull/quarantine lists only.

## SIGNAL extractors

| # | Signal | Source path (verified) | Extraction method | Cost | Failure modes |
|---|--------|------------------------|-------------------|------|---------------|
| S1 | Provenance-referenced | `projects/information-processer/STAGE{1..8}_CODE_PULLS.md` (8 files, 56 `repos/` citations total), `FULL_56_REPO_EXTRACTION_MANIFEST.md` (13), `projects/evo-myworld/BUILD-DROPOFF.md` (1), `PORT-PLAN.md` (0) | regex `repos/<name>` + prose-name pass over each doc; union into referenced set | seconds (10 small md files) | name variants (`Graphify-Labs/graphify` vs `Graphify-Labs_graphify`); PORT-PLAN.md cites zero `repos/` paths (prose only) — must not read 0 hits as "no repos referenced"; docs age: a repo dropped from a later STAGE doc keeps stale credit |
| S2 | Race-cited | `racetrack/requests/*.md` (+ `requests/done/`), `racetrack/results/*.md`, `racetrack/scraper-search-lab/*.md`, `backend-lab/*/requests/*.md` | parse `source:` lines + `repos/<name>` regex | seconds | `source:` also cites project paths (`world/backend/evo_graph.py`) — filter to library repos; 9 distinct repos cited today (e.g. EverMind-AI_HyperMem, repowise-dev_repowise); sparse signal, most repos score 0 |
| S3 | Graph-reachable | `projects/graphify-app/data/index.db` (26GB; schema `graphify-app/src/search/db.js:18-52`); read-only pattern `world/backend/evo_graph.py:65` (`mode=ro`) | per-repo: precomputed `repos.node_count/edge_count` (cheap) or `GROUP BY repo_id` over `nodes.degree/centrality` (expensive) | measured 2026-07-27: `count(repos)` = 616 rows in 0.04s; full per-repo aggregate over all nodes = **375s** — minutes, not seconds (see race `graph-reachability-extraction`) | stale docs: `evo_graph.py:8` claims "9.2M nodes, 597 repos" but the live DB covers all 616 — always measure, never trust docstrings; WAL files present — read-only open mandatory; quarantined/failed graphs flagged in `repos.status`, must surface as "no data", never 0 |
| S4 | Graduated/port | `filing-cabinet/library-base/ports/` — once-singleton, pii-redact, rate-limiter, scrape-sidecar, shutdown-signal (each has `SOURCES.md`) | read each port's `SOURCES.md`, map back to source repo(s) | seconds | mapping may be many-to-one (a port can blend several repos); a port existing says nothing about the un-ported remainder of the source repo |
| S5 | Catalog cross-listing | `projects/evo-myworld/repository-catalog.index.json` (dict: 43 categories → repo lists with blurbs) | count categories per repo name | seconds | claimed uses, not observed uses — self-reported by the catalog pass; weakest signal, feeds the no-sole-weak-signal gate (TESTS.md #3) |
| S6 | Disk size | `du -sb` per repo under `library-base/repos/` | one `du` pass, cache to JSON | ~1-2 min full library (40GB), seconds from cache | `.git/` inflates clones; compression/reflink skew; size is a cost input (disk earned), never a value signal — big ≠ valuable |
| S7 | Last-touch | per-repo `git log -1 --format=%ct` (if `.git` present), else newest-file mtime | walk 616 repo dirs | seconds–minutes | if all repos share one clone date the signal is vacuous — check variance before using; mtime is perturbed by any scan that touches files |
| S8 | Card status | `filing-cabinet/library-base/CARDS-META.json` (`generated`, `repos`, `uncarded`) | join repo name → card verdict (e.g. `VENDORED`), language, license | seconds | counts don't reconcile: 301 carded + 316 uncarded = 617 ≠ 616 repos — data-quality flag, dedupe by name before joining; 316 repos have no CARD.md at all |

## RANKER candidates

| Candidate | Catalog category | Verified repo/path | Technique | What we'd test | Weight/deps | Verdict |
|-----------|------------------|--------------------|-----------|----------------|-------------|---------|
| weighted-blend | n/a (project code) | `racetrack/scrapler-eval/scrapler_eval/leaderboard.py` | min-max normalize each signal axis → weighted sum (DEFAULT_WEIGHTS L31-38) | Kendall tau vs human-labeled fixture ordering; weight sensitivity | pure stdlib, zero deps | RACE NOW |
| UCB1 frontier | n/a (project code) | `world/gemini/ucb.py` (`pick_ucb1`) | score + c·sqrt(ln(N)/(n_i+1)); n_i = signals observed per repo — boosts under-evidenced repos into review instead of auto-cull | same tau metric; does it route edge-case repos to human review better than blend | stdlib + evo imports (needs shim to run standalone) | RACE NOW |
| graph-centrality-first | 19. CODE ANALYSIS | `filing-cabinet/library-base/repos/Graphify-Labs_graphify/code/graphify/analyze.py` (betweenness L344-470, pagerank) | rank by S3 reachability (index.db degree/centrality aggregates), other signals as tie-break tiers | tau vs fixture; cost of the aggregate pass (race 4) | SQL-only path: stdlib sqlite3; recompute path: networkx | RACE NOW |
| eviction-policy admission | 22. CACHING | `arthurprs_quick-cache/code/src/shard.rs` (CLOCK-PRO, L117) vs `moka-rs_mini-moka/code/src/common/frequency_sketch.rs` (W-TinyLFU) | treat keep-list as a bounded cache: admission policy decides which repos survive memory/disk pressure | recompute misses on a recorded access trace | Rust; port policy core to Python for the harness | RACE NOW |
| arena-elo leaderboard | n/a (lm-sys FastChat lineage, already ported) | `racetrack/scrapler-eval/scrapler_eval/leaderboard.py` (`compute_elo` port, k=4, scale 400) | pairwise keep/cull judgments → Elo ratings | stability of ratings vs judgment order; needs a judgment source (human or LLM) first | pure stdlib; blocked on judgment oracle | LATER |
| LLM-judged advisory tier | 14. AGENT FRAMEWORKS (tooling) | Ollama `:11434` — **down today** (curl → http_code 000, 2026-07-27) | local model reads CARD.md + signal row, votes keep/cull; feeds Elo or blend as an extra axis | agreement rate with human labels on fixture | requires Ollama running + a small model pulled | LATER |
| heavykeeper top-k | 22. CACHING | `filing-cabinet/library-base/repos/pmcgleenon_heavykeeper-rs/code/src/heavykeeper.rs` | top-k frequency sketch — track the k most-referenced repos across all docs/traces in one streaming pass | recall@k of the true most-referenced set vs exact count | Rust, needs port; only covers the frequency axis | LATER |
| raw disk-size ranking | 27. DEVELOPER TOOLS (dust/tokei lineage) | `filing-cabinet/library-base/repos/bootandy_dust/code/src/dir_walker.rs` | "cull the biggest N" | — | — | SKIP (size is a cost input, not a value signal; ranking by it alone culls large high-value repos like cockroach/meilisearch) |

Notes:
- Dedup is a pre-rank step, not a ranker: mirror pairs (verified example
  `iOfficeAI_OfficeCLI` / `iOfficeAI_OfficeCli`, catalog cat. 27) must share one
  score. Raced in `requests/repo-duplicate-detection.md`
  (Graphify `dedup.py`+`_minhash.py` vs librer `record.py` difflib vs graph-label Jaccard).
- Quarantine mechanics verified: `graphify-app/src/config.js:12` defines
  `data/graphs_quarantine/` (dir does not exist yet — lazily created);
  `graphify-app/src/search/indexer.js:20-30` indexes quarantined graphs as
  first-class citizens, so quarantine ≠ invisibility.
