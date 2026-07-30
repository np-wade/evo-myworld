"""watchdog-eval — the page-change-monitor benchmark for evo HQ (Test 4).

Seed task: "Watch these 12 pages; each run, report what changed since last
run — what's new, what's gone, what moved."

Oracle trick: WE author the truth. Frozen page-version pairs (v1, v2) carry a
KNOWN injection manifest — real changes (price edits, added/removed items,
reworded paragraphs, deleted sections) plus cosmetic CHURN TRAPS (timestamps,
session tokens, reordered-but-identical lists, rotating ads, cache-busters)
that a good watcher must IGNORE. The manifest IS the answer key.

100% OFFLINE and deterministic. Core is pure stdlib; optional deps
(beautifulsoup4) live only behind available()-gated candidates.
"""
__all__ = ["oracle", "snapshot", "differs", "classify", "race", "pipeline"]
