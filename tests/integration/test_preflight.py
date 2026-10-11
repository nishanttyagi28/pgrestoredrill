"""Empty and stale local dumps are stored as failed runs and are not restored."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import Engine

from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_FAILED
from pgrestoredrill.db.urls import swap_database
from pgrestoredrill.errors import RestoreFailed
from pgrestoredrill.runner.service import execute_drill
from tests.integration.preflight_helpers import (
    assert_failed_history,
    block_restore,
    local_config,
)


def test_empty_local_dump_is_refused(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "dumps"
    folder.mkdir()
    dump = folder / "empty.dump"
    dump.write_bytes(b"")
    block_restore(monkeypatch)
    completed = execute_drill(settings, local_config(tmp_path, "empty-local", folder))
    assert completed.status == STATUS_FAILED
    assert completed.error == "dump is empty"
    assert completed.database_name is None
    assert completed.restore_seconds is None
    assert completed.assertions == ()
    assert completed.dump_bytes == 0
    assert completed.dump_sha256 == hashlib.sha256(b"").hexdigest()
    assert_failed_history(engine, completed.run_id)
    assert dump.exists() is True


def test_stale_local_dump_is_refused(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "dumps"
    folder.mkdir()
    dump = folder / "old.dump"
    dump.write_bytes(b"abc")
    os.utime(dump, (1_600_000_000, 1_600_000_000))
    block_restore(monkeypatch)
    completed = execute_drill(
        settings,
        local_config(tmp_path, "stale-local", folder, max_age_minutes=60),
    )
    assert completed.status == STATUS_FAILED
    assert completed.error == "dump is older than max_age_minutes"
    assert completed.dump_bytes == 3
    assert completed.database_name is None
    assert_failed_history(engine, completed.run_id)
    assert dump.exists() is True


def test_small_local_dump_is_refused(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "dumps"
    folder.mkdir()
    (folder / "small.dump").write_bytes(b"abc")
    block_restore(monkeypatch)
    completed = execute_drill(
        settings,
        local_config(tmp_path, "small-local", folder, min_bytes=100),
    )
    assert completed.status == STATUS_FAILED
    assert completed.error == "dump is smaller than min_bytes"
    assert completed.database_name is None
    assert_failed_history(engine, completed.run_id)


def test_fresh_dump_still_reaches_restore(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "dumps"
    folder.mkdir()
    dump = folder / "fresh.dump"
    dump.write_bytes(b"abcd")
    os.utime(dump, None)
    called: dict[str, bool] = {}

    def fake_create(url: str) -> str:
        called["create"] = True
        return swap_database(url, "pgrestoredrill_" + "ab" * 16)

    def fake_restore(path: Path, target: object, timeout: float) -> None:
        called["restore"] = True
        raise RestoreFailed(1, "stopped", 0.01)

    monkeypatch.setattr("pgrestoredrill.targets.opening.create_drill_database", fake_create)
    monkeypatch.setattr("pgrestoredrill.runner.service.restore_dump", fake_restore)
    completed = execute_drill(
        settings,
        local_config(tmp_path, "fresh-local", folder, min_bytes=4, max_age_minutes=60),
    )
    assert called == {"create": True, "restore": True}
    assert completed.status == "error"
    assert completed.error == "pg_restore exited 1: stopped"
