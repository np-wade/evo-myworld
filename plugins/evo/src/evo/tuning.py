"""Parameter tuning for Evo (Bayesian / random search over benchmark knobs).

Evo's experiment tree optimizes *code* (an agent edits a target, a benchmark
scores it). This module optimizes *numeric/categorical parameters* of a fixed
target -- temperature, top_p, a LoRA rank, a batch size, a threshold -- by
searching a declared parameter space against the same benchmark + metric.

Each trial samples a point in the space, exposes it to the benchmark via the
``EVO_PARAMS`` (JSON) env var and an ``EVO_PARAMS_FILE`` on disk, runs the
benchmark, and reads the score with :func:`evo.core.parse_score` -- so a tuned
benchmark scores identically to one run under ``evo run``.

Search engine: Optuna's TPE sampler when ``optuna`` is installed; otherwise a
dependency-free random search (seedable). The sampling + parameter-space design
is adapted from comet-ml/opik's ParameterOptimizer (Apache-2.0).
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .core import compare_scores, parse_score, utc_now

# NOTICE: parameter-space + TPE search design adapted from comet-ml/opik
# (Apache License 2.0). https://github.com/comet-ml/opik

#: An evaluator maps a sampled parameter dict to a scalar score. Defaults to
#: running the benchmark; injectable so tests need no subprocess.
Evaluator = Callable[[dict[str, Any]], float]


class TuningError(RuntimeError):
    """Invalid parameter space, missing engine, or an unscorable benchmark."""


_KINDS = {"float", "int", "categorical", "bool"}


@dataclass(frozen=True)
class ParameterSpec:
    """One tunable parameter. ``float``/``int`` need ``low``/``high``;
    ``categorical`` needs ``choices``; ``bool`` samples ``[False, True]``."""

    name: str
    kind: str
    low: Optional[float] = None
    high: Optional[float] = None
    step: Optional[float] = None
    scale: str = "linear"  # "linear" | "log" (float/int only)
    choices: Optional[list[Any]] = None

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise TuningError(f"{self.name}: unsupported type {self.kind!r} (use {sorted(_KINDS)})")
        if self.kind in {"float", "int"}:
            if self.low is None or self.high is None:
                raise TuningError(f"{self.name}: 'min' and 'max' are required for {self.kind}")
            if self.low >= self.high:
                raise TuningError(f"{self.name}: 'min' must be < 'max'")
            if self.scale not in {"linear", "log"}:
                raise TuningError(f"{self.name}: scale must be 'linear' or 'log'")
            if self.scale == "log" and (self.low <= 0 or self.high <= 0):
                raise TuningError(f"{self.name}: log scale requires positive bounds")
            if self.step is not None and self.step <= 0:
                raise TuningError(f"{self.name}: step must be positive")
        elif self.kind == "categorical" and not self.choices:
            raise TuningError(f"{self.name}: categorical requires non-empty 'choices'")

    # -- random-search sampling (no optuna) --------------------------------
    def sample_random(self, rng: random.Random) -> Any:
        if self.kind == "bool":
            return rng.choice([False, True])
        if self.kind == "categorical":
            assert self.choices is not None
            return rng.choice(self.choices)
        assert self.low is not None and self.high is not None
        if self.scale == "log":
            import math
            val = math.exp(rng.uniform(math.log(self.low), math.log(self.high)))
        else:
            val = rng.uniform(float(self.low), float(self.high))
        if self.kind == "int":
            return int(round(val))
        if self.step:
            val = self.low + round((val - self.low) / self.step) * self.step
        return val

    # -- optuna sampling ---------------------------------------------------
    def suggest_optuna(self, trial: Any) -> Any:
        if self.kind == "bool":
            return trial.suggest_categorical(self.name, [False, True])
        if self.kind == "categorical":
            assert self.choices is not None
            return trial.suggest_categorical(self.name, self.choices)
        assert self.low is not None and self.high is not None
        if self.kind == "int":
            return trial.suggest_int(self.name, int(self.low), int(self.high),
                                     step=int(self.step) if self.step else 1,
                                     log=self.scale == "log")
        return trial.suggest_float(self.name, float(self.low), float(self.high),
                                   step=self.step, log=self.scale == "log")


def parse_param_space(spec: dict[str, Any]) -> list[ParameterSpec]:
    """Parse a ``{name: {type, min, max, ...}}`` mapping into ParameterSpecs.

    Aliases: ``type``→kind, ``min``→low, ``max``→high, ``values``/``choices``.
    """
    if not isinstance(spec, dict) or not spec:
        raise TuningError("parameter space must be a non-empty object of {name: {type, ...}}")
    out: list[ParameterSpec] = []
    for name, body in spec.items():
        if not isinstance(body, dict):
            raise TuningError(f"{name}: parameter definition must be an object")
        kind = str(body.get("type") or body.get("kind") or "").strip().lower()
        choices = body.get("choices", body.get("values"))
        out.append(ParameterSpec(
            name=name,
            kind=kind,
            low=body.get("min", body.get("low")),
            high=body.get("max", body.get("high")),
            step=body.get("step"),
            scale=str(body.get("scale", "linear")).lower(),
            choices=list(choices) if choices is not None else None,
        ))
    return out


@dataclass
class Trial:
    number: int
    params: dict[str, Any]
    score: Optional[float]
    ok: bool
    error: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number, "params": self.params, "score": self.score,
            "ok": self.ok, "error": self.error, "duration_ms": self.duration_ms,
        }


@dataclass
class TuningResult:
    metric: str
    sampler: str
    n_trials: int
    best_params: Optional[dict[str, Any]]
    best_score: Optional[float]
    trials: list[Trial] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "evo.tuning-result/v1",
            "metric": self.metric,
            "sampler": self.sampler,
            "n_trials": self.n_trials,
            "completed_trials": sum(1 for t in self.trials if t.ok),
            "best_params": self.best_params,
            "best_score": self.best_score,
            "trials": [t.to_dict() for t in self.trials],
        }


# ---------------------------------------------------------------------------
# Benchmark evaluator
# ---------------------------------------------------------------------------


def make_benchmark_evaluator(
    benchmark: str,
    *,
    cwd: Path,
    timeout: int = 1800,
    params_dir: Optional[Path] = None,
    base_env: Optional[dict[str, str]] = None,
) -> Evaluator:
    """Return an evaluator that runs ``benchmark`` (a shell command) with the
    sampled params exposed via ``EVO_PARAMS`` (JSON) and ``EVO_PARAMS_FILE``,
    and scores stdout with :func:`evo.core.parse_score`."""

    def _evaluate(params: dict[str, Any]) -> float:
        env = dict(base_env if base_env is not None else os.environ)
        env["EVO_PARAMS"] = json.dumps(params)
        pfile: Optional[Path] = None
        if params_dir is not None:
            params_dir.mkdir(parents=True, exist_ok=True)
            pfile = params_dir / "params.json"
            pfile.write_text(json.dumps(params, indent=2), encoding="utf-8")
            env["EVO_PARAMS_FILE"] = str(pfile)
        proc = subprocess.run(
            benchmark, shell=True, cwd=str(cwd), env=env,
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            raise TuningError(f"benchmark exited {proc.returncode}: {(proc.stderr or '')[-300:]}")
        score, _ = parse_score(proc.stdout)
        return score

    return _evaluate


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def _is_better(metric: str, candidate: float, best: Optional[float]) -> bool:
    return compare_scores(metric, candidate, best) if best is not None else True


def run_tuning(
    space: Sequence[ParameterSpec],
    evaluator: Evaluator,
    *,
    metric: str = "max",
    n_trials: int = 20,
    sampler: str = "tpe",
    seed: Optional[int] = None,
    on_trial: Optional[Callable[[Trial], None]] = None,
) -> TuningResult:
    """Search ``space`` with ``evaluator`` for ``n_trials``.

    ``sampler`` is ``tpe`` (Optuna; falls back to ``random`` with a warning if
    optuna is absent) or ``random``. A failed trial is recorded and skipped,
    never fatal. Returns the best params/score plus every trial.
    """
    if metric not in {"max", "min"}:
        raise TuningError("metric must be 'max' or 'min'")
    space = list(space)
    if not space:
        raise TuningError("empty parameter space")

    want_tpe = sampler == "tpe"
    have_optuna = False
    if want_tpe:
        try:
            import optuna  # noqa: F401
            have_optuna = True
        except ImportError:
            print("NOTE: optuna not installed; falling back to random search "
                  "(`pip install optuna` for TPE).")
    used = "tpe" if have_optuna else "random"

    result = TuningResult(metric=metric, sampler=used, n_trials=n_trials,
                          best_params=None, best_score=None)

    def _record(number: int, params: dict[str, Any]) -> float:
        started = time.monotonic()
        try:
            score = float(evaluator(params))
            trial = Trial(number, params, score, ok=True,
                          duration_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:  # noqa: BLE001
            trial = Trial(number, params, None, ok=False, error=str(exc),
                          duration_ms=int((time.monotonic() - started) * 1000))
        result.trials.append(trial)
        if on_trial:
            on_trial(trial)
        if trial.ok and trial.score is not None and _is_better(metric, trial.score, result.best_score):
            result.best_score = trial.score
            result.best_params = dict(params)
        # Optuna minimizes; a failed trial must not look optimal.
        if trial.score is None:
            return float("inf") if metric == "max" else float("-inf")
        return trial.score

    if have_optuna:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        direction = "maximize" if metric == "max" else "minimize"
        study = optuna.create_study(direction=direction,
                                    sampler=optuna.samplers.TPESampler(seed=seed))

        def _objective(trial: Any) -> float:
            params = {p.name: p.suggest_optuna(trial) for p in space}
            return _record(trial.number, params)

        study.optimize(_objective, n_trials=n_trials)
    else:
        rng = random.Random(seed)
        for number in range(n_trials):
            params = {p.name: p.sample_random(rng) for p in space}
            _record(number, params)

    return result
