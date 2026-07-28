# result: crawl-suite (T5) — Internal Crawl + Search

seat: steward + crawl-eval
question: crawl an internal site completely, index it, answer queries — and
settle the two questions T1–T4 never could: (a) WHEN does a browser beat a
fetcher? (b) which search engine wins? (c) how long can a crawler sustain?
metric: crawl P/R/F1 + js_recall + robots gate; extract title/body fidelity;
search recall/MRR; endurance = turns (pages) sustained under a time budget
gate: report saved; robots respected (0 violations); crawl_recall≥.75; search_recall≥.5
oracle: the site is AUTHORED (we own it) → perfect offline gold, no external API
package: crawl-eval/  •  run: `.venv/bin/python -m crawl_eval pipeline`

Seed task: "Crawl this internal site completely; build a searchable index of
every page; answer these queries with the exact pages that satisfy them; deliver
a report." Planted traps isolate one capability each: a **DOM-injection JS wall**
(/catalog links /item/* via an inline script), a harder **fetch-injection JS
wall** (/store pulls /product/* via `fetch()` → separates DOM-only engines from
full browsers), a **robots wall** (/private/secret Disallow:'d but linked from
home), a **depth chain** (/depth/deep at depth 4), a **pagination trail** (/blog
× 3 pages), a **duplicate URL** (/products?ref=home → canonical /products), and
**distractor pages** (share an answer's keywords → precision pressure). 28
crawlable pages, 9 JS-only, 9 tiered queries.

## Crawl race — browser-vs-fetcher, HARDENED into 3 tiers  (results-crawl-run3.json)
Full field, 8 candidates. Two JS traps now: a **DOM-injection** page (/catalog,
inline script) and a harder **fetch()-injection** page (/store, links pulled via
`fetch()` → JSON). gold=28 pages, 9 JS-only.
| candidate | kind | recall | **js_recall** | robots | p50 ms |
|---|---|---|---|---|---|
| 🏆 crawl4ai-crawl | browser | 1.000 | **1.000** | ok | 7,400 |
| selenium-crawl | browser | 1.000 | **1.000** | ok | 10,900 |
| playwright-crawl | browser | 1.000 | **1.000** | ok | 15,900 |
| jsdom-crawl | browser | 0.893 | **0.667** | ok | 22,300 |
| urllib-bfs | static | 0.679 | **0.000** | ok | 44 |
| curl_cffi-bfs | static | 0.679 | **0.000** | ok | 55 |
| scrapling-bfs | static | 0.679 | **0.000** | ok | 83 |
| stdlib-greedy | static | 0.679 | 0.000 | ⚠**1** | 55 |

**Three conclusive tiers, not a tie:** (1) **full browsers** (crawl4ai/selenium/
playwright) reach everything — DOM- *and* fetch-injected — js_recall **1.0**.
(2) **jsdom is DOM-only** — it runs inline injectors but has no global `fetch()`,
so it misses the 3 fetch-injected /product pages (js_recall **0.667**): a
pure-JS DOM engine is cheap but not a real browser. (3) **static fetchers** miss
all JS regardless of backend — curl_cffi's TLS impersonation and Scrapling buy
*nothing* against a JS wall (js_recall **0.000**). A full browser pays ~170–360×
latency (44 ms → 7–16 s) for the pages a fetcher gets free; **crawl4ai is the
fastest full engine** (7.4 s, 2× playwright). greedy trips the robots gate +
dup. **Optimal = static-first, escalate to a full browser only where JS
injection (esp. fetch-driven) is detected.**

## Endurance race — "crawl and crawl and crawl"  (results-endurance-run1.json)
How many TURNS (page-fetches) each engine sustains in a fixed budget (10 s here;
every engine stopped on `timeout`, not error → all could run indefinitely).
| engine | kind | **turns/10s** | pages/s | stable |
|---|---|---|---|---|
| 🏆 urllib-bfs | static | ~4,800 | 477 | yes |
| stdlib-greedy | static | ~4,700 | 469 | yes |
| curl_cffi-bfs | static | ~4,100 | 413 | yes |
| scrapling-bfs | static | ~3,600 | 357 | yes |
| playwright-crawl | browser | 18 | 1.8 | yes |
| jsdom-crawl | browser | 12 | 1.2 | yes |

Plain **urllib is the endurance king** (~477 pages/s → ~28k/min, ~1.7M/hour).
**Stealth costs endurance** (curl_cffi/scrapling shed ~25% throughput for their
impersonation machinery). **Browsers are ~400× slower** — a scalpel for JS
pages, not a marathon crawler. Same architecture the JS-trap points to, from the
opposite angle. Test served by an on-the-fly **endless procedural maze**
(`/maze/<id>`, fanout 3 + deep next-chain); tune with
`endurance-race --seconds N`.

## Stealth race — Tier-R JA3 wall (the gap, now closed)  (results-stealth-run1.json)
The owned site has no anti-bot wall, so urllib==curl_cffi==scrapling there. To
actually test stealth I built a **JA3-fingerprinting HTTPS target** (`hardened.py`):
it peeks the raw TLS ClientHello (`MSG_PEEK`), computes the JA3, and 403s any
client whose fingerprint lacks **GREASE** — the signal that separates a real
browser (and curl-impersonate, which mimics it) from stock Python/libcurl. Cert
verification is off for every client, so the ONLY variable is the fingerprint.
| strategy | resolve | blocked | GREASE | ALPN h2 | JA3 |
|---|---|---|---|---|---|
| 🏆 curl_cffi-chrome | 1.00 | 0.00 | yes | yes | f954cd54… |
| 🏆 curl_cffi-safari | 1.00 | 0.00 | yes | yes | 0ca3c3ef… |
| 🏆 scrapling | 1.00 | 0.00 | yes | yes | 99c88bb9… |
| curl_cffi-plain | 0.00 | **1.00** | no | yes | 53d06205… |
| urllib | 0.00 | **1.00** | no | no | 8a9d5d0f… |

**Three findings the owned site could never surface:** (1) **TLS impersonation is
what beats a JA3 wall** — chrome/safari-impersonating clients + Scrapling resolve;
plain urllib is blocked. (2) **It's the impersonation, not the library** —
`curl_cffi` *without* `impersonate` is blocked just like urllib (both present a
no-GREASE fingerprint); the value is mimicking the browser ClientHello, not using
curl. (3) **Scrapling does real TLS impersonation** (GREASE + distinct browser
JA3), not just header spoofing. Chrome's JA3 rotates per handshake (randomized
GREASE) — authentic browser behavior the wall accepts. Run:
`stealth-race --runs 5`. This is the empirical basis for spider-den defaulting to
a TLS-impersonating fetcher on hostile targets. Note: JA3 is the TLS layer only;
a JS/behavioral challenge (Cloudflare-style) still needs a browser — future
Tier-R+.

## HTTP/2 fingerprint race — the layer above JA3  (results-http2-run1.json)
Real anti-bot stacks fingerprint HTTP/2 too. `http2fp.py` negotiates ALPN, parses
the raw h2 frames, and (via a minimal HPACK decoder) builds the **full Akamai
fingerprint**: `SETTINGS | WINDOW_UPDATE | PRIORITY | PSEUDO_HEADER_ORDER`.
| strategy | h2? | full Akamai h2 fingerprint |
|---|---|---|
| urllib | **NO** | (stock Python can't do HTTP/2 at all) |
| curl_cffi-chrome / scrapling | yes | `1:65536;2:0;4:6291456;6:262144\|15663105\|0\|`**`m,a,s,p`** |
| curl_cffi-firefox | yes | `1:65536;2:0;4:131072;5:16384\|12517377\|0\|`**`m,p,a,s`** |
| curl_cffi-safari | yes | `2:0;3:100;4:2097152;9:1\|10420225\|0\|`**`m,s,a,p`** |

**Findings:** (1) **urllib doesn't speak h2** → an h2-required site flags it
instantly. (2) curl_cffi's impersonation is faithful at the h2 layer too —
chrome/safari/firefox each emit the *correct distinct* real-browser signature,
including the documented **pseudo-header order** (Chrome `m,a,s,p`, Firefox
`m,p,a,s`, Safari `m,s,a,p`); scrapling rides Chrome's. (3) **The layers are
INDEPENDENT** — `curl_cffi-plain` was BLOCKED at the JA3 wall (non-browser TLS)
yet presents a *Chrome* h2 fingerprint here; a WAF checking BOTH catches the
mismatch (a Chrome h2 stack on a non-Chrome TLS handshake = bot). That's why
defense-in-depth fingerprints multiple layers. The full Akamai string
(SETTINGS+WINDOW_UPDATE+PRIORITY+pseudo-header order) is now captured end-to-end.

## Tier-R+ challenge race — TLS wall + JS challenge  (results-challenge-run1.json)
Two layers stacked: the JA3 wall AND a Cloudflare-style JS challenge where the
content link is assembled by JS from fragments (no literal in the raw HTML, so a
regex can't shortcut it). To reach content a client needs BOTH a browser TLS
fingerprint AND a JS engine — which finally separates stealth FETCHERS from real
BROWSERS (JA3 alone couldn't).
| strategy | kind | outcome |
|---|---|---|
| 🏆 crawl4ai · playwright · selenium | browser | **solved** (browser TLS + runs JS) |
| curl_cffi-chrome · scrapling | fetcher | 🧱 **challenged** (pass JA3, no JS engine) |
| urllib | fetcher | ⛔ **blocked** (no GREASE → JA3 403) |
| jsdom | browser | ⛔ **blocked** (runs JS, but Node TLS has no GREASE) |

**The conclusive stealth ceiling:** only a full real-browser stack (real
Chromium) beats a layered TLS+JS defense. A stealth *fetcher* clears the TLS
layer but has no JS engine → stuck on the challenge. **jsdom** is the mirror
image — it runs JS but its Node/OpenSSL TLS lacks GREASE, so it's blocked at the
network layer before JS even matters. This is the empirical basis for spider-den
escalating a hard target all the way to a real browser, not just a stealth fetch.

## Extract race  (results-extract-run1.json)
| extractor | title_acc | body_f1 | ms |
|---|---|---|---|
| 🏆 css-json | 1.000 | 0.936 | 1.1 |
| trafilatura | 1.000 | 0.896 | 245 |
| rule | 1.000 | 0.883 | 0.1 |
On this clean authored HTML the stdlib `<p>`/`<h1>` extractor edges trafilatura
(which strips some short bodies as boilerplate) at ~220× the speed. trafilatura
still owns messy real-world pages (it won T2) — kept as the escalation extractor.

## Index race — HARDENED into 3 query tiers  (results-index-run3.json)
All 4 engines installed & raced. Query set redesigned so a keyword engine and a
vector engine can NO LONGER tie: 9 queries across **lexical** (words on the page),
**semantic** (no lexical overlap — meaning only), **typo** (misspelled), and
**precision** (a distractor page shares the keywords).
| engine | recall | lex | **sem** | **typo** | prec | build_ms | q_ms |
|---|---|---|---|---|---|---|---|
| 🏆 qdrant (vector) | **1.000** | 1.00 | **1.00** | **1.00** | 1.00 | 729 | 165 |
| meilisearch | 0.667 | 1.00 | 0.00 | **1.00** | 1.00 | 126 | 38 |
| stdlib-bm25 | 0.444 | 1.00 | 0.00 | 0.00 | 1.00 | 0.1 | 0.1 |
| tantivy | 0.444 | 1.00 | 0.00 | 0.00 | 1.00 | 146 | 0.5 |

**Now they earn their differences:** only **qdrant's vectors** handle semantic
(concept) *and* typo queries → the vector engine justifies its ~5,000× build
cost precisely on the hard tiers. **meilisearch's value is typo-tolerance**
(typo 1.0) but it's keyword-based so semantic=0. **bm25/tantivy are fast but
brittle** — exact keywords only, blind to meaning and misspelling. The when-to-
use map: exact-keyword → bm25 (fastest); typo-heavy user input → meilisearch;
semantic/concept → qdrant. (p@k caps at 0.333: one answer per query at k=3.)

## Pipeline scorecard (E2E, hard query set)  (pipeline-run3.json)
crawl4ai-crawl → dedup/robots (in-driver) → **qdrant** (the only index that
clears the semantic+typo queries) → report. crawl_f1 **1.0**, js_recall **1.0**,
robots_violations **0**, extract_title_acc 1.0 / body_f1 0.854, search_recall
**0.889** (8/9 on the crawled corpus — one semantic answer ranks just outside
top-3 vs the clean gold), MRR 0.889. All 4 gates pass. 10.6 s, 33 requests.
Deliverable: `crawl-eval/out/site1/{report.json,pages/}`.

## Candidate coverage — the FULL unraced field, now all raced
RACED (all installed): static fetchers (urllib/curl_cffi/scrapling) + impolite
greedy · **4 browser engines** (crawl4ai, selenium, playwright, jsdom) ·
extractors (rule/css-json/trafilatura) · **4 search engines** (stdlib-bm25,
tantivy, meilisearch [container], qdrant [vector+fastembed]). Nothing left
gated. Deps: `.venv` (playwright+chromium, selenium, crawl4ai, tantivy,
qdrant-client+fastembed, curl_cffi, scrapling, trafilatura) + `node_modules/
jsdom` + a `meili-crawleval` docker container on :7700 (torn down post-run —
`docker run -d -p 7700:7700 getmeili/meilisearch:v1.10` to restart).

## Files
Package `crawl-eval/crawl_eval/*.py` (site_spec/build_fixtures/site_server/oracle/
fetchers/crawl/extract/index/race/pipeline/cli + render_jsdom.js + the /catalog.js
DOM injector + /store.js fetch injector); fixtures `crawl-eval/fixtures/site1/`
(authored HTML + gold); latest results `results-crawl-run3.json`,
`results-index-run3.json`, `results-endurance-run1.json`,
`results-extract-run1.json`, `pipeline-run3.json` (run1/run2 = pre-hardening
history); deliverable `crawl-eval/out/site1/`. Handoff: `crawl-eval/HANDOFF.md`.

## Notes / evo frontier
Top optimization surface: a **routing policy** — cheap static fetch by default,
detect a JS-nav gap (empty container + a script that injects links) OR a bot wall
(403/JA3 block), and escalate that URL alone to the right tool: a TLS-impersonating
fetcher for a JA3 wall (proven in the stealth race), a full browser for
fetch-injected JS. Wins every race at once: fetcher endurance + stealth +
browser completeness. Remaining frontier: a **Tier-R+ JS/behavioral challenge**
(Cloudflare-style — needs a browser to solve, so it separates the stealth
FETCHERS from stealth BROWSERS, which JA3 alone doesn't); HTTP/2 (Akamai)
fingerprinting; semantically-paraphrased query variants to widen qdrant's lead.
