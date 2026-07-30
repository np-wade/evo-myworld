"""Unit tests for the LLM-as-judge layer (no real model calls)."""

from __future__ import annotations

import pytest

from evo import judges


def _stub(text: str):
    """Return a call-fn that ignores the prompt and yields ``text``."""
    return lambda _prompt: text


def test_g_eval_normalizes_score_to_unit_interval():
    r = judges.g_eval(
        "some output",
        task_introduction="t",
        evaluation_criteria="c",
        name="demo",
        call=_stub('{"score": 8, "reason": "mostly good"}'),
    )
    assert r.name == "demo"
    assert r.raw_score == 8.0
    assert r.value == pytest.approx(0.8)
    assert r.reason == "mostly good"
    assert r.scale_max == 10.0


def test_g_eval_parses_fenced_and_prose_wrapped_json():
    fenced = _stub('```json\n{"score": 10, "reason": "perfect"}\n```')
    assert judges.g_eval("o", task_introduction="t", evaluation_criteria="c", call=fenced).value == 1.0

    prose = _stub('Here is my verdict:\n{"score": 5, "reason": "ok"} — done.')
    assert judges.g_eval("o", task_introduction="t", evaluation_criteria="c", call=prose).value == pytest.approx(0.5)


def test_g_eval_clamps_out_of_range_score():
    r = judges.g_eval("o", task_introduction="t", evaluation_criteria="c",
                      call=_stub('{"score": 42, "reason": "overshoot"}'))
    assert r.raw_score == 10.0 and r.value == 1.0


def test_g_eval_custom_scale():
    r = judges.g_eval("o", task_introduction="t", evaluation_criteria="c", scale_max=5,
                      call=_stub('{"score": 3, "reason": "x"}'))
    assert r.raw_score == 3.0 and r.value == pytest.approx(0.6)


def test_g_eval_raises_on_unparsable_output():
    with pytest.raises(judges.JudgeError):
        judges.g_eval("o", task_introduction="t", evaluation_criteria="c", call=_stub("no json here"))


def test_g_eval_raises_on_missing_score():
    with pytest.raises(judges.JudgeError):
        judges.g_eval("o", task_introduction="t", evaluation_criteria="c",
                      call=_stub('{"reason": "forgot the score"}'))


def test_preset_scoring_uses_named_rubric():
    r = judges.g_eval_preset("diff text", preset="diff_matches_brief",
                             call=_stub('{"score": 7, "reason": "on brief"}'))
    assert r.name == "g_eval_diff_matches_brief"
    assert r.value == pytest.approx(0.7)


def test_unknown_preset_raises():
    with pytest.raises(judges.JudgeError):
        judges.g_eval_preset("x", preset="does_not_exist", call=_stub("{}"))


def test_result_event_error_surfaces():
    events = [{"type": "result", "is_error": True, "result": "boom"}]
    with pytest.raises(judges.JudgeError):
        judges._result_text(events)


def test_prompt_includes_context_and_input_blocks():
    p = judges.build_geval_prompt(
        task_introduction="t", evaluation_criteria="c", output="o",
        context="CTX", input="Q?",
    )
    assert "CTX" in p and "Q?" in p and "0 to 10 scale" in p
