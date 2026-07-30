# interlinking — identity, links & retrieval across everything

Question: how does every entity (repo, document, scrape artifact, agent run, concept, person) get ONE canonical identity and get linked/joined across all of the user's apps — and what retrieval ranks those links best?
Why: today each app invents its own id (SHA-256 evidence uids, UUID rooms, CARD paths, `cloned__library__*` graph dirs, URL/DOI citations), so the same thing exists N times and nothing joins cleanly; dedup and lineage queries pay the price.
How candidates graduate: anything marked RACE NOW in `CANDIDATES.md` gets a race request in `requests/` (exact racetrack format, ≥2 verified candidates, seconds-scale, <10MB fixtures).
Races measure one number (dedup ms/record, resolution F1, recall@k, rerank nDCG) behind an executable correctness gate; winners ship back into the incumbent stores (`evo/graph/writeback.py`, `world/backend/evo_graph.py`, `witt-spine`).
Non-goals: the FTS latency race is already filed at `racetrack/requests/backend-query-ranking.md` — we extend its contender field via recall/rerank races, we do not re-run it.
