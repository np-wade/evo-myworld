"""Tests for the parameter tuner (random sampler; no optuna/subprocess needed)."""

from __future__ import annotations

import json
import sys

import pytest

from evo import tuning


# -- parameter space parsing / validation -----------------------------------


def test_parse_param_space_aliases_and_kinds():
    space = tuning.parse_param_space({
        "temperature": {"type": "float", "min": 0.0, "max": 1.5},
        "n": {"type": "int", "min": 0, "max": 8},
        "strategy": {"type": "categorical", "values": ["a", "b"]},
        "flag": {"type": "bool"},
    })
    by = {p.name: p for p in space}
    assert by["temperature"].kind == "float" and by["temperature"].high == 1.5
    assert by["n"].kind == "int"
    assert by["strategy"].choices == ["a", "b"]
    assert by["flag"].kind == "bool"


@pytest.mark.parametrize("body,msg", [
    ({"type": "float", "min": 1, "max": 1}, "min"),          # low >= high
    ({"type": "float", "min": -1, "max": 1, "scale": "log"}, "positive"),
    ({"type": "categorical"}, "choices"),
    ({"type": "nope", "min": 0, "max": 1}, "unsupported"),
    ({"type": "float", "max": 1}, "required"),               # missing min
])
def test_invalid_specs_raise(body, msg):
    with pytest.raises(tuning.TuningError) as exc:
        tuning.parse_param_space({"p": body})
    assert msg in str(exc.value)


def test_empty_space_raises():
    with pytest.raises(tuning.TuningError):
        tuning.parse_param_space({})


# -- random sampling stays in bounds ----------------------------------------


def test_sample_random_respects_domain():
    import random
    rng = random.Random(0)
    f = tuning.ParameterSpec("x", "float", low=0.0, high=2.0)
    i = tuning.ParameterSpec("n", "int", low=1, high=3)
    c = tuning.ParameterSpec("s", "categorical", choices=["a", "b"])
    for _ in range(50):
        assert 0.0 <= f.sample_random(rng) <= 2.0
        assert i.sample_random(rng) in (1, 2, 3)
        assert c.sample_random(rng) in ("a", "b")


# -- search loop -------------------------------------------------------------


def test_random_search_maximizes(monkeypatch):
    space = tuning.parse_param_space({"x": {"type": "float", "min": -5, "max": 5}})
    # score peaks at x = 2
    result = tuning.run_tuning(
        space, lambda p: -(p["x"] - 2) ** 2,
        metric="max", n_trials=40, sampler="random", seed=1,
    )
    assert result.sampler == "random"
    assert result.best_score is not None and result.best_score <= 0
    assert result.best_params is not None
    assert abs(result.best_params["x"] - 2) < 1.5  # 40 random draws land near the peak
    assert sum(1 for t in result.trials if t.ok) == 40


def test_random_search_minimizes():
    space = tuning.parse_param_space({"x": {"type": "float", "min": 0, "max": 10}})
    result = tuning.run_tuning(space, lambda p: (p["x"] - 1) ** 2,
                              metric="min", n_trials=30, sampler="random", seed=2)
    assert result.best_score >= 0
    assert result.best_params["x"] < 4


def test_failed_trials_are_recorded_not_fatal():
    calls = {"n": 0}

    def _flaky(params):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            raise RuntimeError("boom")
        return float(params["x"])

    space = tuning.parse_param_space({"x": {"type": "float", "min": 0, "max": 1}})
    result = tuning.run_tuning(space, _flaky, metric="max", n_trials=6, sampler="random", seed=3)
    ok = [t for t in result.trials if t.ok]
    bad = [t for t in result.trials if not t.ok]
    assert len(result.trials) == 6 and ok and bad
    # A failed trial never becomes the best.
    assert result.best_params is not None
    assert all(t.score is not None for t in ok)


def test_tpe_falls_back_to_random_without_optuna(monkeypatch):
    # Simulate optuna missing.
    monkeypatch.setitem(sys.modules, "optuna", None)
    space = tuning.parse_param_space({"x": {"type": "int", "min": 0, "max": 3}})
    result = tuning.run_tuning(space, lambda p: p["x"], metric="max", n_trials=5, sampler="tpe", seed=0)
    assert result.sampler == "random"  # fell back


# -- real benchmark evaluator (subprocess) ----------------------------------


def test_benchmark_evaluator_roundtrips_params_and_score(tmp_path):
    # Benchmark reads EVO_PARAMS and emits {"score": ...} the way evo run expects.
    bench = (
        f'{sys.executable} -c '
        '"import os,json;p=json.loads(os.environ[\'EVO_PARAMS\']);'
        'print(json.dumps({\'score\': -(p[\'x\']-3)**2}))"'
    )
    ev = tuning.make_benchmark_evaluator(bench, cwd=tmp_path, timeout=30, params_dir=tmp_path)
    score = ev({"x": 3.0})
    assert score == 0.0
    # params file was written for the benchmark to read too
    assert json.loads((tmp_path / "params.json").read_text())["x"] == 3.0
