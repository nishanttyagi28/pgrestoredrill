"""Shared setup for dump preflight integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_FAILED, AssertionResult, Run
from pgrestoredrill.runner.service import execute_drill
from pgrestoredrill.sources.s3 import RemoteObject


def refuse_s3_listing(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    key: str,
    modified: datetime,
    size: int,
    reason: str,
    min_bytes: int | None = None,
    max_age_minutes: int | None = None,
) -> None:
    store = FixedStore(key, modified, size)

    def fake_open(**kwargs: object) -> FixedStore:
        return store

    def fail_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        raise AssertionError("should not create a temp file")

    monkeypatch.setattr("pgrestoredrill.sources.s3.tempfile.mkstemp", fail_mkstemp)
    monkeypatch.setattr("pgrestoredrill.runner.acquire.open_s3_store", fake_open)
    block_restore(monkeypatch)
    completed = execute_drill(
        settings,
        s3_config(tmp_path, name, min_bytes=min_bytes, max_age_minutes=max_age_minutes),
    )
    assert store.opened is False
    assert completed.status == STATUS_FAILED
    assert completed.error == reason
    assert completed.dump_path == key
    assert completed.dump_bytes == size
    assert completed.dump_sha256 is None
    assert completed.database_name is None
    assert completed.restore_seconds is None
    assert_failed_history(engine, completed.run_id)
    with Session(engine) as session:
        run = session.get(Run, completed.run_id)
    assert run is not None
    assert run.dump_key == key
    assert run.dump_bytes == size
    assert run.dump_sha256 is None


class FixedStore:
    def __init__(self, key: str, modified: datetime, size: int) -> None:
        self._key = key
        self._modified = modified
        self._size = size
        self.opened = False

    def list_dumps(self, bucket: str, prefix: str) -> tuple[RemoteObject, ...]:
        return (RemoteObject(key=self._key, modified=self._modified, size=self._size),)

    def open_dump(self, bucket: str, key: str) -> Iterator[bytes]:
        self.opened = True
        raise AssertionError("should not download")


def block_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(url: str) -> str:
        raise AssertionError("should not create a database")

    monkeypatch.setattr("pgrestoredrill.targets.opening.create_drill_database", explode)


def assert_failed_history(engine: Engine, run_id: object) -> None:
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


def postgres_16_header() -> bytes:
    out = bytearray(b"PGDMP")
    out.extend(bytes((1, 15, 0, 4, 8, 1, 0)))
    for _ in range(7):
        out.extend(bytes((0, 1, 0, 0, 0)))
    for text in (b"app", b"16.4", b"16.4"):
        out.extend(bytes((0, len(text), 0, 0, 0)))
        out.extend(text)
    return bytes(out)


def local_config(
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
    return write_config(root, body)


def s3_config(
    root: Path,
    name: str,
    *,
    min_bytes: int | None = None,
    max_age_minutes: int | None = None,
) -> Path:
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
    if min_bytes is not None:
        body["min_bytes"] = min_bytes
    if max_age_minutes is not None:
        body["max_age_minutes"] = max_age_minutes
    return write_config(root, body)


def write_config(root: Path, body: dict[str, object]) -> Path:
    (root / "assertions.yaml").write_text(
        yaml.safe_dump([{"name": "present", "type": "rows_gte", "sql": "SELECT 1", "expected": 1}]),
        encoding="utf-8",
    )
    config = root / "drill.yaml"
    config.write_text(yaml.safe_dump(body), encoding="utf-8")
    return config
