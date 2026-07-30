# storage-engine — the generalized knowledge store

**The question:** what should be the ONE store (or small tier-set) where ALL of the user's data lands — AI-processed output, scraped data, and code knowledge — across their apps?
**Why it matters:** today the same knowledge lives in 4+ places (26GB SQLite+FTS5 at `graphify-app/data/index.db`, FalkorDB on :16379, witt-spine's Turso-targeted trunk, markdown+git memory dirs) with no single recall path; every app re-implements storage.
**How candidates graduate:** `CANDIDATES.md` marks each catalog repo RACE NOW / RACE LATER / SKIP; RACE NOW candidates get a `requests/*.md` race (small, seconds-not-minutes); race winners face the full `TESTS.md` suite; losers are culled, citations kept.
**Box reality:** 12GB RAM WSL, 8 cores, docker available (falkordb + ollama images already local), no GPU assumption, system python has no pytest/numpy — fixtures must be generated, small (<10MB), and deterministic.
