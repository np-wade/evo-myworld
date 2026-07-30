"""Grader-side fixture author — builds fixtures/set1/: v1/ + v2/ page pairs and
manifest.json (the answer key). The app never reads this module's change table;
it only sees the HTML files. Deterministic (no randomness, no timestamps taken
from the clock, no network) so the whole benchmark is offline-rerunnable.

12 synthetic-but-realistic pages. 9 carry REAL injected changes (price edit,
item added, item removed, paragraph reworded, section deleted, headline edit),
3 are CHURN-ONLY (nothing real changed — the pages every naive watcher false
alarms on). Every page also carries churn traps: rotating timestamps, build/
session tokens, view counters, reordered-but-identical lists, ad-slot rotation,
cache-buster query strings, hidden CSRF tokens.
"""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"
SET = "set1"

# volatile value pairs (v1, v2)
TS = ("2026-07-25 04:12 UTC", "2026-07-26 09:47 UTC")
TS2 = ("2026-07-25 03:58 UTC", "2026-07-26 09:41 UTC")
TOKEN = ("9f3ac1d2e07b", "b81de44a9c02")
CSRF = ("a77c01f4d2b8e655", "0d94b3a1c8f7e219")
AD = ("Sponsored: CloudBox — 30-day free trial, no card needed.",
      "Sponsored: DevKit Pro — ship dashboards twice as fast.")
CACHE = ("1043", "1044")


def _head(title: str, css_v: str = "") -> str:
    q = f"?v={css_v}" if css_v else ""
    return (f"<!doctype html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
            f"<title>{title}</title>\n"
            f"<link rel=\"stylesheet\" href=\"/static/site.css{q}\">\n"
            f"</head>\n<body>\n"
            f"<nav id=\"site-nav\"><a href=\"/\">Home</a> "
            f"<a href=\"/pricing\">Pricing</a> <a href=\"/blog\">Blog</a> "
            f"<a href=\"/docs\">Docs</a></nav>\n")


def _foot(*extra: str) -> str:
    inner = "\n".join(extra)
    return (f"<footer id=\"site-footer\">\n{inner}\n"
            f"<p id=\"copyright\">&copy; 2026 Acme Data Systems</p>\n"
            f"</footer>\n</body>\n</html>\n")


def pricing(v: int) -> str:
    price = ("$29/mo", "$35/mo")[v]
    return _head("Acme — Pricing") + f"""<main id="content">
<h1>Acme Pipeline — Pricing</h1>
<p id="intro">Simple plans that scale with your ingestion volume.</p>
<ul id="plans">
<li id="price-free">Free — $0/mo — 1 project, community support</li>
<li id="price-pro">Pro — {price} — 10 projects, email support, 90-day history</li>
<li id="price-team">Team — $99/mo — unlimited projects, SSO, priority support</li>
</ul>
<p id="fine-print">All prices in USD. Cancel any time.</p>
</main>
""" + _foot(f'<p id="page-updated">Last updated: {TS[v]}</p>',
            f'<p id="build-info">build {TOKEN[v]}</p>')


def blog(v: int) -> str:
    new_post = ("" if v == 0 else
                '<li id="post-eventbus"><a href="/blog/event-bus">Designing an '
                'event bus that survives restarts</a> — 12 views</li>\n')
    views1 = ("1,204", "1,271")[v]
    views2 = ("3,882", "3,905")[v]
    tags = (("kubernetes", "observability", "python", "sre"),
            ("python", "sre", "kubernetes", "observability"))[v]
    tag_lis = "\n".join(f"<li>{t}</li>" for t in tags)
    return _head("Acme — Engineering Blog") + f"""<main id="content">
<h1>Engineering Blog</h1>
<ul id="post-list">
{new_post}<li id="post-elastic"><a href="/blog/search-bill">Cutting our search bill by 70%</a> — <span id="views-elastic">{views1} views</span></li>
<li id="post-oncall"><a href="/blog/on-call">On-call without burnout</a> — <span id="views-oncall">{views2} views</span></li>
<li id="post-postmortem"><a href="/blog/postmortems">Postmortem culture at Acme</a> — 954 views</li>
</ul>
<h2>Tags</h2>
<ul id="tag-list">
{tag_lis}
</ul>
</main>
""" + _foot()


def docs(v: int) -> str:
    note = ("Acme Pipeline requires Python 3.10 or newer and a running Redis "
            "instance for queue state.",
            "You need Python 3.10+ and a reachable Redis server; queue state "
            "lives in Redis.")[v]
    return _head("Acme — Docs / Installation", css_v=CACHE[v]) + f"""<main id="content">
<h1>Acme Pipeline Docs — Installation</h1>
<section id="install">
<h2>Install</h2>
<p id="install-cmd">pip install acme-pipeline</p>
<p id="install-note">{note}</p>
</section>
<section id="quickstart">
<h2>Quickstart</h2>
<p id="qs-body">Run acme init, point it at your source bucket, then acme run to start the pipeline.</p>
</section>
</main>
""" + _foot(f'<p id="docs-updated">Last updated: {TS[v]}</p>')


def products(v: int) -> str:
    mini = ("<li id=\"prod-widget-mini\">Widget Mini — $9.99 — in stock</li>\n"
            if v == 0 else "")
    maxi = ("" if v == 0 else
            "<li id=\"prod-widget-max\">Widget Max — $79.99 — preorder</li>\n")
    return _head("Acme — Hardware Shop") + f"""<main id="content">
<h1>Hardware Shop</h1>
<div id="ad-1" class="ad-slot">{AD[v]}</div>
<ul id="product-grid">
<li id="prod-widget-a">Widget A — $19.99 — in stock</li>
{mini}<li id="prod-widget-pro">Widget Pro — $49.99 — low stock</li>
{maxi}</ul>
</main>
""" + _foot()


def changelog(v: int) -> str:
    new = ("" if v == 0 else
           '<li id="cl-2-1-0">2.1.0 — Adds incremental snapshots and a '
           '--dry-run flag.</li>\n')
    return _head("Acme — Changelog") + f"""<main id="content">
<h1>Changelog</h1>
<ul id="release-list">
{new}<li id="cl-2-0-3">2.0.3 — Fixes a race in the scheduler shutdown path.</li>
<li id="cl-2-0-2">2.0.2 — Faster manifest parsing on large repos.</li>
</ul>
</main>
""" + _foot(f'<p id="build-info">build {TOKEN[v]}</p>')


def team(v: int) -> str:
    rmartin = ("<li id=\"member-rmartin\">R. Martin — Infrastructure</li>\n"
               if v == 0 else "")
    socials = (("GitHub", "Mastodon", "LinkedIn"),
               ("LinkedIn", "GitHub", "Mastodon"))[v]
    soc_lis = "\n".join(f"<li>{s}</li>" for s in socials)
    return _head("Acme — Team") + f"""<main id="content">
<h1>The Team</h1>
<ul id="member-list">
<li id="member-akim">A. Kim — Founder</li>
<li id="member-jortiz">J. Ortiz — Data Engineering</li>
{rmartin}<li id="member-lchen">L. Chen — Product</li>
</ul>
<h2>Elsewhere</h2>
<ul id="social-list">
{soc_lis}
</ul>
</main>
""" + _foot()


def faq(v: int) -> str:
    ans = ("Refunds are available within 14 days of purchase; contact support "
           "with your order number.",
           "We offer a 30-day money-back guarantee — email support with your "
           "order number to start one.")[v]
    return _head("Acme — FAQ") + f"""<main id="content">
<h1>Frequently Asked Questions</h1>
<section id="faq-refunds">
<h2 id="faq-refunds-q">Can I get a refund?</h2>
<p id="faq-refunds-a">{ans}</p>
</section>
<section id="faq-export">
<h2 id="faq-export-q">Can I export my data?</h2>
<p id="faq-export-a">Yes — full JSON export is available from the settings page at any time.</p>
</section>
</main>
""" + _foot(f'<p id="faq-updated">Last updated: {TS2[v]}</p>')


def status(v: int) -> str:
    secs = ("12", "3")[v]
    past = ("""<section id="past-incidents">
<h2>Past incidents</h2>
<p id="incident-0714">2026-07-14 — Elevated queue latency in eu-west for 41 minutes; resolved by scaling workers.</p>
</section>
""" if v == 0 else "")
    return _head("Acme — System Status") + f"""<main id="content">
<h1>System Status</h1>
<p id="status-line">All systems operational.</p>
<p id="last-check">Checked {secs} seconds ago.</p>
{past}</main>
""" + _foot(f'<p id="build-info">build {TOKEN[v]}</p>')


def news(v: int) -> str:
    headline = ("Acme raises Series B to expand data tooling",
                "Acme closes $40M Series B, doubles down on data tooling")[v]
    return _head("Acme — News") + f"""<main id="content">
<h1>Acme News</h1>
<div id="ad-2" class="ad-slot">{AD[v]}</div>
<article id="news-lead">
<h2 id="news-lead-h">{headline}</h2>
<p id="news-lead-p">The round was led by Meridian Capital with participation from existing investors.</p>
</article>
<article id="news-2">
<h2 id="news-2-h">Acme Pipeline 2.0 ships</h2>
<p id="news-2-p">The 2.0 release brings incremental processing to every plan.</p>
</article>
</main>
""" + _foot(f'<p id="news-updated">Last updated: {TS[v]}</p>')


def jobs(v: int) -> str:
    perks = (("Remote-first", "Learning budget", "Hardware of your choice"),
             ("Hardware of your choice", "Remote-first", "Learning budget"))[v]
    perk_lis = "\n".join(f"<li>{p}</li>" for p in perks)
    return _head("Acme — Careers") + f"""<main id="content">
<h1>Careers</h1>
<ul id="job-list">
<li id="job-be">Senior Backend Engineer — Remote</li>
<li id="job-sre">Site Reliability Engineer — Berlin</li>
</ul>
<h2>Perks</h2>
<ul id="perks-list">
{perk_lis}
</ul>
</main>
""" + _foot(f'<p id="jobs-updated">Last updated: {TS2[v]}</p>',
            f'<p id="build-info">build {TOKEN[v]}</p>')


def terms(v: int) -> str:
    return _head("Acme — Terms of Service", css_v=CACHE[v]) + """<main id="content">
<h1>Terms of Service</h1>
<p id="tos-1">Use of the Acme service constitutes acceptance of these terms.</p>
<p id="tos-2">We may update these terms; material changes will be announced 30 days in advance.</p>
</main>
""" + _foot(f'<p id="tos-generated">Generated at {TS[v]}</p>')


def landing(v: int) -> str:
    count = ("12,408", "12,566")[v]
    return _head("Acme Pipeline") + f"""<main id="content">
<h1>Acme Pipeline</h1>
<p id="tagline">Move data without babysitting it.</p>
<div id="ad-3" class="ad-slot">{AD[v]}</div>
<p id="signup-count">Join {count} makers already shipping with Acme.</p>
<form id="signup-form" action="/signup" method="post">
<input type="hidden" name="csrf" value="{CSRF[v]}">
<input type="email" name="email" placeholder="you@work.com">
<button>Get started</button>
</form>
</main>
""" + _foot()


PAGES = [
    ("pricing", pricing), ("blog", blog), ("docs", docs),
    ("products", products), ("changelog", changelog), ("team", team),
    ("faq", faq), ("status", status), ("news", news),
    ("jobs", jobs), ("terms", terms), ("landing", landing),
]

# The answer key. kind=real -> must be detected; kind=churn -> must be IGNORED
# (reporting one as a real change is a false alarm).
CHANGES = [
    # --- real injected changes (10) ---
    dict(change_id="pricing-r1", page="pricing", kind="real", type="price-edit",
         element_id="price-pro", v1_text="$29/mo", v2_text="$35/mo",
         desc="Pro plan price raised $29/mo -> $35/mo"),
    dict(change_id="blog-r1", page="blog", kind="real", type="item-added",
         element_id="post-eventbus", v1_text="",
         v2_text="Designing an event bus that survives restarts",
         desc="new blog post added at top of index"),
    dict(change_id="docs-r1", page="docs", kind="real", type="reworded",
         element_id="install-note",
         v1_text="requires Python 3.10 or newer",
         v2_text="queue state lives in Redis",
         desc="install note paragraph reworded"),
    dict(change_id="products-r1", page="products", kind="real",
         type="item-removed", element_id="prod-widget-mini",
         v1_text="Widget Mini — $9.99", v2_text="",
         desc="Widget Mini removed from the grid"),
    dict(change_id="products-r2", page="products", kind="real",
         type="item-added", element_id="prod-widget-max",
         v1_text="", v2_text="Widget Max — $79.99",
         desc="Widget Max added to the grid"),
    dict(change_id="changelog-r1", page="changelog", kind="real",
         type="item-added", element_id="cl-2-1-0",
         v1_text="", v2_text="incremental snapshots",
         desc="2.1.0 release entry added"),
    dict(change_id="team-r1", page="team", kind="real", type="item-removed",
         element_id="member-rmartin",
         v1_text="R. Martin — Infrastructure", v2_text="",
         desc="team member removed"),
    dict(change_id="faq-r1", page="faq", kind="real", type="reworded",
         element_id="faq-refunds-a",
         v1_text="within 14 days of purchase",
         v2_text="30-day money-back guarantee",
         desc="refund answer reworded (policy change)"),
    dict(change_id="status-r1", page="status", kind="real",
         type="section-deleted", element_id="past-incidents",
         v1_text="Elevated queue latency in eu-west", v2_text="",
         alt_texts=["Past incidents"],
         desc="past-incidents section deleted"),
    dict(change_id="news-r1", page="news", kind="real", type="modified",
         element_id="news-lead-h",
         v1_text="raises Series B to expand",
         v2_text="closes $40M Series B",
         desc="lead headline edited"),
    # --- churn traps (23) — NOT real changes; flagging one = false alarm ---
    dict(change_id="pricing-c1", page="pricing", kind="churn", type="timestamp",
         element_id="page-updated", v1_text=TS[0], v2_text=TS[1],
         desc="footer last-updated timestamp rotated"),
    dict(change_id="pricing-c2", page="pricing", kind="churn", type="token",
         element_id="build-info", v1_text=TOKEN[0], v2_text=TOKEN[1],
         desc="build hash rotated"),
    dict(change_id="blog-c1", page="blog", kind="churn", type="counter",
         element_id="views-elastic", v1_text="1,204 views",
         v2_text="1,271 views", desc="view counter ticked"),
    dict(change_id="blog-c2", page="blog", kind="churn", type="counter",
         element_id="views-oncall", v1_text="3,882 views",
         v2_text="3,905 views", desc="view counter ticked"),
    dict(change_id="blog-c3", page="blog", kind="churn", type="reorder",
         element_id="tag-list", v1_text="kubernetes", v2_text="kubernetes",
         desc="tag list reordered, identical items"),
    dict(change_id="docs-c1", page="docs", kind="churn", type="timestamp",
         element_id="docs-updated", v1_text=TS[0], v2_text=TS[1],
         desc="last-updated timestamp rotated"),
    dict(change_id="docs-c2", page="docs", kind="churn", type="cache-buster",
         element_id="", v1_text=f"?v={CACHE[0]}", v2_text=f"?v={CACHE[1]}",
         desc="stylesheet cache-buster query string bumped"),
    dict(change_id="products-c1", page="products", kind="churn", type="ad",
         element_id="ad-1", v1_text=AD[0], v2_text=AD[1],
         desc="ad slot rotated"),
    dict(change_id="changelog-c1", page="changelog", kind="churn", type="token",
         element_id="build-info", v1_text=TOKEN[0], v2_text=TOKEN[1],
         desc="build hash rotated"),
    dict(change_id="team-c1", page="team", kind="churn", type="reorder",
         element_id="social-list", v1_text="Mastodon", v2_text="Mastodon",
         desc="social links reordered, identical items"),
    dict(change_id="faq-c1", page="faq", kind="churn", type="timestamp",
         element_id="faq-updated", v1_text=TS2[0], v2_text=TS2[1],
         desc="last-updated timestamp rotated"),
    dict(change_id="status-c1", page="status", kind="churn", type="counter",
         element_id="last-check", v1_text="Checked 12 seconds ago",
         v2_text="Checked 3 seconds ago", desc="freshness counter ticked"),
    dict(change_id="status-c2", page="status", kind="churn", type="token",
         element_id="build-info", v1_text=TOKEN[0], v2_text=TOKEN[1],
         desc="build hash rotated"),
    dict(change_id="news-c1", page="news", kind="churn", type="ad",
         element_id="ad-2", v1_text=AD[0], v2_text=AD[1],
         desc="ad slot rotated"),
    dict(change_id="news-c2", page="news", kind="churn", type="timestamp",
         element_id="news-updated", v1_text=TS[0], v2_text=TS[1],
         desc="last-updated timestamp rotated"),
    dict(change_id="jobs-c1", page="jobs", kind="churn", type="reorder",
         element_id="perks-list", v1_text="Learning budget",
         v2_text="Learning budget", desc="perks reordered, identical items"),
    dict(change_id="jobs-c2", page="jobs", kind="churn", type="timestamp",
         element_id="jobs-updated", v1_text=TS2[0], v2_text=TS2[1],
         desc="last-updated timestamp rotated"),
    dict(change_id="jobs-c3", page="jobs", kind="churn", type="token",
         element_id="build-info", v1_text=TOKEN[0], v2_text=TOKEN[1],
         desc="build hash rotated"),
    dict(change_id="terms-c1", page="terms", kind="churn", type="timestamp",
         element_id="tos-generated", v1_text=TS[0], v2_text=TS[1],
         desc="generated-at timestamp rotated"),
    dict(change_id="terms-c2", page="terms", kind="churn", type="cache-buster",
         element_id="", v1_text=f"?v={CACHE[0]}", v2_text=f"?v={CACHE[1]}",
         desc="stylesheet cache-buster query string bumped"),
    dict(change_id="landing-c1", page="landing", kind="churn", type="ad",
         element_id="ad-3", v1_text=AD[0], v2_text=AD[1],
         desc="ad slot rotated"),
    dict(change_id="landing-c2", page="landing", kind="churn", type="counter",
         element_id="signup-count", v1_text="Join 12,408 makers",
         v2_text="Join 12,566 makers", desc="signup counter ticked"),
    dict(change_id="landing-c3", page="landing", kind="churn",
         type="session-token", element_id="", v1_text=CSRF[0], v2_text=CSRF[1],
         desc="hidden CSRF token rotated"),
]


def generate(force: bool = False) -> Path:
    root = FIXTURES / SET
    manifest = root / "manifest.json"
    if manifest.exists() and not force:
        return root
    for ver in ("v1", "v2"):
        (root / ver).mkdir(parents=True, exist_ok=True)
    real_pages = {c["page"] for c in CHANGES if c["kind"] == "real"}
    pages_meta = []
    for name, build in PAGES:
        (root / "v1" / f"{name}.html").write_text(build(0))
        (root / "v2" / f"{name}.html").write_text(build(1))
        pages_meta.append({"page": name, "file": f"{name}.html",
                           "has_real": name in real_pages})
    manifest.write_text(json.dumps(
        {"set": SET, "pages": pages_meta, "changes": CHANGES}, indent=2))
    return root
