"""ip_eval CLI — fixtures | selftest | list | race <stage> | race-all

Usage: python3 -m ip_eval.cli <command> [args]
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def cmd_fixtures(force: bool = False):
    from .fixtures import build_fixtures
    gold = build_fixtures(force=force)
    print(f"fixtures: {len(gold['documents'])} docs, "
          f"{len(gold['adversarial'])} adversarial cases")


def cmd_selftest():
    """Oracle math verified on perfect/empty/noisy sets; driver smoke; no network."""
    from . import oracle
    from .fixtures import build_fixtures, normalize_text

    failures = []

    def check(name, cond):
        print(f"  {'ok' if cond else 'FAIL'} {name}")
        if not cond:
            failures.append(name)

    print("selftest: oracle math")
    perfect = oracle.token_prf("the quick brown fox", "the quick brown fox")
    check("token_prf perfect == 1.0", perfect["f1"] == 1.0)
    empty = oracle.token_prf("", "the quick brown fox")
    check("token_prf empty == 0.0", empty["f1"] == 0.0)
    noisy = oracle.token_prf("quick fox", "the quick brown fox")
    check("token_prf noisy in (0,1)", 0.0 < noisy["f1"] < 1.0)

    split_perfect = oracle.score_split(["Abstract", "Methods"], ["Abstract", "Methods"])
    check("score_split perfect == 1.0", split_perfect["f1"] == 1.0)
    split_half = oracle.score_split(["Abstract"], ["Abstract", "Methods"])
    check("score_split half recall < 1", split_half["recall"] == 0.5)

    concepts = oracle.score_concepts(
        [{"name": "Evidence Graph Transformer", "type": "Architecture"},
         {"name": "Spurious Thing", "type": "Concept"}],
        [{"name": "Evidence Graph Transformer", "type": "Architecture"},
         {"name": "Local Evidence Retriever", "type": "System Component"}])
    check("score_concepts p/r sane", concepts["precision"] == 0.5 and concepts["recall"] == 0.5)
    check("score_concepts type_accuracy == 1.0", concepts["type_accuracy"] == 1.0)

    print("selftest: fixtures + gold consistency")
    gold = build_fixtures()
    from .fixtures import FIXTURES_DIR
    for key, doc in gold["documents"].items():
        for fmt, spec in doc["formats"].items():
            check(f"{key}.{fmt} exists", (FIXTURES_DIR / spec["file"]).exists())
        check(f"{key} canonical is normalized",
              doc["formats"]["md"]["canonical_text"]
              == normalize_text(doc["formats"]["md"]["canonical_text"]))
    alpha = gold["documents"]["alpha"]
    check("alpha has 7 sections + refs", len(alpha["sections"]) == 7 and len(alpha["references"]) == 4)
    check("gold concepts carry types", all(c["type"] for c in alpha["concepts"]))

    print("selftest: incumbent driver smoke")
    from .candidates import InformationProcesser
    ip = InformationProcesser()
    ok, reason = ip.available()
    check(f"ip-incumbent available ({reason or 'yes'})", ok)
    if ok:
        md_path = FIXTURES_DIR / alpha["formats"]["md"]["file"]
        out = ip.extract(md_path, md_path.name, alpha["formats"]["md"]["mime"])
        check("ip extract ok", out.get("ok", False))
        scored = oracle.score_extraction(out.get("content", ""), alpha["formats"]["md"]["canonical_text"])
        check(f"ip extract f1 high ({scored['f1']})", scored["f1"] >= 0.9)
        sections = ip.split(alpha["formats"]["md"]["canonical_text"])
        check(f"ip split finds sections ({len(sections)})", len(sections) >= 5)
        docx_bytes = ip.export_docx("# T\n\nBody paragraph.", [{"key": "k1", "author": "A", "year": 2024, "title": "T"}])
        validity = oracle.score_docx(docx_bytes)
        check(f"ip docx valid ({validity})", validity["valid"])

    if failures:
        print(f"selftest FAILED: {failures}")
        raise SystemExit(1)
    print("selftest: all green")


def cmd_list():
    from .candidates import all_candidates
    from .race import STAGES
    print("stages:")
    for name, spec in STAGES.items():
        print(f"  {name:15s} {spec['mode']}")
    print("candidates:")
    for cand in all_candidates():
        print(f"  {cand.name:20s} stages={sorted(cand.stages)}")


def cmd_race(stage: str):
    from .race import race
    outcome = race(stage)
    result = outcome["result"]
    print(f"race {stage} -> {outcome['path'].name}")
    for entry in result["leaderboard"]:
        print(f"  {entry['candidate']:20s} gate={entry['gate']:4s} score={entry['score']}"
              f" det={entry.get('deterministic')} fails={entry['fails']}"
              + (f" err={entry['error'][:80]}" if entry["error"] else ""))
    for unavail in result["candidates_unavailable"]:
        print(f"  (unavailable) {unavail['candidate']}: {unavail['reason'][:100]}")


def cmd_deps_prune():
    """Remove every candidate venv (they are re-provisionable on demand)."""
    venvs = PACKAGE_ROOT / ".venv-candidates"
    if venvs.exists():
        size = sum(f.stat().st_size for f in venvs.rglob("*") if f.is_file())
        shutil.rmtree(venvs)
        print(f"pruned .venv-candidates ({size / 1e6:.0f} MB reclaimed)")
    else:
        print("nothing to prune")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, rest = args[0], args[1:]
    if cmd == "fixtures":
        cmd_fixtures(force="--force" in rest)
    elif cmd == "selftest":
        cmd_selftest()
    elif cmd == "list":
        cmd_list()
    elif cmd == "race":
        if not rest:
            raise SystemExit("race requires a stage name")
        cmd_race(rest[0])
    elif cmd == "race-all":
        from .race import STAGES
        for stage in STAGES:
            cmd_race(stage)
    elif cmd == "pipeline":
        from .pipeline import run_pipeline
        outcome = run_pipeline()
        print(f"pipeline -> {outcome['path'].name}")
        print(json.dumps(outcome["result"]["score"], indent=2))
    elif cmd == "deps-prune":
        cmd_deps_prune()
    else:
        raise SystemExit(f"unknown command {cmd!r}; see --help")


if __name__ == "__main__":
    main()
