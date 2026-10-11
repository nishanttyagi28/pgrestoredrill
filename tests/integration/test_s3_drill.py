"""An S3 drill records the newest object and deletes its temp file."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import Run
from pgrestoredrill.db.urls import swap_database
from pgrestoredrill.errors import DumpSourceError, RestoreFailed
from pgrestoredrill.runner.service import execute_drill
from pgrestoredrill.sources.s3 import RemoteObject

_PAYLOAD = b"not-a-real-dump"


class _Store:
    def list_dumps(self, bucket: str, prefix: str) -> tuple[RemoteObject, ...]:
        assert bucket == "drills"
        assert prefix == "backups/"
        return (
            RemoteObject(
                key="backups/old.dump",
                modified=datetime(2020, 1, 1, tzinfo=UTC),
                size=3,
            ),
            RemoteObject(
                key="backups/new.dump",
                modified=datetime(2024, 6, 1, tzinfo=UTC),
                size=len(_PAYLOAD),
            ),
        )

    def open_dump(self, bucket: str, key: str) -> Iterator[bytes]:
        assert key == "backups/new.dump"
        yield _PAYLOAD


def test_s3_run_records_the_newest_object_and_deletes_the_temp_file(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held: dict[str, object] = {}

    def fake_open(**kwargs: object) -> _Store:
        assert kwargs["endpoint_url"] == "http://127.0.0.1:9"
        assert kwargs["access_key"] == ""
        assert kwargs["secret_key"] == ""
        return _Store()

    def fake_create(url: str) -> str:
        held["created"] = True
        return swap_database(url, "pgrestoredrill_" + "cd" * 16)

    def fake_restore(path: Path, target: object, timeout: float) -> None:
        held["existed"] = path.is_file() and path.read_bytes() == _PAYLOAD
        held["path"] = path
        raise RestoreFailed(1, "stopped", 0.01)

    monkeypatch.setattr("pgrestoredrill.runner.acquire.open_s3_store", fake_open)
    monkeypatch.setattr("pgrestoredrill.targets.opening.create_drill_database", fake_create)
    monkeypatch.setattr("pgrestoredrill.runner.service.restore_dump", fake_restore)
    completed = execute_drill(settings, _config(tmp_path))
    path = held["path"]
    assert isinstance(path, Path)
    assert held["created"] is True
    assert held["existed"] is True
    assert path.exists() is False
    assert completed.status == "error"
    assert completed.dump_path == "backups/new.dump"
    assert completed.dump_bytes == len(_PAYLOAD)
    assert completed.dump_sha256 == hashlib.sha256(_PAYLOAD).hexdigest()
    assert completed.run_id is not None
    with Session(engine) as session:
        run = session.get(Run, completed.run_id)
    assert run is not None
    assert run.dump_key == "backups/new.dump"
    assert run.dump_sha256 == completed.dump_sha256
    assert "127.0.0.1" not in (run.error or "")


def test_s3_read_error_is_stored_without_restoring(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_open(**kwargs: object) -> _Store:
        raise DumpSourceError("could not read the s3 dump")

    def explode(url: str) -> str:
        raise AssertionError("should not create a database")

    monkeypatch.setattr("pgrestoredrill.runner.acquire.open_s3_store", fake_open)
    monkeypatch.setattr("pgrestoredrill.targets.opening.create_drill_database", explode)
    completed = execute_drill(settings, _config(tmp_path))
    assert completed.status == "error"
    assert completed.error == "could not read the s3 dump"
    assert completed.database_name is None
    assert completed.run_id is not None
    with Session(engine) as session:
        run = session.get(Run, completed.run_id)
    assert run is not None
    assert run.status == "error"
    assert run.dump_key is None
    assert run.error == "could not read the s3 dump"


def _config(root: Path) -> Path:
    assertions = root / "assertions.yaml"
    assertions.write_text(
        yaml.safe_dump([{"name": "present", "type": "rows_gte", "sql": "SELECT 1", "expected": 1}]),
        encoding="utf-8",
    )
    config = root / "drill.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "name": "s3-drill",
                "source_kind": "s3",
                "source_uri": "backups/",
                "bucket": "drills",
                "endpoint_url": "http://127.0.0.1:9",
                "region": "us-east-1",
                "rpo_minutes": 60,
                "assertions_file": "assertions.yaml",
            }
        ),
        encoding="utf-8",
    )
    return config
