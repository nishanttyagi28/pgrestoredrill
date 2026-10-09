"""Refuse databases that were not created for a drill, before connecting."""

from __future__ import annotations

import pytest

from pgrestoredrill.errors import TargetNotDrillDatabase
from pgrestoredrill.targets.external import (
    drop_database,
    ensure_restore_allowed,
    is_drill_database,
)


def test_drill_database_name_shape() -> None:
    assert is_drill_database("pgrestoredrill_" + ("ab" * 16)) is True
    assert is_drill_database("postgres") is False
    assert is_drill_database("pgrestoredrill_meta_" + ("ab" * 16)) is False
    assert is_drill_database("pgrestoredrill_") is False


def test_refuses_other_databases_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("should not connect")

    monkeypatch.setattr("pgrestoredrill.targets.external.connect", explode)
    with pytest.raises(TargetNotDrillDatabase, match="postgres"):
        ensure_restore_allowed("postgresql://user:secret@localhost/postgres")
    with pytest.raises(TargetNotDrillDatabase, match="postgres"):
        drop_database("postgresql://user:secret@localhost/postgres", "postgres")
