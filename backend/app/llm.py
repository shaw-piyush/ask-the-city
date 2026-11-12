import json
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError, model_validator


class LLMOutputError(Exception):
    """The model's answer could not be parsed or is internally inconsistent."""


class LLMAnswer(BaseModel):
    sql: str | None
    chart_type: Literal["line", "bar", "grouped_bar", "table", "number"]
    x: str | None
    y: str | None
    series: str | None
    title: str
    explanation: str
    cannot_answer: str | None

    @model_validator(mode="after")
    def _exactly_one_of_sql_or_cannot_answer(self) -> "LLMAnswer":
        if self.sql is not None and not self.sql.strip():
            raise ValueError("sql must not be an empty string")
        if self.cannot_answer is not None and not self.cannot_answer.strip():
            raise ValueError("cannot_answer must not be an empty string")
        if self.sql is not None and self.cannot_answer is not None:
            raise ValueError("set exactly one of sql and cannot_answer, not both")
        if self.sql is None and self.cannot_answer is None:
            raise ValueError("set exactly one of sql and cannot_answer, got neither")
        return self


def parse_answer(raw: str | dict) -> LLMAnswer:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise LLMOutputError(f"invalid JSON: {e}") from e
    if not isinstance(raw, dict):
        raise LLMOutputError("invalid answer: expected a JSON object")
    try:
        return LLMAnswer.model_validate(raw)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'answer'}: {err['msg']}"
            for err in e.errors()
        )
        raise LLMOutputError(f"invalid answer: {problems}") from e


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class RepairContext:
    previous_sql: str
    error: str


@dataclass(frozen=True)
class LLMResult:
    answer: LLMAnswer
    usage: TokenUsage


class LLM(Protocol):
    def answer(
        self,
        question: str,
        schema_card: str,
        repair_context: RepairContext | None = None,
    ) -> LLMResult: ...


class FakeLLM:
    """Returns or raises scripted items in order and records every call."""

    def __init__(self, script: list[LLMAnswer | Exception]):
        self._script = list(script)
        self.calls: list[tuple[str, str, RepairContext | None]] = []

    def answer(
        self,
        question: str,
        schema_card: str,
        repair_context: RepairContext | None = None,
    ) -> LLMResult:
        self.calls.append((question, schema_card, repair_context))
        if len(self.calls) > len(self._script):
            raise AssertionError(
                f"FakeLLM called {len(self.calls)} times but only "
                f"{len(self._script)} answers were scripted"
            )
        item = self._script[len(self.calls) - 1]
        if isinstance(item, Exception):
            raise item
        return LLMResult(answer=item, usage=TokenUsage(0, 0))
