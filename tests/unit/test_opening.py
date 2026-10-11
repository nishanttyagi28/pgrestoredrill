"""Restore target selection."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from pgrestoredrill.config import Settings
from pgrestoredrill.errors import TargetError
from pgrestoredrill.targets.opening import open_restore_url

_DATABASE = "postgresql://localhost/pgrestoredrill"
_DRILL = "postgresql://127.0.0.1/pgrestoredrill_" + ("ab" * 16)


def test_external_uses_the_admin_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def created(url: str) -> str:
        assert url == "postgresql://localhost/postgres"
        return _DRILL

    monkeypatch.setattr("pgrestoredrill.targets.opening.create_drill_database", created)
    settings = Settings(
        database_url=_DATABASE,
        target_url="postgresql://localhost/postgres",
        log_level="INFO",
    )
    with open_restore_url(settings) as url:
        assert url == _DRILL


def test_docker_is_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def started() -> Iterator[str]:
        yield _DRILL

    monkeypatch.setattr("pgrestoredrill.targets.opening.docker_database", started)
    settings = Settings(
        database_url=_DATABASE,
        target_url="",
        target_kind="docker",
        log_level="INFO",
    )
    with open_restore_url(settings) as url:
        assert url == _DRILL


def test_unknown_kind_is_refused() -> None:
    settings = Settings.model_construct(target_kind="other")
    with pytest.raises(TargetError, match="unknown target"), open_restore_url(settings):
        pass


def test_sidecar_is_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    def prepared(**kwargs: object) -> str:
        assert kwargs["user"] == "postgres"
        assert kwargs["password"] == "s3cret"
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 5432
        return _DRILL

    monkeypatch.setattr("pgrestoredrill.targets.opening.prepare_sidecar", prepared)
    settings = Settings(
        database_url=_DATABASE,
        target_url="",
        target_kind="k8s-sidecar",
        sidecar_password="s3cret",
        log_level="INFO",
    )
    with open_restore_url(settings) as url:
        assert url == _DRILL
