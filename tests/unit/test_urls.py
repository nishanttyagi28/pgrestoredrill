"""Database URL handling."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgrestoredrill.config import Settings
from pgrestoredrill.db.session import make_engine
from pgrestoredrill.db.urls import database_name, for_libpq, for_sqlalchemy, swap_database
from pgrestoredrill.redact import redact


def test_libpq_and_sqlalchemy_urls() -> None:
    converted = for_libpq("postgres://localhost/pgrestoredrill")
    assert converted == "postgresql://localhost/pgrestoredrill"
    sqlalchemy = for_sqlalchemy("postgresql://localhost/pgrestoredrill")
    assert sqlalchemy == "postgresql+psycopg://localhost/pgrestoredrill"
    assert for_libpq(sqlalchemy) == "postgresql://localhost/pgrestoredrill"


def test_rejects_unknown_scheme_and_missing_name() -> None:
    with pytest.raises(ValueError, match="scheme"):
        for_libpq("mysql://localhost/db")
    with pytest.raises(ValueError, match="database name"):
        database_name("postgresql://localhost")


def test_swap_preserves_credentials_and_query() -> None:
    name = "pgrestoredrill_" + ("ab" * 16)
    swapped = swap_database(
        "postgresql://user:secret@localhost:5432/postgres?sslmode=disable",
        name,
    )
    assert swapped == f"postgresql://user:secret@localhost:5432/{name}?sslmode=disable"
    assert database_name(swapped) == name


def test_swap_rejects_unsafe_names() -> None:
    with pytest.raises(ValueError, match="invalid database name"):
        swap_database("postgresql://localhost/postgres", "bad-name")


def test_settings_normalize_log_level() -> None:
    settings = Settings(
        database_url="postgres://localhost/pgrestoredrill",
        target_url="postgresql://localhost/postgres",
        log_level="debug",
    )
    assert settings.log_level == "DEBUG"


def test_alert_webhook_is_optional_and_hides_its_value() -> None:
    blank = Settings(
        database_url="postgresql://localhost/pgrestoredrill",
        target_url="postgresql://localhost/postgres",
        log_level="INFO",
        alert_webhook_url="  ",
    )
    assert blank.alert_webhook_url == ""
    hooked = blank.model_copy(update={"alert_webhook_url": "https://alerts.example/hook"})
    assert "alerts.example" not in repr(hooked)
    with pytest.raises(ValidationError) as caught:
        Settings(
            database_url="postgresql://localhost/pgrestoredrill",
            target_url="postgresql://localhost/postgres",
            log_level="INFO",
            alert_webhook_url="http://user:secret@alerts.example/hook",
        )
    assert caught.value.errors()[0]["msg"] == "Value error, invalid alert webhook"
    assert "secret" not in caught.value.errors()[0]["msg"]


def test_settings_reject_bad_values() -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="mysql://localhost/db",
            target_url="postgresql://localhost/postgres",
            log_level="INFO",
        )
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql://localhost/pgrestoredrill",
            target_url="postgresql://localhost/postgres",
            log_level="loud",
        )


def test_engine_uses_psycopg() -> None:
    engine = make_engine("postgresql://localhost/pgrestoredrill")
    try:
        assert engine.url.drivername == "postgresql+psycopg"
    finally:
        engine.dispose()


def test_redact_hides_passwords() -> None:
    text = "failed postgresql+psycopg://user:secret@localhost/db password=secret"
    hidden = redact(text)
    assert "secret" not in hidden
    assert "***" in hidden
    assert redact("no secrets here") == "no secrets here"
