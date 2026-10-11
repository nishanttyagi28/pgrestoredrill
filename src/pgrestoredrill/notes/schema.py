"""Strict shape of one failure suggestion."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

Category = Literal[
    "missing extension",
    "missing role",
    "version mismatch",
    "permission denied",
    "disk full",
    "timeout",
    "assertion failed",
    "unknown",
]

CATEGORIES: tuple[Category, ...] = (
    "missing extension",
    "missing role",
    "version mismatch",
    "permission denied",
    "disk full",
    "timeout",
    "assertion failed",
    "unknown",
)

MISSING_EXTENSION: Category = "missing extension"
MISSING_ROLE: Category = "missing role"
VERSION_MISMATCH: Category = "version mismatch"
PERMISSION_DENIED: Category = "permission denied"
DISK_FULL: Category = "disk full"
TIMEOUT: Category = "timeout"
ASSERTION_FAILED: Category = "assertion failed"
UNKNOWN: Category = "unknown"
_TEXT_LIMIT = 300


class FailureNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    short_reason: str = Field(min_length=1, max_length=_TEXT_LIMIT)
    suggested_next_step: str = Field(min_length=1, max_length=_TEXT_LIMIT)

    @field_validator("short_reason", "suggested_next_step")
    @classmethod
    def _text(cls, value: str) -> str:
        text = value.strip()
        if text == "" or len(text) > _TEXT_LIMIT:
            raise ValueError("invalid note text")
        return text


def parse_note(raw: str) -> FailureNote | None:
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    try:
        return FailureNote.model_validate(loaded)
    except ValidationError:
        return None
