import json

import pytest

from app.llm import (
    FakeLLM,
    LLMAnswer,
    LLMOutputError,
    LLMResult,
    RepairContext,
    TokenUsage,
    parse_answer,
)

VALID = {
    "sql": "SELECT 1 AS n",
    "chart_type": "number",
    "x": None,
    "y": "n",
    "series": None,
    "title": "One",
    "explanation": "Returns one.",
    "cannot_answer": None,
}


def make(**over) -> LLMAnswer:
    return LLMAnswer(**{**VALID, **over})


def test_valid_dict_and_string():
    assert parse_answer(VALID).sql == "SELECT 1 AS n"
    assert parse_answer(json.dumps(VALID)).chart_type == "number"


def test_valid_cannot_answer():
    a = parse_answer({**VALID, "sql": None, "chart_type": "table", "cannot_answer": "No such data."})
    assert a.cannot_answer == "No such data."


def test_all_fields_required_in_schema():
    schema = LLMAnswer.model_json_schema()
    assert set(schema["required"]) == set(VALID)


def test_invalid_json():
    with pytest.raises(LLMOutputError, match="invalid JSON"):
        parse_answer("{not json")


def test_non_object():
    with pytest.raises(LLMOutputError, match="JSON object"):
        parse_answer("[1, 2]")


def test_missing_field():
    raw = {k: v for k, v in VALID.items() if k != "title"}
    with pytest.raises(LLMOutputError, match="title"):
        parse_answer(raw)


def test_wrong_type():
    with pytest.raises(LLMOutputError, match="explanation"):
        parse_answer({**VALID, "explanation": 5})


def test_unknown_chart_type():
    with pytest.raises(LLMOutputError, match="chart_type"):
        parse_answer({**VALID, "chart_type": "pie"})


def test_empty_sql():
    with pytest.raises(LLMOutputError, match="empty"):
        parse_answer({**VALID, "sql": ""})


def test_both_set():
    with pytest.raises(LLMOutputError, match="both"):
        parse_answer({**VALID, "cannot_answer": "nope"})


def test_neither_set():
    with pytest.raises(LLMOutputError, match="neither"):
        parse_answer({**VALID, "sql": None})


def test_fake_llm_order_and_calls():
    err = RuntimeError("boom")
    a, b = make(), make(title="Two")
    fake = FakeLLM([a, err, b])
    r = fake.answer("q1", "card")
    assert r == LLMResult(a, TokenUsage(0, 0))
    ctx = RepairContext("SELECT 1", "bad")
    with pytest.raises(RuntimeError):
        fake.answer("q2", "card", ctx)
    assert fake.answer("q3", "card2").answer is b
    assert fake.calls == [("q1", "card", None), ("q2", "card", ctx), ("q3", "card2", None)]


def test_fake_llm_exhausted():
    fake = FakeLLM([make()])
    fake.answer("q", "card")
    with pytest.raises(AssertionError, match="only 1 answers were scripted"):
        fake.answer("q", "card")
