import re
from pathlib import Path

import pytest

from app.guard import check_sql
from app.llm import RepairContext, parse_answer
from app.prompt import build_system_prompt, build_user_message, example_answers

DEMO_QUESTIONS = [
    "How many 311 requests were filed each month since May 2024?",
    "What are the 10 most common request types?",
    "Which council districts have the most pothole requests?",
    "How have missed garbage pickup requests changed month by month?",
    "How many requests are New, In Progress, or Closed?",
    "Which day of the week gets the most requests?",
    "What hours of the day see the most requests?",
    "Compare pothole requests this spring vs. last spring",
    "What's the median days-to-close by request type?",
    "Last 30 days vs. the 30 days before: which types grew most?",
]

CARD = "SCHEMA-CARD-MARKER\nTable requests_311 with columns."


def test_prompt_contains_card_rules_and_examples():
    p = build_system_prompt(CARD)
    assert CARD in p
    for field in ("sql", "chart_type", "x", "y", "series", "title", "explanation", "cannot_answer"):
        assert f"- {field}:" in p
    assert "cannot_answer" in p and "exactly one" in p
    assert len(example_answers()) == 4
    for q, _ in example_answers():
        assert f"Question: {q}" in p


def test_demo_questions_absent():
    p = build_system_prompt(CARD).lower()
    for q in DEMO_QUESTIONS:
        assert q.lower() not in p


def test_demo_questions_match_design_doc():
    design = (Path(__file__).resolve().parents[2] / "DESIGN.md").read_text()
    rows = re.findall(r"^\| \d+ \| (.+?) \| .+ \|$", design, re.M)
    assert rows == DEMO_QUESTIONS


@pytest.mark.parametrize("question,answer", example_answers())
def test_example_sql_passes_guard_and_runs(con, question, answer):
    parsed = parse_answer(answer)
    if parsed.sql is None:
        pytest.skip("example has no SQL")
    assert check_sql(parsed.sql).ok
    from app import db

    result = db.run_query(con, parsed.sql)
    for col in (parsed.x, parsed.y):
        if col:
            assert col in result.columns


def test_an_example_declines():
    declined = [a for _, a in example_answers() if a["cannot_answer"]]
    assert declined
    for a in declined:
        assert a["sql"] is None and a["chart_type"] == "table"
        assert a["x"] is None and a["y"] is None and a["series"] is None
        assert parse_answer(a).cannot_answer


def test_user_message():
    assert build_user_message("hi") == "hi"
    msg = build_user_message("hi", RepairContext("SELECT bad", "no such column"))
    assert "hi" in msg and "SELECT bad" in msg and "no such column" in msg


@pytest.fixture
def con(fixture_db_path):
    from app import db

    c = db.connect(fixture_db_path)
    yield c
    c.close()
