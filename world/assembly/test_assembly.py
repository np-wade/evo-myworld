"""Offline pytest for world/assembly/assembly.py.

Run: uv run --no-project --with pytest pytest -q world/assembly/test_assembly.py
"""

import json
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import assembly  # noqa: E402

IDEA = "a CLI stopwatch"


def plan():
    return assembly.make_plan(IDEA)


# --- plan contract (mirrors plannerCliContract required_output.fields,
# --- assembly-office lib/architecture.mjs:131-137, minus AI-touchpoint fields)

def test_plan_required_fields():
    p = plan()
    for field in ("summary", "assumptions", "risks", "acceptance_criteria",
                  "handoffs", "stages", "run_id", "idea", "test_profile",
                  "metric", "schema_version"):
        assert field in p, f"missing {field}"


def test_plan_is_deterministic():
    assert plan() == plan()


def test_stage_nodes_carry_assignment_contract():
    # Port of the assignment-node contract, station-roles.mjs:395-408.
    for s in plan()["stages"]:
        for field in ("id", "job", "depends_on", "owned_paths",
                      "expected_artifacts", "validation_profile", "gates"):
            assert field in s, f"stage {s.get('id')} missing {field}"


def test_owned_paths_are_narrow():
    # HOW-ASSEMBLY-OFFICE-BUILDS-APPS.md:108 — broad ['.'] is valid but weak.
    for s in plan()["stages"]:
        assert s["owned_paths"], s["id"]
        assert "." not in s["owned_paths"], s["id"]


def test_depends_on_chain_is_valid():
    ids = set()
    for s in plan()["stages"]:
        for dep in s["depends_on"]:
            assert dep in ids, f"{s['id']} depends on unknown/later {dep}"
        ids.add(s["id"])


def test_gate_scripts_exist_in_hermes_library():
    for s in plan()["stages"]:
        for g in s["gates"]:
            script = shlex.split(g["command"])[1]
            assert (REPO / script).is_file(), f"missing gate script {script}"


def test_gate_phases():
    for s in plan()["stages"]:
        by_name = {g["name"]: g["phase"] for g in s["gates"]}
        assert by_name["correctness"] == "post"
        if "regression" in by_name:
            assert by_name["regression"] == "pre"
    # Root stage has no parent -> no regression gate; later stages do.
    stages = plan()["stages"]
    assert all(g["name"] != "regression" for g in stages[0]["gates"])
    assert any(g["name"] == "regression" for g in stages[1]["gates"])


def test_race_stage_gets_budget_and_held_out():
    race = [s for s in plan()["stages"] if s.get("race")]
    assert len(race) == 1
    names = {g["name"] for g in race[0]["gates"]}
    assert {"budget", "held_out"} <= names


# --- profile inference (port of inferTestProfile, test-runner.mjs:35-49)

def test_profile_default_and_keywords():
    assert assembly.infer_profile("a CLI stopwatch") == "python-pytest"
    assert assembly.infer_profile("a rust json parser") == "rust-cargo"
    assert assembly.infer_profile("a node web scraper") == "node-npm"


def test_profile_lang_override_and_allowlist():
    assert assembly.infer_profile(IDEA, "rust") == "rust-cargo"
    try:
        assembly.infer_profile(IDEA, "cobol")
        raise AssertionError("allowlist not enforced")
    except SystemExit:
        pass


def test_slugify():
    assert assembly.slugify(IDEA) == "cli-stopwatch"
    assert assembly.slugify("") == "product"


# --- briefs (evo 4-field style, subagent/SKILL.md:57-64)

def test_brief_has_four_fields_and_budget():
    p = plan()
    for s in p["stages"]:
        text = assembly.render_brief(p, s, budget=3)
        for field in ("**Objective**", "**Parent node**",
                      "**Boundaries / anti-patterns**", "**Pointer traces**"):
            assert field in text, f"{s['id']} missing {field}"
        assert "Iteration budget: 3" in text
        for path in s["owned_paths"]:
            assert path in text


def test_baseline_brief_points_at_root():
    p = plan()
    text = assembly.render_brief(p, p["stages"][0])
    assert "baseline root" in text


# --- to-evo emission

def test_to_evo_contains_seed_and_gate_adds():
    p = plan()
    out = assembly.render_to_evo(p)
    assert "/evo:discover" in out
    assert p["idea"] in out
    assert "metric min" in out
    n_gates = sum(len(s["gates"]) for s in p["stages"])
    assert out.count("evo gate add") == n_gates
    assert "--phase pre" in out and "--phase post" in out


def test_to_evo_seed_line_is_shell_safe():
    out = assembly.render_to_evo(plan())
    seed_line = next(l for l in out.splitlines() if l.startswith("claude -p"))
    parts = shlex.split(seed_line)  # raises ValueError on broken quoting
    assert parts[:2] == ["claude", "-p"] and len(parts) == 3


# --- CLI end-to-end (subprocess, still offline)

def test_cli_round_trip(tmp_path):
    plan_file = tmp_path / "plan.json"
    run = subprocess.run(
        [sys.executable, str(HERE / "assembly.py"), "plan", IDEA,
         "-o", str(plan_file)],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    loaded = json.loads(plan_file.read_text())
    assert loaded == plan()
    run = subprocess.run(
        [sys.executable, str(HERE / "assembly.py"), "to-evo", str(plan_file)],
        capture_output=True, text=True)
    assert run.returncode == 0 and "/evo:discover" in run.stdout


def test_cli_empty_idea_fails():
    run = subprocess.run(
        [sys.executable, str(HERE / "assembly.py"), "plan", "   "],
        capture_output=True, text=True)
    assert run.returncode != 0
