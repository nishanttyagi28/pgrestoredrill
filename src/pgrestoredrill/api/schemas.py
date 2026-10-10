"""Response models for the run history API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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


class AssertionResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    passed: bool
    observed: str | None
    expected: str
    duration_ms: int


class RunDetail(RunOut):
    assertions: list[AssertionResultOut]
