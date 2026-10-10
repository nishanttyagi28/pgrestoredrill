"""Empty and stale dumps are stored as failed runs and are not restored."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_FAILED, AssertionResult, Run
from pgrestoredrill.db.urls import swap_database
from pgrestoredrill.errors import RestoreFailed
from pgrestoredrill.runner.service import execute_drill
from pgrestoredrill.sources.s3 import RemoteObject


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
    _block_restore(monkeypatch)
    completed = execute_drill(settings, _local(tmp_path, "empty-local", folder))
    assert completed.status == STATUS_FAILED
    assert completed.error == "dump is empty"
    assert completed.database_name is None
    assert completed.restore_seconds is None
    assert completed.assertions == ()
    assert completed.dump_bytes == 0
    assert completed.dump_sha256 == hashlib.sha256(b"").hexdigest()
    _assert_failed_history(engine, completed.run_id)
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
    _block_restore(monkeypatch)
    completed = execute_drill(
        settings,
        _local(tmp_path, "stale-local", folder, max_age_minutes=60),
    )
    assert completed.status == STATUS_FAILED
    assert completed.error == "dump is older than max_age_minutes"
    assert completed.dump_bytes == 3
    assert completed.database_name is None
    _assert_failed_history(engine, completed.run_id)
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
    _block_restore(monkeypatch)
    completed = execute_drill(
        settings,
        _local(tmp_path, "small-local", folder, min_bytes=100),
    )
    assert completed.status == STATUS_FAILED
    assert completed.error == "dump is smaller than min_bytes"
    assert completed.database_name is None
    _assert_failed_history(engine, completed.run_id)


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

    monkeypatch.setattr("pgrestoredrill.runner.service.create_drill_database", fake_create)
    monkeypatch.setattr("pgrestoredrill.runner.service.restore_dump", fake_restore)
    completed = execute_drill(
        settings,
        _local(tmp_path, "fresh-local", folder, min_bytes=4, max_age_minutes=60),
    )
    assert called == {"create": True, "restore": True}
    assert completed.status == "error"
    assert completed.error == "pg_restore exited 1: stopped"


def test_empty_s3_object_is_refused_and_the_temp_file_is_removed(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _run_s3(
        settings,
        engine,
        tmp_path,
        monkeypatch,
        name="empty-s3",
        key="backups/empty.dump",
        modified=datetime.now(UTC),
        payload=b"",
    )
    assert path.exists() is False


def test_stale_s3_object_is_refused_and_the_temp_file_is_removed(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _run_s3(
        settings,
        engine,
        tmp_path,
        monkeypatch,
        name="stale-s3",
        key="backups/old.dump",
        modified=datetime.now(UTC) - timedelta(days=2),
        payload=b"abc",
        max_age_minutes=60,
        reason="dump is older than max_age_minutes",
    )
    assert path.exists() is False


def _run_s3(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    key: str,
    modified: datetime,
    payload: bytes,
    max_age_minutes: int | None = None,
    reason: str = "dump is empty",
) -> Path:
    held: dict[str, Path] = {}
    real = tempfile.mkstemp

    def wrapped(*args: object, **kwargs: object) -> tuple[int, str]:
        descriptor, filename = real(*args, **kwargs)
        held["path"] = Path(filename)
        return descriptor, filename

    def fake_open(**kwargs: object) -> _FixedStore:
        return _FixedStore(key, modified, payload)

    monkeypatch.setattr("pgrestoredrill.sources.s3.tempfile.mkstemp", wrapped)
    monkeypatch.setattr("pgrestoredrill.runner.acquire.open_s3_store", fake_open)
    _block_restore(monkeypatch)
    completed = execute_drill(
        settings,
        _s3(tmp_path, name, max_age_minutes=max_age_minutes),
    )
    assert completed.status == STATUS_FAILED
    assert completed.error == reason
    assert completed.dump_path == key
    assert completed.dump_bytes == len(payload)
    assert completed.dump_sha256 == hashlib.sha256(payload).hexdigest()
    assert completed.database_name is None
    _assert_failed_history(engine, completed.run_id)
    return held["path"]


class _FixedStore:
    def __init__(self, key: str, modified: datetime, payload: bytes) -> None:
        self._key = key
        self._modified = modified
        self._payload = payload

    def list_dumps(self, bucket: str, prefix: str) -> tuple[RemoteObject, ...]:
        return (RemoteObject(key=self._key, modified=self._modified),)

    def open_dump(self, bucket: str, key: str) -> Iterator[bytes]:
        assert key == self._key
        yield self._payload


def _block_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(url: str) -> str:
        raise AssertionError("should not create a database")

    monkeypatch.setattr("pgrestoredrill.runner.service.create_drill_database", explode)


def _assert_failed_history(engine: Engine, run_id: object) -> None:
    assert run_id is not None
    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        results = list(
            session.scalars(select(AssertionResult).where(AssertionResult.run_id == run.id)).all()
        )
    assert run.status == STATUS_FAILED
    assert run.restore_seconds is None
    assert results == []


def _local(
    root: Path,
    name: str,
    folder: Path,
    *,
    min_bytes: int | None = None,
    max_age_minutes: int | None = None,
) -> Path:
    body: dict[str, object] = {
        "name": name,
        "source_kind": "local",
        "source_uri": folder.as_posix(),
        "rpo_minutes": 60,
        "assertions_file": "assertions.yaml",
    }
    if min_bytes is not None:
        body["min_bytes"] = min_bytes
    if max_age_minutes is not None:
        body["max_age_minutes"] = max_age_minutes
    return _write(root, body)


def _s3(root: Path, name: str, *, max_age_minutes: int | None) -> Path:
    body: dict[str, object] = {
        "name": name,
        "source_kind": "s3",
        "source_uri": "backups/",
        "bucket": "drills",
        "endpoint_url": "http://127.0.0.1:9",
        "region": "us-east-1",
        "rpo_minutes": 60,
        "assertions_file": "assertions.yaml",
    }
    if max_age_minutes is not None:
        body["max_age_minutes"] = max_age_minutes
    return _write(root, body)


def _write(root: Path, body: dict[str, object]) -> Path:
    (root / "assertions.yaml").write_text(
        yaml.safe_dump([{"name": "present", "type": "rows_gte", "sql": "SELECT 1", "expected": 1}]),
        encoding="utf-8",
    )
    config = root / "drill.yaml"
    config.write_text(yaml.safe_dump(body), encoding="utf-8")
    return config
