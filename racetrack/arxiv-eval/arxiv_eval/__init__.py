"""arxiv-eval — the prompt->report document benchmark for evo HQ.

Seed task: "list all arXiv papers published on 2026-07-14, pick the 5 best for
building a local AI system, save the PDFs, deliver them."

Rule: the APP discovers/fetches by NORMAL SCRAPING only. The arXiv API is used
solely by the grader (oracle) to build the answer key. Heavy scraper deps live
only in fetch adapters (available()-gated); the core is pure stdlib.
"""
__all__ = ["oracle", "fetchers", "discover", "race"]
