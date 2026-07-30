"""LLM-as-judge scoring for Evo (G-Eval).

Evo's benchmark metric is a single opaque scalar (``--metric max|min``). This
module adds a *qualitative* scoring layer: given a task, a rubric, and an
output, a judge model returns a normalized [0, 1] score with a reason. It is
meant to run in a ``verify`` mission, or to auto-annotate an attempt after
``evo run``, so the mission DAG and the frontier carry judged evidence, not
just the raw metric.

The judge drives Claude the same way the dispatch host does -- via the
``claude -p --output-format json`` CLI (see :mod:`evo.hosts.claude_fork`) --
so it needs no API key and honors ``EVO_CLAUDE_BIN`` / ``EVO_DISPATCH_MODEL``.

The G-Eval prompt/parse design (derive chain-of-thought evaluation steps from
the criteria, then score 0-10 + reason as JSON) is adapted from
comet-ml/opik's ``opik.evaluation.metrics.llm_judges.g_eval`` (Apache-2.0);
Opik's cloud/litellm plumbing is not used. See NOTICE below.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# NOTICE: G-Eval prompt & score-parsing approach adapted from comet-ml/opik
# (Apache License 2.0). https://github.com/comet-ml/opik

CLAUDE_BIN = os.environ.get("EVO_CLAUDE_BIN", "claude")
DEFAULT_MODEL = os.environ.get("EVO_JUDGE_MODEL", os.environ.get("EVO_DISPATCH_MODEL", ""))
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("EVO_JUDGE_TIMEOUT", "180"))

#: A judge callable takes a fully-rendered prompt and returns the model's text.
CallFn = Callable[[str], str]


class JudgeError(RuntimeError):
    """The judge could not produce a usable score (call failed or unparsable)."""


@dataclass(frozen=True)
class JudgeResult:
    """A single judge verdict. ``value`` is normalized to [0, 1]."""

    name: str
    value: float
    reason: str
    raw_score: float  # the model's pre-normalization score (e.g. 0-10)
    scale_max: float
    model: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "evo.judge-result/v1",
            "name": self.name,
            "value": self.value,
            "reason": self.reason,
            "raw_score": self.raw_score,
            "scale_max": self.scale_max,
            "model": self.model,
            "meta": self.meta,
        }


# ---------------------------------------------------------------------------
# G-Eval presets (task introduction + rubric)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GEvalPreset:
    name: str
    task_introduction: str
    evaluation_criteria: str


#: Built-in rubrics. The first three are Evo-native (code/agent oriented); the
#: rest are adapted from Opik's GEVAL_PRESETS for general text tasks.
GEVAL_PRESETS: dict[str, GEvalPreset] = {
    "diff_matches_brief": GEvalPreset(
        name="g_eval_diff_matches_brief",
        task_introduction=(
            "You review a code change (unified diff) against the brief it was"
            " meant to satisfy. Reason briefly before scoring."
        ),
        evaluation_criteria=(
            "Return an integer score from 0 (does not address the brief) to 10"
            " (fully and precisely satisfies it). Check: 1) Does the diff do what"
            " the brief asks, with no missing pieces? 2) Does it avoid changing"
            " unrelated code or introducing scope creep? 3) Would a maintainer"
            " accept it as a faithful implementation of the brief?"
            " Use 0 when the change is off-target, 5 when it is partial or noisy,"
            " and 10 when it is a complete, minimal, on-brief implementation."
        ),
    ),
    "minimal_change": GEvalPreset(
        name="g_eval_minimal_change",
        task_introduction=(
            "You judge whether a code change is minimal and low-risk for the"
            " result it achieves. Reason briefly before scoring."
        ),
        evaluation_criteria=(
            "Return an integer score from 0 (sprawling/risky) to 10 (tight and"
            " safe). Check: 1) Is the diff the smallest reasonable change for the"
            " goal? 2) Does it avoid unrelated refactors, dead code, or churn?"
            " 3) Does it preserve existing style and public contracts?"
            " Use 0 for large unfocused rewrites, 5 for changes with notable"
            " incidental edits, and 10 for a surgical, style-matching change."
        ),
    ),
    "agent_trajectory": GEvalPreset(
        name="g_eval_agent_trajectory",
        task_introduction=(
            "You evaluate an autonomous agent's trajectory (its sequence of"
            " reasoning, tool calls, and observations) against the goal it was"
            " given. Reason briefly before scoring."
        ),
        evaluation_criteria=(
            "Return an integer score from 0 (incoherent/off-goal) to 10 (efficient"
            " and correct). Check: 1) Do the steps make progress toward the goal"
            " without redundant or contradictory actions? 2) Are tool calls used"
            " appropriately with their results actually incorporated? 3) Does the"
            " trajectory reach a correct, verifiable outcome?"
            " Use 0 for flailing or goal-ignoring runs, 5 for runs that reach the"
            " goal inefficiently or with unverified steps, and 10 for a direct,"
            " well-grounded, correct trajectory."
        ),
    ),
    "qa_relevance": GEvalPreset(
        name="g_eval_qa_relevance",
        task_introduction=(
            "You grade how well an answer addresses a user's question given"
            " optional supporting context. Provide reasoning before scoring."
        ),
        evaluation_criteria=(
            "Return an integer score from 0 (irrelevant) to 10 (direct and"
            " correct). Check: 1) Does the answer respond to the core question?"
            " 2) Are statements grounded in the provided context? 3) Is the answer"
            " concise and precise? Use 0 for answers that miss the question, 5 for"
            " partially relevant responses, and 10 for fully correct, grounded"
            " answers."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Prompt construction (single-call G-Eval)
# ---------------------------------------------------------------------------

_GEVAL_PROMPT = """\
You are a strict, fair evaluator. Assess the OUTPUT below against the task and \
evaluation criteria.

*** TASK INTRODUCTION:
{task_introduction}

*** EVALUATION CRITERIA:
{evaluation_criteria}

First, think step by step and derive the concrete evaluation steps implied by \
the criteria, then apply them to the output. The final score MUST be an integer \
on a 0 to {scale_max} scale.
{context_block}{input_block}
*** OUTPUT TO EVALUATE:
{output}

Return ONLY a JSON object, no prose outside it, with exactly these keys:
{{"score": <integer 0-{scale_max}>, "reason": "<one or two sentences>"}}
"""


def build_geval_prompt(
    *,
    task_introduction: str,
    evaluation_criteria: str,
    output: str,
    context: Optional[str] = None,
    input: Optional[str] = None,
    scale_max: int = 10,
) -> str:
    context_block = f"\n*** CONTEXT:\n{context}\n" if context else ""
    input_block = f"\n*** INPUT / QUESTION:\n{input}\n" if input else ""
    return _GEVAL_PROMPT.format(
        task_introduction=task_introduction.strip(),
        evaluation_criteria=evaluation_criteria.strip(),
        output=output,
        context_block=context_block,
        input_block=input_block,
        scale_max=scale_max,
    )


# ---------------------------------------------------------------------------
# Claude CLI call + output parsing
# ---------------------------------------------------------------------------


def _parse_events(stdout: str) -> list[dict[str, Any]]:
    """Parse `claude -p --output-format json` output (JSON array or JSONL).

    Mirrors evo.hosts.claude_fork._parse_events so the judge tolerates the same
    output shapes without importing the dispatch/explorer machinery.
    """
    stdout = stdout.strip()
    if not stdout:
        return []
    try:
        parsed = json.loads(stdout)
        if isinstance(parsed, list):
            return [e for e in parsed if isinstance(e, dict)]
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass
    out: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            if isinstance(ev, dict):
                out.append(ev)
        except json.JSONDecodeError:
            pass
    return out


def _result_text(events: list[dict[str, Any]]) -> str:
    """The assistant's final text is the `result` field of the result event."""
    for ev in events:
        if ev.get("type") == "result":
            if ev.get("is_error"):
                raise JudgeError(f"claude judge reported an error: {ev.get('result')!r}")
            text = ev.get("result")
            if isinstance(text, str) and text.strip():
                return text
    raise JudgeError("no result text in claude judge output")


def claude_call(prompt: str, *, model: str = "", timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    """Run one non-interactive `claude -p` and return the assistant's text."""
    cmd = [CLAUDE_BIN, "-p", "--output-format", "json"]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise JudgeError(
            f"claude binary not found ({CLAUDE_BIN!r}); set EVO_CLAUDE_BIN"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise JudgeError(f"claude judge timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise JudgeError(f"claude judge failed (exit={proc.returncode}): {(proc.stderr or '')[-500:]}")
    return _result_text(_parse_events(proc.stdout))


def _extract_json_object(text: str) -> dict[str, Any]:
    """Pull the JSON verdict out of the model text, tolerating code fences and
    surrounding prose by scanning for the first balanced ``{...}`` block."""
    text = text.strip()
    if text.startswith("```"):
        # strip a ```json ... ``` fence
        inner = text.split("```", 2)
        if len(inner) >= 2:
            body = inner[1]
            body = body[4:] if body.lstrip().lower().startswith("json") else body
            text = body.strip().rstrip("`").strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Fallback: first balanced brace span.
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise JudgeError(f"could not parse JSON verdict from judge output: {text[:200]!r}")


def _parse_score(text: str, *, name: str, scale_max: int, model: str) -> JudgeResult:
    obj = _extract_json_object(text)
    if "score" not in obj:
        raise JudgeError(f"judge verdict missing 'score': {obj!r}")
    try:
        raw = float(obj["score"])
    except (TypeError, ValueError) as exc:
        raise JudgeError(f"judge 'score' is not numeric: {obj.get('score')!r}") from exc
    # Clamp into range rather than reject; judges occasionally overshoot.
    raw = max(0.0, min(float(scale_max), raw))
    reason = str(obj.get("reason", "")).strip()
    return JudgeResult(
        name=name,
        value=raw / scale_max if scale_max else 0.0,
        reason=reason,
        raw_score=raw,
        scale_max=float(scale_max),
        model=model,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def g_eval(
    output: str,
    *,
    task_introduction: str,
    evaluation_criteria: str,
    context: Optional[str] = None,
    input: Optional[str] = None,
    name: str = "g_eval",
    scale_max: int = 10,
    model: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    call: Optional[CallFn] = None,
) -> JudgeResult:
    """Score ``output`` against a rubric with a single G-Eval judge call.

    ``call`` is an injectable ``prompt -> text`` function; it defaults to the
    real ``claude -p`` invocation but can be stubbed in tests so no tokens are
    spent. Raises :class:`JudgeError` on call or parse failure.
    """
    model = DEFAULT_MODEL if model is None else model
    prompt = build_geval_prompt(
        task_introduction=task_introduction,
        evaluation_criteria=evaluation_criteria,
        output=output,
        context=context,
        input=input,
        scale_max=scale_max,
    )
    fn: CallFn = call or (lambda p: claude_call(p, model=model or "", timeout=timeout))
    text = fn(prompt)
    return _parse_score(text, name=name, scale_max=scale_max, model=model or "")


def g_eval_preset(
    output: str,
    *,
    preset: str,
    context: Optional[str] = None,
    input: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    call: Optional[CallFn] = None,
) -> JudgeResult:
    """Score ``output`` with a named built-in rubric (see :data:`GEVAL_PRESETS`)."""
    if preset not in GEVAL_PRESETS:
        known = ", ".join(sorted(GEVAL_PRESETS))
        raise JudgeError(f"unknown judge preset {preset!r}; known: {known}")
    p = GEVAL_PRESETS[preset]
    return g_eval(
        output,
        task_introduction=p.task_introduction,
        evaluation_criteria=p.evaluation_criteria,
        context=context,
        input=input,
        name=p.name,
        model=model,
        timeout=timeout,
        call=call,
    )
