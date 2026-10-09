"""Drill file loaded by the CLI."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class DrillFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    source_kind: str = Field(pattern=r"^local$")
    source_uri: str = Field(min_length=1)
    rpo_minutes: int = Field(gt=0)
    assertions_file: str = Field(min_length=1)
    enabled: bool = True
    restore_timeout_seconds: float = Field(default=60, gt=0, le=86_400)
    statement_timeout_ms: int = Field(default=5000, gt=0, le=3_600_000)


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
