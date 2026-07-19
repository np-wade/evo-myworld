#!/usr/bin/env python3
"""evo-graph — Track B phase 1: read-only bridge from the graphify library
into evo. Pure stdlib (sqlite3 + json + argparse).

Commands
--------
  find <query> [--repo R] [--limit N]
      FTS5 search over graphify's index.db (9.2M nodes, 597 repos).
      Ranked symbol hits with repo + source_file + degree.

  slice <repo-id-or-substring> [--topic T]
      Locate a repo's slice directory under data/graphs/<id>/graphify-out/
      slices/ and print slice JSON paths + summaries (topic terms, node/
      edge counts, files, top hubs).

Data root resolution: $GRAPHIFY_DATA, else the lab default
(~/coding/docker-envs/projects/graphify-app/data).

Everything is read-only (sqlite URI mode=ro; slices are only read).
Missing DB / slices fail gracefully with a message and exit code 2 —
never a traceback (pattern borrowed from tencentdb-agent-memory's
"never raises, degrade gracefully" gateway guarantees).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sqlite3
import sys

DEFAULT_DATA_ROOT = os.path.expanduser(
    "~/coding/docker-envs/projects/graphify-app/data"
)

# Query stopwords: content words should drive the search, not question filler.
# Trimmed-down port of _QUERY_STOPWORDS in graphify serve.py (L117-126).
_QUERY_STOPWORDS = frozenset({
    "how", "what", "why", "when", "where", "which", "who",
    "does", "did", "is", "are", "was", "were", "be",
    "can", "could", "should", "would", "will", "may", "might", "must",
    "has", "have", "had", "the", "and", "but", "not", "for", "from",
    "with", "into", "that", "this", "these", "those", "there",
})

# Ranking bonuses, same tier idea as graphify serve.py (_EXACT_MATCH_BONUS /
# _PREFIX_MATCH_BONUS): exact label beats prefix beats plain bm25 order.
_EXACT_BONUS = 1000.0
_PREFIX_BONUS = 100.0


def data_root() -> str:
    return os.environ.get("GRAPHIFY_DATA", DEFAULT_DATA_ROOT)


def _die(msg: str) -> "int":
    print(f"evo-graph: {msg}", file=sys.stderr)
    return 2


def _connect(db_path: str) -> sqlite3.Connection:
    """Read-only connection; raises sqlite3.OperationalError if unreadable."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _query_terms(query: str) -> list[str]:
    """Tokenize a free-text query into content terms.

    Port of graphify serve.py _query_terms() (L128): \\w+ tokens, lowercase,
    drop stopwords and 1-2 char English tokens, fall back to unfiltered
    terms if everything was a stopword.
    """
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    content = [t for t in terms if t not in _QUERY_STOPWORDS]
    return content or terms


def _fts_query(terms: list[str]) -> str:
    """Build a safe FTS5 MATCH string: each token double-quoted (neutralises
    FTS5 operators/punctuation in user input), AND-joined for precision.
    Quoting pattern from tencentdb-agent-memory sqlite.ts buildFtsQuery()
    (L198): tokens are individually quoted, then joined.
    """
    return " AND ".join('"{}"'.format(t.replace('"', '""')) for t in terms)


def cmd_find(args: argparse.Namespace) -> int:
    root = data_root()
    db_path = os.path.join(root, "index.db")
    if not os.path.exists(db_path):
        return _die(f"index.db not found at {db_path} "
                    "(set GRAPHIFY_DATA to the graphify data dir)")

    terms = _query_terms(args.query)
    if not terms:
        return _die("query has no searchable terms")

    limit = max(1, args.limit)
    # Overfetch so post-ranking bonuses can reorder within candidates.
    fetch = limit * 5

    sql = """
        SELECT n.repo_id, n.label, n.norm_label, n.kind, n.source_file,
               n.loc, n.degree, n.community_name, bm25(nodes_fts) AS score
        FROM nodes_fts
        JOIN nodes n ON n.id = nodes_fts.rowid
        WHERE nodes_fts MATCH ?
    """
    params: list = [_fts_query(terms)]
    if args.repo:
        sql += " AND n.repo_id LIKE ?"
        params.append(f"%{args.repo}%")
    sql += " ORDER BY score LIMIT ?"
    params.append(fetch)

    try:
        con = _connect(db_path)
    except sqlite3.OperationalError as e:
        return _die(f"cannot open index.db read-only: {e}")
    try:
        try:
            rows = con.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            return _die(f"FTS query failed: {e}")
        if not rows and len(terms) > 1:
            # AND was too strict — retry with OR (graphify seeds with OR).
            params[0] = params[0].replace(" AND ", " OR ")
            rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    if not rows:
        print(f"no hits for {terms} "
              "(note: FTS covers top ~50k nodes/repo — a miss is not proof "
              "of absence in giant repos)")
        return 0

    joined = " ".join(terms)

    def rank(r: sqlite3.Row) -> float:
        s = r["score"]  # bm25: lower (more negative) = better
        norm = (r["norm_label"] or "").lower()
        if norm == joined or norm == terms[0]:
            s -= _EXACT_BONUS
        elif norm.startswith(terms[0]):
            s -= _PREFIX_BONUS
        return s

    rows = sorted(rows, key=rank)[:limit]
    for r in rows:
        loc = f" {r['loc']}" if r["loc"] else ""
        kind = r["kind"] or "?"
        print(f"{r['repo_id']}  {r['label']}  [{kind}]  "
              f"{r['source_file'] or '?'}{loc}  deg={r['degree']}")
    return 0


def _slice_summary(path: str) -> str:
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return f"{path}\n    (unreadable: {e})"
    hubs = [n.get("label", "?") for n in d.get("nodes", [])[:5]]
    return (f"{path}\n"
            f"    topic_terms={d.get('topic_terms')} "
            f"nodes={d.get('node_count')} edges={d.get('edge_count')}\n"
            f"    files={d.get('files', [])[:8]}\n"
            f"    first nodes: {hubs}")


def cmd_slice(args: argparse.Namespace) -> int:
    root = data_root()
    graphs_dir = os.path.join(root, "graphs")
    if not os.path.isdir(graphs_dir):
        return _die(f"graphs dir not found at {graphs_dir} "
                    "(set GRAPHIFY_DATA to the graphify data dir)")

    needle = args.repo.lower()
    matches = sorted(
        d for d in os.listdir(graphs_dir)
        if needle in d.lower()
        and os.path.isdir(os.path.join(graphs_dir, d))
    )
    if not matches:
        return _die(f"no graph dir matching '{args.repo}' under {graphs_dir}")
    if len(matches) > 1:
        print(f"{len(matches)} repos match '{args.repo}':")
        for m in matches:
            print(f"  {m}")
        print("narrow the substring to pick one.")
        return 1

    repo_dir = os.path.join(graphs_dir, matches[0])
    # slices live at <repo>/graphify-out/slices/ (occasionally <repo>/slices/)
    slices_dir = None
    for cand in ("graphify-out/slices", "slices"):
        p = os.path.join(repo_dir, cand)
        if os.path.isdir(p):
            slices_dir = p
            break
    if slices_dir is None:
        return _die(f"{matches[0]} has no slices/ yet — run "
                    "data/build-run/slice_graph.py on it (GRAPH-FIRST.md)")

    pattern = os.path.join(slices_dir, "*.json")
    slice_files = sorted(glob.glob(pattern))
    if args.topic:
        t = args.topic.lower()
        slice_files = [p for p in slice_files
                       if t in os.path.basename(p).lower()]
        if not slice_files:
            return _die(f"no slice named like '{args.topic}' in {slices_dir} "
                        "(slices are named by topic terms; try a concept "
                        "word, see INDEX.md)")

    print(f"repo: {matches[0]}")
    index_md = os.path.join(slices_dir, "INDEX.md")
    if os.path.exists(index_md):
        print(f"index: {index_md}")
    print(f"{len(slice_files)} slice(s):")
    for p in slice_files:
        if args.topic:
            print(_slice_summary(p))
        else:
            print(f"  {p}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="evo_graph",
        description="Read-only bridge: graphify index.db + slices -> evo.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_find = sub.add_parser("find", help="FTS search over index.db")
    p_find.add_argument("query")
    p_find.add_argument("--repo", help="filter by repo_id substring")
    p_find.add_argument("--limit", type=int, default=10)
    p_find.set_defaults(fn=cmd_find)

    p_slice = sub.add_parser("slice", help="locate + summarize slice JSONs")
    p_slice.add_argument("repo", help="graph-dir substring, e.g. 'graphify'")
    p_slice.add_argument("--topic", help="slice-name substring, e.g. 'fts'")
    p_slice.set_defaults(fn=cmd_slice)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
