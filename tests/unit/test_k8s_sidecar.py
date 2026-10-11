"""Sidecar target preparation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest

from pgrestoredrill.errors import TargetError
from pgrestoredrill.targets.k8s_sidecar import prepare_sidecar

_DRILL = "postgresql://127.0.0.1/pgrestoredrill_" + ("ab" * 16)


def test_prepare_waits_and_creates_a_drill_database(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    @contextmanager
    def connected(url: str, *, autocommit: bool) -> Iterator[object]:
        assert autocommit is True
        assert "p%40ss%2Fword" in url
        assert "s3cret" not in url

        class _Connection:
            def execute(self, query: str) -> None:
                assert query == "SELECT 1"

        yield _Connection()

    def created(url: str) -> str:
        seen.append(url)
        return _DRILL

    monkeypatch.setattr("pgrestoredrill.targets.k8s_sidecar.connect", connected)
    monkeypatch.setattr("pgrestoredrill.targets.k8s_sidecar.create_drill_database", created)
    url = prepare_sidecar(
        user="postgres",
        password="p@ss/word",
        host="127.0.0.1",
        port=5432,
        attempts=1,
    )
    assert url == _DRILL
    assert seen == ["postgresql://postgres:p%40ss%2Fword@127.0.0.1:5432/postgres"]


def test_missing_password_is_refused() -> None:
    with pytest.raises(TargetError, match="sidecar password is required"):
        prepare_sidecar(user="postgres", password="  ", attempts=1)


def test_bad_address_does_not_reveal_the_password() -> None:
    with pytest.raises(TargetError, match="invalid sidecar address") as caught:
        prepare_sidecar(user="postgres", password="s3cret", host="bad host", attempts=1)
    assert "s3cret" not in str(caught.value)


def test_unready_sidecar_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(url: str, *, autocommit: bool) -> object:
        raise psycopg.OperationalError("down")

    slept: list[float] = []
    monkeypatch.setattr("pgrestoredrill.targets.k8s_sidecar.connect", down)
    with pytest.raises(TargetError, match="not ready") as caught:
        prepare_sidecar(
            user="postgres",
            password="s3cret",
            attempts=2,
            pause=0.25,
            sleep=slept.append,
        )
    assert slept == [0.25, 0.25]
    assert "s3cret" not in str(caught.value)
