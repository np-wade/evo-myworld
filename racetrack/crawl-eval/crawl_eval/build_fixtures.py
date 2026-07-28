"""build_fixtures — render site_spec to fixtures/site1/ (grader-only, idempotent).

Writes the raw HTML the server serves + the gold the oracle scores against.
Re-runnable: overwrites deterministically (no timestamps, no randomness), so a
frozen fixture set is byte-stable. This is NOT part of the app path — it's the
answer-key builder (we authored the site, so no scraping is involved).

Layout produced under fixtures/site1/:
  pages/<slug>.html   raw page HTML (JS-nav items NOT present in catalog.html)
  catalog.js          the injector that makes /item/* links appear post-render
  robots.txt          Disallow: /private/
  routes.json         url-path -> pages file / asset  (used by the server)
  gold/inventory.json canonical crawlable set, js-only set, forbidden, dups, depth
  gold/pages/<slug>.json  per-page title/body/links gold (extract scoring)
  gold/queries.json   query -> answer-page paths (search scoring)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import site_spec as S

FIX = Path(__file__).parent.parent / "fixtures" / "site1"


def slug(path: str) -> str:
    """/blog/post/1 -> blog_post_1 ; / -> index"""
    s = path.strip("/").replace("/", "_")
    return s or "index"


def render_html(path: str, spec: dict) -> str:
    parts = ["<!DOCTYPE html>", "<html lang='en'>", "<head>",
             f"<meta charset='utf-8'><title>{spec['title']}</title>"]
    if spec.get("canonical"):
        parts.append(f"<link rel='canonical' href='{spec['canonical']}'>")
    parts += ["</head>", "<body>", f"<h1>{spec['title']}</h1>",
              f"<p>{spec['body']}</p>"]
    if spec.get("links"):
        parts.append("<nav>")
        for l in spec["links"]:
            parts.append(f"<a href='{l}'>{l}</a>")
        parts.append("</nav>")
    # JS-nav trap: an empty container + the injector script. No item <a> here.
    if spec.get("js_links"):
        parts.append("<div id='items'>Loading catalog items...</div>")
        parts.append("<script src='/catalog.js'></script>")
    # Harder trap: links injected via fetch() (jsdom has no fetch → misses them).
    if spec.get("js_fetch_links"):
        parts.append("<div id='store'>Loading store products...</div>")
        parts.append("<script src='/store.js'></script>")
    parts += ["</body>", "</html>"]
    return "\n".join(parts)


def catalog_js() -> str:
    items = S.PAGES["/catalog"]["js_links"]
    ids = [p.rsplit("/", 1)[1] for p in items]
    return (
        "// Injects the catalog item links into the DOM AFTER load.\n"
        "// A raw-HTML link parser never sees these; a JS-executing browser does.\n"
        f"var ITEMS = {json.dumps(ids)};\n"
        "document.addEventListener('DOMContentLoaded', function () {\n"
        "  var c = document.getElementById('items');\n"
        "  if (!c) return;\n"
        "  c.innerHTML = ITEMS.map(function (n) {\n"
        "    return \"<a href='/item/\" + n + \"'>Item \" + n + \"</a>\";\n"
        "  }).join(' ');\n"
        "});\n"
    )


def store_js() -> str:
    return (
        "// Injects store links by FETCHING a JSON endpoint, then building <a>.\n"
        "// jsdom provides no global fetch() -> this throws there and no links\n"
        "// appear; real browsers (playwright/selenium/crawl4ai) have fetch.\n"
        "document.addEventListener('DOMContentLoaded', function () {\n"
        "  fetch('/store-data.json').then(function (r) { return r.json(); })\n"
        "    .then(function (ids) {\n"
        "      var c = document.getElementById('store');\n"
        "      if (!c) return;\n"
        "      c.innerHTML = ids.map(function (n) {\n"
        "        return \"<a href='/product/\" + n + \"'>Product \" + n + \"</a>\";\n"
        "      }).join(' ');\n"
        "    });\n"
        "});\n"
    )


_TAG = re.compile(r"<[^>]+>")


def _text(body: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", body)).strip().lower()


def build() -> dict:
    (FIX / "pages").mkdir(parents=True, exist_ok=True)
    (FIX / "gold" / "pages").mkdir(parents=True, exist_ok=True)

    routes: dict[str, str] = {}
    for path, spec in S.PAGES.items():
        sl = slug(path)
        (FIX / "pages" / f"{sl}.html").write_text(render_html(path, spec))
        routes[path] = f"pages/{sl}.html"
        # per-page extract gold: title + normalized visible body text
        gold_body = _text(spec["body"])
        (FIX / "gold" / "pages" / f"{sl}.json").write_text(json.dumps({
            "path": path, "title": spec["title"], "body_text": gold_body,
            "links": spec.get("links", []),
        }, indent=2))

    # duplicate URLs route to the canonical page's file
    for dup, canon in S.DUPLICATES.items():
        routes[dup] = routes[canon]

    # static asset: the DOM injector
    (FIX / "catalog.js").write_text(catalog_js())
    routes["/catalog.js"] = "catalog.js"

    # static assets: the fetch() injector + its JSON data endpoint
    fetch_ids = [p.rsplit("/", 1)[1]
                 for c in S.PAGES for p in S.PAGES[c].get("js_fetch_links", [])]
    if fetch_ids:
        (FIX / "store.js").write_text(store_js())
        routes["/store.js"] = "store.js"
        (FIX / "store-data.json").write_text(json.dumps(fetch_ids))
        routes["/store-data.json"] = "store-data.json"

    (FIX / "robots.txt").write_text(
        "User-agent: *\n" + "".join(f"Disallow: {p}\n" for p in S.ROBOTS_DISALLOW))
    routes["/robots.txt"] = "robots.txt"

    (FIX / "routes.json").write_text(json.dumps(routes, indent=2))

    inventory = {
        "crawlable": sorted(S.canonical_paths()),
        "js_only": sorted(S.js_only_paths()),
        "forbidden": sorted(S.forbidden_paths()),
        "duplicates": S.DUPLICATES,
        "robots_disallow": S.ROBOTS_DISALLOW,
        "max_depth": S.max_depth(),
    }
    (FIX / "gold" / "inventory.json").write_text(json.dumps(inventory, indent=2))
    (FIX / "gold" / "queries.json").write_text(json.dumps(S.QUERIES, indent=2))

    return {
        "fixtures": str(FIX),
        "pages": len(S.PAGES),
        "crawlable": len(inventory["crawlable"]),
        "js_only": len(inventory["js_only"]),
        "forbidden": len(inventory["forbidden"]),
        "queries": len(S.QUERIES),
        "routes": len(routes),
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
