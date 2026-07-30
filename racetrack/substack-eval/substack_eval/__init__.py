"""substack-eval — the archive-crawl prompt->report benchmark for evo HQ.

Seed task: "Find every post from <newsletter>.substack.com published in the
last 60 days; save the 10 most recent as clean markdown; deliver a table +
files."

Rule: the APP discovers/fetches by NORMAL SCRAPING only (archive HTML page,
sitemap.xml, SERP). Substack's RSS feed and JSON archive API are PRIVILEGED
channels used solely by the grader (oracle / fetch_fixtures.py) to build the
answer key. Heavy scraper deps live only in available()-gated adapters; the
core is pure stdlib.

The 60-day window is PINNED to the fixture's ref_date (2026-07-26) — the
scored path never calls a live now().
"""
__all__ = ["oracle", "fetchers", "discover", "filter", "fetch_stage",
           "extract_stage", "race", "pipeline"]
