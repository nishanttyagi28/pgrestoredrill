"""Drill file loaded by the CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class DrillFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    source_kind: str = Field(pattern=r"^(local|s3)$")
    source_uri: str = Field(min_length=1)
    rpo_minutes: int = Field(gt=0)
    assertions_file: str = Field(min_length=1)
    enabled: bool = True
    restore_timeout_seconds: float = Field(default=60, gt=0, le=86_400)
    statement_timeout_ms: int = Field(default=5000, gt=0, le=3_600_000)
    bucket: str | None = Field(default=None, min_length=1, max_length=255)
    endpoint_url: str | None = None
    region: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]+$", max_length=64)
    min_bytes: int | None = Field(default=None, gt=0)
    max_age_minutes: int | None = Field(default=None, gt=0)

    @field_validator("endpoint_url")
    @classmethod
    def _endpoint(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or parts.hostname is None:
            raise ValueError("invalid s3 endpoint")
        if parts.username is not None or parts.password is not None:
            raise ValueError("invalid s3 endpoint")
        return value

    @model_validator(mode="after")
    def _s3_bucket(self) -> Self:
        if self.source_kind == "s3" and self.bucket is None:
            raise ValueError("s3 source requires a bucket")
        return self


def load_drill(path: Path) -> DrillFile:
    if not path.is_file():
        raise FileNotFoundError("drill config not found")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise ValueError("invalid drill config") from None
    try:
        return DrillFile.model_validate(raw)
    except ValidationError:
        raise ValueError("invalid drill config") from None


def resolve_from_config(config_path: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (config_path.parent / path).resolve()
