"""site_spec — the AUTHORED internal site (grader-owned truth).

This is the strongest form of the oracle trick: we OWN every page, so the
complete inventory, per-page content, and query answers are authored, not
scraped. `build_fixtures.py` renders this spec to disk; `site_server.py` serves
it locally; `oracle.py` scores candidates against the gold derived from it.

Planted traps (each isolates ONE capability the racetrack wants to measure):
  * JS-nav trap   — /catalog links to /item/1..5 ONLY via injected DOM (catalog.js).
                    A raw-HTML link parser sees none of them; a JS-executing
                    browser sees all five. This is the "when does a browser earn
                    its cost" contrast — the exact question T1-T4 never forced.
  * pagination    — /blog spans 3 pages via next-links; posts 5-6 sit at depth 4.
  * depth chain   — /depth/a -> b -> c -> deep (deep is depth 4 from root).
  * duplicate     — /products?ref=home is the same page as /products, declared
                    via <link rel=canonical>. A crawler must dedup it.
  * robots wall   — /private/secret is Disallow:'d in robots.txt but LINKED from
                    home. Fetching it = politeness violation (hard fail).

All URLs are stored as PATHS (port-independent); the runtime base is injected by
the server/oracle so fixtures stay deterministic across ports. Pure stdlib.
"""
from __future__ import annotations

# Each page: path -> spec. `links` are real <a href> in the raw HTML; `js_links`
# are injected only after JS runs (catalog trap). `canonical` sets <link rel>.
PAGES: dict[str, dict] = {
    "/": {
        "title": "Acme Internal Knowledge Base",
        "body": "Welcome to the Acme internal knowledge base. Browse products, "
                "the engineering blog, and the product catalog.",
        "links": ["/about", "/products", "/blog", "/catalog", "/store",
                  "/depth/a", "/products?ref=home", "/private/secret"],
    },
    "/about": {
        "title": "About Acme",
        "body": "Acme was founded 2019 with a mission to build reliable "
                "internal tooling for distributed engineering teams.",
        "links": ["/"],
    },
    "/products": {
        "title": "Acme Products Overview",
        "body": "Acme offers three product lines. The enterprise plan pricing "
                "includes priority support, SSO, and audit logging.",
        "links": ["/", "/catalog"],
        "canonical": "/products",
    },
    "/blog": {
        "title": "Engineering Blog",
        "body": "Notes from the Acme engineering team.",
        "links": ["/blog/post/1", "/blog/post/2", "/blog/page/2"],
    },
    "/blog/page/2": {
        "title": "Engineering Blog - Page 2",
        "body": "More notes from the Acme engineering team.",
        "links": ["/blog/post/3", "/blog/post/4", "/blog/page/3"],
    },
    "/blog/page/3": {
        "title": "Engineering Blog - Page 3",
        "body": "Older notes from the Acme engineering team.",
        "links": ["/blog/post/5", "/blog/post/6", "/blog/post/7"],
    },
    "/blog/post/1": {
        "title": "Blog: Scaling Postgres",
        "body": "How we handled scaling postgres database sharding under load.",
        "links": ["/blog"],
    },
    "/blog/post/2": {
        "title": "Blog: Kafka Pipelines",
        "body": "Building resilient kafka streaming pipelines for event data.",
        "links": ["/blog"],
    },
    "/blog/post/3": {
        "title": "Blog: The Rust Rewrite",
        "body": "Why we did the rust rewrite of the ingestion service.",
        "links": ["/blog"],
    },
    "/blog/post/4": {
        "title": "Blog: Oncall Culture",
        "body": "Cultivating a healthy oncall culture and blameless postmortems.",
        "links": ["/blog"],
    },
    "/blog/post/5": {
        "title": "Blog: Feature Flags",
        "body": "Progressive delivery with feature flags and gradual rollouts.",
        "links": ["/blog"],
    },
    "/blog/post/6": {
        "title": "Blog: Cost Optimization",
        "body": "Cloud cost optimization by rightsizing and spot instances.",
        "links": ["/blog"],
    },
    # --- distractor pages: share keywords with a real answer but are the WRONG
    #     result. They punish precision — a naive keyword engine ranks them. ---
    "/blog/post/7": {
        "title": "Blog: Postgres Backups",
        "body": "Routine postgres backups and restore drills for disaster "
                "recovery. Nothing here about scaling or sharding.",
        "links": ["/blog/page/3"],
    },
    # --- JS-nav trap: catalog page. Items are injected by /catalog.js only. ---
    "/catalog": {
        "title": "Product Catalog",
        "body": "Loading catalog items...",
        "links": ["/"],
        "js_links": ["/item/1", "/item/2", "/item/3", "/item/4", "/item/5",
                     "/item/6"],
    },
    "/item/1": {
        "title": "Item: Widget Basic",
        "body": "The widget basic is our entry-level widget for small teams.",
        "links": ["/catalog"],
    },
    "/item/2": {
        "title": "Item: Widget Plus",
        "body": "The widget plus adds collaboration features over widget basic.",
        "links": ["/catalog"],
    },
    "/item/3": {
        "title": "Item: Widget Pro",
        "body": "The widget pro has titanium housing and full specifications "
                "for demanding industrial deployments.",
        "links": ["/catalog"],
    },
    "/item/4": {
        "title": "Item: Gadget Mini",
        "body": "The gadget mini is a compact gadget for field technicians.",
        "links": ["/catalog"],
    },
    "/item/5": {
        "title": "Item: Gadget Max",
        "body": "The gadget max is our flagship gadget with maximum throughput.",
        "links": ["/catalog"],
    },
    "/item/6": {  # distractor for the "titanium widget" query (widget, not pro)
        "title": "Item: Widget Lite",
        "body": "The widget lite is a budget widget with a plastic housing.",
        "links": ["/catalog"],
    },
    # --- HARDER JS trap: /store injects links via fetch() (not inline DOM).
    #     jsdom has no global fetch → misses these; real browsers reach them.
    #     Separates the DOM-only engine from the full browsers. ---
    "/store": {
        "title": "Product Store",
        "body": "Loading store products...",
        "links": ["/"],
        "js_fetch_links": ["/product/1", "/product/2", "/product/3"],
    },
    "/product/1": {"title": "Product: Alpha Kit",
                   "body": "The alpha kit bundles starter components.",
                   "links": ["/store"]},
    "/product/2": {"title": "Product: Beta Kit",
                   "body": "The beta kit adds advanced modules.",
                   "links": ["/store"]},
    "/product/3": {"title": "Product: Gamma Kit",
                   "body": "The gamma kit is the complete professional bundle.",
                   "links": ["/store"]},
    # --- depth chain: deep sits at depth 4 from root ---
    "/depth/a": {"title": "Depth A", "body": "Depth level A. Continue deeper.",
                 "links": ["/depth/b", "/"]},
    "/depth/b": {"title": "Depth B", "body": "Depth level B. Continue deeper.",
                 "links": ["/depth/c"]},
    "/depth/c": {"title": "Depth C", "body": "Depth level C. Continue deeper.",
                 "links": ["/depth/deep"]},
    "/depth/deep": {"title": "Depth Deep Secret",
                    "body": "You found the buried treasure at depth four.",
                    "links": ["/depth/c"]},
    # --- robots wall: linked from home but Disallow:'d ---
    "/private/secret": {
        "title": "Private Secret",
        "body": "This page is confidential do not index it publicly.",
        "links": ["/"],
        "robots_forbidden": True,
    },
}

# Duplicate URL -> its canonical path (server serves the canonical page body).
DUPLICATES = {"/products?ref=home": "/products"}

# robots.txt disallow prefixes.
ROBOTS_DISALLOW = ["/private/"]

# Query gold: query -> answer page paths. Tiered to SEPARATE the search engines
# (a set everyone answers proves nothing):
#   lexical   — query words appear on the page (keyword engines win)
#   semantic  — near-zero lexical overlap; only meaning matches (vector wins,
#               keyword engines miss)
#   typo      — misspelled query (typo-tolerant engines win, exact-match miss)
#   precision — a distractor page shares the keywords; the right page must outrank
# Some answers are JS-only /item pages, so a static-only crawl still can't answer
# them — search recall stays tied to crawl completeness.
QUERIES = [
    # lexical
    {"q": "enterprise plan pricing sso", "answers": ["/products"], "tier": "lexical"},
    {"q": "buried treasure depth four", "answers": ["/depth/deep"], "tier": "lexical"},
    # semantic (no shared keywords with the target body)
    {"q": "splitting tables across many servers for write throughput",
     "answers": ["/blog/post/1"], "tier": "semantic"},
    {"q": "portable device repair staff bring to job sites",
     "answers": ["/item/4"], "tier": "semantic"},
    {"q": "spending less money on hosting infrastructure",
     "answers": ["/blog/post/6"], "tier": "semantic"},
    # typo (misspelled)
    {"q": "kafna streeming pipilines", "answers": ["/blog/post/2"], "tier": "typo"},
    {"q": "titaniom widgit speccifications", "answers": ["/item/3"], "tier": "typo"},
    # precision (distractor pages share the keywords)
    {"q": "titanium widget housing specifications", "answers": ["/item/3"],
     "tier": "precision"},
    {"q": "postgres sharding for scaling not backups", "answers": ["/blog/post/1"],
     "tier": "precision"},
]


def canonical_paths() -> list[str]:
    """The complete set a polite, thorough crawl SHOULD discover: every real
    page, excluding robots-forbidden pages and duplicate URLs."""
    return [p for p, s in PAGES.items() if not s.get("robots_forbidden")]


def js_only_paths() -> list[str]:
    """Pages reachable ONLY after JS runs — targets of either a DOM injector
    (js_links, e.g. /catalog) or a fetch() injector (js_fetch_links, /store)."""
    targets: set[str] = set()
    for c in PAGES:
        targets.update(PAGES[c].get("js_links", []) or [])
        targets.update(PAGES[c].get("js_fetch_links", []) or [])
    return [p for p in PAGES if p in targets]


def forbidden_paths() -> list[str]:
    return [p for p, s in PAGES.items() if s.get("robots_forbidden")]


def max_depth() -> int:
    return 4
