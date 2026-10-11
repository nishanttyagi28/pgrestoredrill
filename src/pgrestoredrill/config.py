"""Process settings. URLs stay in memory and are not logged."""

from __future__ import annotations

import logging
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
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
    # external uses target_url. docker starts a local container. k8s-sidecar uses the pod.
    target_kind: str = "external"
    sidecar_password: str = Field(default="", repr=False)
    sidecar_host: str = "127.0.0.1"
    sidecar_port: int = 5432
    sidecar_user: str = "postgres"
    log_level: str = "INFO"
    # Empty values leave credential selection to the AWS default chain.
    s3_access_key: str = Field(default="", repr=False)
    s3_secret_key: str = Field(default="", repr=False)
    # Empty refuses every authenticated API request.
    admin_token: str = Field(default="", repr=False)
    # Empty skips alerts. The URL is not logged.
    alert_webhook_url: str = Field(default="", repr=False)

    @field_validator("database_url")
    @classmethod
    def _require_database(cls, value: str) -> str:
        database_name(value)
        return value

    @field_validator("target_kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in {"external", "docker", "k8s-sidecar"}:
            raise ValueError("invalid target kind")
        return value

    @model_validator(mode="after")
    def _target(self) -> Self:
        if self.target_kind == "external":
            database_name(self.target_url)
        if self.target_kind == "k8s-sidecar":
            if self.sidecar_user.strip() == "" or self.sidecar_host.strip() == "":
                raise ValueError("invalid sidecar address")
            if self.sidecar_port <= 0 or self.sidecar_port > 65535:
                raise ValueError("invalid sidecar address")
        return self

    @field_validator("log_level")
    @classmethod
    def _normalize_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError("invalid log level")
        return normalized

    @field_validator("alert_webhook_url")
    @classmethod
    def _webhook(cls, value: str) -> str:
        text = value.strip()
        if text == "":
            return ""
        parts = urlsplit(text)
        if parts.scheme not in {"http", "https"} or parts.hostname is None:
            raise ValueError("invalid alert webhook")
        if parts.username is not None or parts.password is not None:
            raise ValueError("invalid alert webhook")
        return text
