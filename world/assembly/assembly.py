#!/usr/bin/env python3
"""assembly.py — the assembly line reborn on evo primitives (Track A core port).

Stdlib-only CLI. Three commands:

  plan   "<one-line product idea>"   -> plan.json on stdout (or -o file)
  brief  plan.json [-o dir]          -> per-stage subagent briefs (evo 4-field style)
  to-evo plan.json                   -> /evo:discover seed prompt + gate registration

Port mapping (PORT-PLAN.md Track A):
  Boss idea intake        -> `plan "<idea>"` (the discover seed's raw material)
  Planner strict JSON     -> plan.json, modeled on assembly-office's planner-input
                             contract: plannerCliContract() in
                             projects/assembly-office/lib/architecture.mjs:119-143
                             (required_output.fields = summary, assumptions,
                             code_components, ai_touchpoints, steps, risks,
                             acceptance_criteria, handoffs) and the deterministic
                             draft in lib/station-roles.mjs:307-356.
  Assigner scoped jobs    -> stages[] nodes carrying the assignment-node contract
                             fields (id, job, depends_on, owned_paths,
                             expected_artifacts, validation_profile) from
                             lib/station-roles.mjs:393-453. owned_paths are NARROW
                             on purpose (HOW-ASSEMBLY-OFFICE-BUILDS-APPS.md:108:
                             "Broad ownedPaths [.] is valid but weak").
  Stations                -> experiment worktrees; each stage = a subagent brief in
                             evo's 4-field style (evo-hq plugins/evo/skills/
                             subagent/SKILL.md:57-64: Objective, Parent node,
                             Boundaries/anti-patterns, Pointer traces + budget).
  Oversight/test profiles -> gates from world/hermes/gates/ (correctness, budget,
                             regression, held_out) + an allowlisted test profile
                             ported from assembly-office lib/test-runner.mjs:8-49.

The new capability (the whole point, PORT-PLAN.md Track A): the "variants" stage
is explicitly a RACE — sibling experiments under one parent, same benchmark,
same gates, losers culled. The factory stops being one-shot.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

GATES_DIR = "world/hermes/gates"

# Allowlisted test profiles — port of TEST_PROFILES + inferTestProfile,
# assembly-office lib/test-runner.mjs:8-49. At plan time no repo exists yet
# (assembly-office infers from lockfiles post-integration), so we infer from
# idea keywords / --lang and record the choice for the experimenter stage.
TEST_PROFILES = ("python-pytest", "node-npm", "rust-cargo", "go-test")

_LANG_KEYWORDS = (
    ("rust-cargo", ("rust", "cargo")),
    ("go-test", ("golang", " go ")),
    ("node-npm", ("node", "typescript", "javascript", " npm", " js ")),
)


def infer_profile(idea: str, lang: str | None = None) -> str:
    if lang:
        aliases = {"python": "python-pytest", "node": "node-npm",
                   "rust": "rust-cargo", "go": "go-test"}
        profile = aliases.get(lang, lang)
        if profile not in TEST_PROFILES:
            raise SystemExit(f"unsupported test profile: {lang!r} "
                             f"(allowlist: {', '.join(TEST_PROFILES)})")
        return profile
    padded = f" {idea.lower()} "
    for profile, needles in _LANG_KEYWORDS:
        if any(n in padded for n in needles):
            return profile
    return "python-pytest"  # lab default: stdlib python, runs on this box


def slugify(idea: str) -> str:
    words = re.findall(r"[a-z0-9]+", idea.lower())
    stop = {"a", "an", "the", "for", "of", "to", "and", "that", "with"}
    kept = [w for w in words if w not in stop][:4]
    return "-".join(kept) or "product"


def _entry_path(slug: str, profile: str) -> str:
    mod = slug.replace("-", "_")
    ext = {"python-pytest": "py", "node-npm": "mjs",
           "rust-cargo": "rs", "go-test": "go"}[profile]
    return f"src/{mod}.{ext}"


def _gate(name: str, phase: str, command: str) -> dict:
    return {"name": name, "phase": phase, "command": command}


def _stage_gates(stage_id: str, has_parent: bool, is_race: bool,
                 entry: str) -> list[dict]:
    """Choose gates from world/hermes/gates/ per stage role.

    Run order guaranteed by evo's phase split (world/hermes/gates/README.md
    §Wiring): regression (pre) -> benchmark -> correctness+budget+held_out
    (post) -> keep decision.
    """
    solver = f"python3 {{target}}/{entry}"
    gates = []
    if has_parent:
        gates.append(_gate(
            "regression", "pre",
            f"python3 {GATES_DIR}/regression.py"
            f" --parent-score .evo/parent_proxy.json"
            f" --current-score {{worktree}}/proxy_score.json"
            f" --field score --mode percent --tolerance 0.0"))
    gates.append(_gate(
        "correctness", "post",
        f"python3 {GATES_DIR}/correctness.py"
        f" --golden golden/{stage_id}.jsonl"
        f" --solver '{solver}'"))
    if is_race:
        gates.append(_gate(
            "budget", "post",
            f"python3 {GATES_DIR}/budget.py --stage {stage_id}"
            f" --budget-file {{worktree}}/.evo/budget.json"
            f" --ceilings budgets.yaml"))
        gates.append(_gate(
            "held_out", "post",
            f"python3 {GATES_DIR}/held_out.py"
            f" --held-out golden/{stage_id}.held_out.jsonl"
            f" --solver '{solver}' --threshold 0.7"))
    return gates


def make_plan(idea: str, lang: str | None = None) -> dict:
    idea = " ".join(str(idea).split())
    if not idea:
        raise SystemExit("empty idea — give me one line, like the Boss desk does")
    slug = slugify(idea)
    profile = infer_profile(idea, lang)
    entry = _entry_path(slug, profile)

    # Stages: the assembly line folded onto evo's experiment tree.
    # scaffold (work-*) -> harness (experimenter prep) -> variants (THE RACE,
    # the capability the port adds) -> review (review station).
    stage_specs = [
        ("scaffold", False, False,
         f"Build the smallest working {slug}: entry point {entry} implementing"
         f" the core behavior of: {idea}. Input on argv/stdin, result on"
         f" stdout. Done when golden/scaffold.jsonl cases pass.",
         ["src/"], [entry]),
        ("harness", True, False,
         "Build the proving ground: golden cases (golden/<stage>.jsonl, one"
         " {id,input,expected} per line), a disjoint held-out slice, and"
         " bench.py printing 'seconds: X' (metric min). Size CALLS_PER_REP so"
         " best-case runtime is well above the rounding unit (FIELD-NOTES"
         " 2026-07-19: score granularity).",
         ["golden/", "bench.py", "budgets.yaml"],
         ["golden/harness.jsonl", "golden/variants.held_out.jsonl", "bench.py"]),
        ("variants", True, True,
         "THE RACE. Propose >=2 candidate implementations of the core"
         " operation (different algorithm/idiom/library), one sibling"
         " experiment each under this stage's node, same benchmark, same"
         " gates. Losers get discarded, winner is committed. Do not merge"
         " candidates.",
         ["src/"], [entry]),
        ("review", True, False,
         "Harden the winner: edge cases into golden/review.jsonl, docstrings,"
         f" and a clean CLI surface. No behavior change to committed"
         f" winners without a gate proving it.",
         ["src/", "golden/review.jsonl", "README.md"], ["README.md"]),
    ]

    stages = []
    prev_id = None
    for stage_id, has_parent, is_race, job, owned, artifacts in stage_specs:
        stages.append({
            "id": stage_id,
            "job": job,
            "depends_on": [prev_id] if prev_id else [],
            "owned_paths": owned,
            "expected_artifacts": artifacts,
            "validation_profile": profile,
            "race": is_race,
            "gates": _stage_gates(stage_id, has_parent, is_race, entry),
        })
        prev_id = stage_id

    return {
        "schema_version": 1,
        "run_id": f"asm-{slug}",
        "idea": idea,
        "summary": idea[:500],
        "assumptions": [
            "Product is buildable offline on a 12GB WSL2 box, sequentially.",
            f"Test profile {profile} covers the integrated result.",
        ],
        "test_profile": profile,
        "metric": {"direction": "min",
                   "meaning": "seconds per benchmark rep (bench.py prints 'seconds: X')"},
        "acceptance_criteria": [
            "All stage expected_artifacts exist after their stage commits.",
            "Every committed node passed its effective gates (inherited included).",
            "The variants race produced >=2 scored siblings; only the winner survives.",
        ],
        "risks": [
            "Benchmark rounding too coarse to rank micro-variants.",
            "Golden cases too narrow -> held_out gate is the backstop.",
        ],
        "handoffs": [
            {"from": s["id"],
             "to": stages[i + 1]["id"] if i + 1 < len(stages) else "ship"}
            for i, s in enumerate(stages)
        ],
        "stages": stages,
    }


def render_brief(plan: dict, stage: dict, budget: int = 3) -> str:
    """One stage -> one subagent brief, evo 4-field style (subagent/SKILL.md:57-64)."""
    parent = (f"the committed node of stage '{stage['depends_on'][0]}'"
              if stage["depends_on"] else
              "the baseline root (exp_0000) of this run")
    traces = ("none — this is the baseline stage; study .evo/project.md instead"
              if not stage["depends_on"] else
              f"failing-task traces of stage '{stage['depends_on'][0]}''s committed "
              f"node (`evo traces <exp_id> <task_id>`)")
    boundaries = [
        f"Write ONLY within owned paths: {', '.join(stage['owned_paths'])} "
        f"(port of ownedPaths write-allowlist, enforced at integration).",
        f"Expected artifacts must exist when you finish: "
        f"{', '.join(stage['expected_artifacts'])}.",
        "Do NOT modify benchmark, gate, or framework code (subagent protocol rule).",
        f"Test profile is {stage['validation_profile']} — do not swap harnesses mid-run.",
    ]
    if stage.get("race"):
        boundaries.append(
            "Anti-pattern: merging candidate implementations into one — each "
            "candidate is its own sibling experiment; the gate+score decides.")
    gate_lines = [f"  - {g['name']} ({g['phase']}): `{g['command']}`"
                  for g in stage["gates"]]
    lines = [
        f"# Brief — stage `{stage['id']}` — run {plan['run_id']}",
        "",
        "Load the `evo:subagent` skill IN FULL before acting.",
        "",
        f"- **Objective**: {stage['job']}",
        f"- **Parent node**: {parent}",
        "- **Boundaries / anti-patterns**:",
        *[f"  - {b}" for b in boundaries],
        f"- **Pointer traces**: {traces}",
        "",
        f"Iteration budget: {budget}",
        "",
        "Gates in effect on this stage's branch (inherit down the tree):",
        *gate_lines,
        "",
    ]
    return "\n".join(lines)


def render_to_evo(plan: dict) -> str:
    """Emit the /evo:discover seed + gate registration for a real run.

    Seeding benchmark+metric in the discover prompt skips all interactive
    questions (FIELD-NOTES.md 2026-07-19, vanilla run log) — good for
    headless dispatch.
    """
    seed = (
        f"/evo:discover Build this product as an experiment tree: {plan['idea']}. "
        f"Stages in order: "
        + " -> ".join(s["id"] for s in plan["stages"]) + ". "
        f"Benchmark: metric {plan['metric']['direction']}, "
        f"{plan['metric']['meaning']}. Test profile: {plan['test_profile']}. "
        f"The variants stage races >=2 sibling implementations under the same "
        f"gates; losers are discarded. Correctness is asserted by gates, not by "
        f"the benchmark."
    )
    out = [
        f"# to-evo — run {plan['run_id']}",
        "",
        "## 1. Discover seed (headless — benchmark+metric seeded, no questions)",
        "",
        f'claude -p "{seed}"',
        "",
        "## 2. Gate registration (after `evo new` gives each stage its root exp id;",
        "##    gates inherit DOWN the tree — register once per stage root,",
        "##    cli-quick-reference.md:258 / cli.py:2685)",
        "",
    ]
    for stage in plan["stages"]:
        exp_var = f"$EXP_{stage['id'].upper()}"
        for g in stage["gates"]:
            out.append(
                f"evo gate add {exp_var} --name {g['name']} "
                f"--command \"{g['command']}\" --phase {g['phase']}")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="assembly.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="one-line idea -> plan.json")
    p_plan.add_argument("idea")
    p_plan.add_argument("--lang", help="force test profile (python|node|rust|go)")
    p_plan.add_argument("-o", "--out", help="write plan.json here instead of stdout")

    p_brief = sub.add_parser("brief", help="plan.json -> per-stage subagent briefs")
    p_brief.add_argument("plan")
    p_brief.add_argument("-o", "--out-dir", help="write briefs/<stage>.md here instead of stdout")
    p_brief.add_argument("--budget", type=int, default=3, help="iteration budget per brief")

    p_evo = sub.add_parser("to-evo", help="plan.json -> discover seed + gate commands")
    p_evo.add_argument("plan")

    args = ap.parse_args(argv)

    if args.cmd == "plan":
        plan = make_plan(args.idea, args.lang)
        text = json.dumps(plan, indent=2)
        if args.out:
            Path(args.out).write_text(text + "\n")
            print(f"wrote {args.out}")
        else:
            print(text)
        return 0

    plan = json.loads(Path(args.plan).read_text())

    if args.cmd == "brief":
        if args.out_dir:
            out_dir = Path(args.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            for stage in plan["stages"]:
                path = out_dir / f"{stage['id']}.md"
                path.write_text(render_brief(plan, stage, args.budget))
                print(f"wrote {path}")
        else:
            for stage in plan["stages"]:
                print(render_brief(plan, stage, args.budget))
                print("---")
        return 0

    if args.cmd == "to-evo":
        print(render_to_evo(plan))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
