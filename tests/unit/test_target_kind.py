"""Target kind settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgrestoredrill.config import Settings

_DATABASE = "postgresql://localhost/pgrestoredrill"


def test_external_target_requires_a_url() -> None:
    settings = Settings(
        database_url=_DATABASE,
        target_url="postgresql://localhost/postgres",
        log_level="INFO",
    )
    assert settings.target_kind == "external"
    with pytest.raises(ValidationError):
        Settings(database_url=_DATABASE, target_url="", log_level="INFO")


def test_docker_target_does_not_require_a_url() -> None:
    settings = Settings(
        database_url=_DATABASE,
        target_url="",
        target_kind="docker",
        log_level="INFO",
    )
    assert settings.target_kind == "docker"


def test_sidecar_password_is_hidden_and_optional_for_the_api() -> None:
    settings = Settings(
        database_url=_DATABASE,
        target_url="",
        target_kind="k8s-sidecar",
        sidecar_password="s3cret",
        log_level="INFO",
    )
    assert "s3cret" not in repr(settings)
    api = Settings(
        database_url=_DATABASE,
        target_url="",
        target_kind="k8s-sidecar",
        sidecar_password="",
        log_level="INFO",
    )
    assert api.sidecar_password == ""


def test_target_kind_must_be_known() -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(
            database_url=_DATABASE,
            target_url="postgresql://localhost/postgres",
            target_kind="kind",
            log_level="INFO",
        )
    assert caught.value.errors()[0]["msg"] == "Value error, invalid target kind"
