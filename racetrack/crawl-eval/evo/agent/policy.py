"""policy.py — the optimizable unit for the T5 evo benchmark.

evo edits THIS file to improve the score. The task: given cheap probe signals
about a target, choose the CHEAPEST fetch tier that will actually reach the
content. Tiers, cheapest first:

    "static"       plain urllib fetch                       (fastest, no stealth)
    "impersonate"  curl_cffi with a browser TLS fingerprint (beats a JA3 wall)
    "browser"      a real headless browser                  (runs JS challenges)

`solve(signals)` returns one of those three strings. `signals` is what a scout
already observed with two cheap probes (a plain static fetch and an impersonating
fetch):

    signals = {
      "static":      {"status": int, "reached": bool, "blocked": bool, "js_hint": bool},
      "impersonate": {"status": int, "reached": bool, "blocked": bool, "js_hint": bool},
    }
    reached  = the target's content marker was present in the response
    blocked  = HTTP 403 (a fingerprint/bot wall)
    js_hint  = a 200 that has <script> but NOT the content (links built by JS)

Scoring rewards reaching content with the MINIMAL sufficient tier:
    reach with the cheapest tier that works -> 1.0
    reach but over-provisioned (heavier tier than needed) -> 0.7
    fail to reach content -> 0.0

=== BASELINE (deliberately naive — this is what evo improves) ===
The starting policy just fetches statically and hopes. It nails plain pages and
fails every wall. The optimization gradient is to learn the escalation ladder:

    if signals["static"]["reached"]:      return "static"
    if signals["impersonate"]["reached"]: return "impersonate"
    return "browser"

That ideal ladder is the empirically-proven result from the T5 races (see
../../results/crawl-suite.md): static for endurance, impersonate for a JA3/h2
wall, a full browser for a JS/behavioral challenge.
"""
from __future__ import annotations


def solve(signals: dict) -> str:
    # BASELINE: always try the cheapest tier. Wins plain pages, loses every wall.
    # evo should replace this with signal-driven escalation.
    return "static"
