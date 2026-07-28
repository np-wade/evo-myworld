"""crawl-eval (T5) — the internal crawl+search benchmark for evo HQ.

Seed task: "Crawl this internal site completely; build a searchable index of
every page; answer these queries with the exact pages that satisfy them; deliver
a report."

The site is AUTHORED (we own it) so the truth is perfect and offline — the
strongest form of the oracle trick. Planted traps force the questions T1-T4 never
could: a JS-nav wall (when does a browser beat a fetcher?), a robots wall
(politeness), a depth chain + pagination (thoroughness), and a duplicate URL
(dedup). The search bracket (stdlib-BM25 / tantivy / meilisearch / qdrant)
finally races because there's a real multi-page corpus to index.

App path = normal crawling only. Heavy engine/index deps live in available()-gated
adapters; the core is pure stdlib.
"""
__all__ = ["site_spec", "build_fixtures", "site_server", "oracle",
           "fetchers", "crawl", "extract", "index", "race", "pipeline",
           "hardened", "stealth", "http2fp", "challenge"]
