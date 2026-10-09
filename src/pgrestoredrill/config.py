"""Process settings. URLs stay in memory and are not logged."""

from __future__ import annotations

import logging

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from pgrestoredrill.db.urls import database_name


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Empty until the environment or the caller supplies a URL. Validation rejects it.
    database_url: str = ""
    target_url: str = ""
    log_level: str = "INFO"

    @field_validator("database_url", "target_url")
    @classmethod
    def _require_database(cls, value: str) -> str:
        database_name(value)
        return value

    @field_validator("log_level")
    @classmethod
    def _normalize_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError("invalid log level")
        return normalized
