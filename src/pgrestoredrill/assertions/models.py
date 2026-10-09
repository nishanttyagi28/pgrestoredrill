"""Assertion documents supplied by the operator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

AssertionType = Literal["rows_gte", "equals", "max_age_minutes"]


class AssertionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1, max_length=200)
    assertion_type: AssertionType = Field(alias="type")
    sql: str
    expected: int | float | str

    @field_validator("sql")
    @classmethod
    def _single_statement(cls, value: str) -> str:
        stripped = value.strip()
        if stripped.endswith(";"):
            stripped = stripped[:-1].strip()
        if not stripped:
            raise ValueError("sql is required")
        if ";" in stripped:
            raise ValueError("sql must be a single statement")
        return stripped

    @field_validator("expected")
    @classmethod
    def _check_expected(cls, value: int | float | str, info: ValidationInfo) -> int | float | str:
        if isinstance(value, bool):
            raise ValueError("expected must not be a boolean")
        kind = info.data.get("assertion_type")
        if kind in {"rows_gte", "max_age_minutes"} and not isinstance(value, (int, float)):
            raise ValueError("expected must be a number")
        return value


@dataclass(frozen=True)
class AssertionOutcome:
    name: str
    passed: bool
    observed: str | None
    expected: str
    duration_ms: int
