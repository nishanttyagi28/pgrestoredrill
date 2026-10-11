"""Response models for the run history API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Health(BaseModel):
    status: str


class DrillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    source_kind: str
    source_uri: str
    rpo_minutes: int
    enabled: bool


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    drill_id: UUID
    status: str
    dump_key: str | None
    dump_bytes: int | None
    dump_sha256: str | None
    restore_seconds: float | None
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    acked_by: str | None = None
    acked_at: datetime | None = None
    note: str | None = None


class AssertionResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    passed: bool
    observed: str | None
    expected: str
    duration_ms: int


class RunDetail(RunOut):
    assertions: list[AssertionResultOut]


class AckIn(BaseModel):
    by: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=500)

    @field_validator("by", "note")
    @classmethod
    def _text(cls, value: str) -> str:
        text = value.strip()
        if text == "":
            raise ValueError("must not be blank")
        return text


class AckOut(BaseModel):
    id: UUID
    acked_by: str
    acked_at: datetime
    note: str


class OpenFailureOut(BaseModel):
    id: UUID
    status: str
    finished_at: datetime | None
    error: str | None


class DrillStatusOut(BaseModel):
    id: UUID
    name: str
    rpo_minutes: int
    rpo_status: str
    open_failures: list[OpenFailureOut]
