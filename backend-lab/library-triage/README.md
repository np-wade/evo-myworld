# library-triage

Builder D section: evidence-based keep/cull/quarantine triage of the 616-repo / 40GB (measured `du -sh`, 2026-07-27) code library at `filing-cabinet/library-base/repos/`.
Never auto-deletes — output is scored keep/cull/quarantine lists only; quarantine pattern per `graphify-app/src/config.js:12` (`data/graphs_quarantine/`, lazily created).
Signals: provenance refs, race citations, graph reachability (26GB `graphify-app/data/index.db`), graduated ports, catalog cross-listing, disk size, last-touch, card status — extractors in `CANDIDATES.md`.
Rankers to race: weighted-blend, UCB1 frontier, graph-centrality-first, eviction-policy admission — race requests in `requests/`, future tests in `TESTS.md`.
