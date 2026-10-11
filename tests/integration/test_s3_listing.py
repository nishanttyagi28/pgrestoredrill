"""S3 listing checks refuse a dump before download. Streamed bytes are checked again."""

from __future__ import annotations

import hashlib
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
from pgrestoredrill.runner.report import CompletedRun
from pgrestoredrill.runner.service import execute_drill
from pgrestoredrill.sources.s3 import RemoteObject


def test_small_s3_listing_is_refused_without_a_download(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Listing(
        (
            RemoteObject(
                key="backups/small.dump",
                modified=datetime.now(UTC),
                size=3,
            ),
        )
    )
    completed = _run(settings, tmp_path, monkeypatch, store, "small-listing", min_bytes=100)
    assert store.opened == []
    assert completed.status == STATUS_FAILED
    assert completed.error == "dump is smaller than min_bytes"
    assert completed.dump_path == "backups/small.dump"
    assert completed.dump_bytes == 3
    assert completed.dump_sha256 is None
    _assert_listing_row(engine, completed.run_id, "backups/small.dump", 3)


def test_rejected_newest_listing_does_not_download_an_older_object(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Listing(
        (
            RemoteObject(
                key="backups/old.dump",
                modified=datetime.now(UTC) - timedelta(days=1),
                size=100,
            ),
            RemoteObject(key="backups/new.dump", modified=datetime.now(UTC), size=0),
        )
    )
    completed = _run(settings, tmp_path, monkeypatch, store, "newest-empty")
    assert store.opened == []
    assert completed.error == "dump is empty"
    assert completed.dump_path == "backups/new.dump"
    assert completed.dump_bytes == 0
    assert completed.dump_sha256 is None
    _assert_listing_row(engine, completed.run_id, "backups/new.dump", 0)


def test_streamed_empty_body_is_refused_and_the_temp_file_is_removed(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b""
    completed, path = _download(
        settings,
        engine,
        tmp_path,
        monkeypatch,
        name="stream-empty",
        payload=payload,
        listed_size=32,
    )
    assert completed.error == "dump is empty"
    assert completed.dump_bytes == 0
    assert completed.dump_sha256 == hashlib.sha256(payload).hexdigest()
    assert path.exists() is False


def test_streamed_short_body_is_refused_and_the_temp_file_is_removed(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"abc"
    completed, path = _download(
        settings,
        engine,
        tmp_path,
        monkeypatch,
        name="stream-short",
        payload=payload,
        listed_size=100,
        min_bytes=50,
    )
    assert completed.error == "dump is smaller than min_bytes"
    assert completed.dump_bytes == len(payload)
    assert completed.dump_bytes != 100
    assert completed.dump_sha256 == hashlib.sha256(payload).hexdigest()
    assert path.exists() is False


def _download(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    payload: bytes,
    listed_size: int,
    min_bytes: int | None = None,
) -> tuple[CompletedRun, Path]:
    obj = RemoteObject(key="backups/fresh.dump", modified=datetime.now(UTC), size=listed_size)
    store = _Listing((obj,), payload)
    held: dict[str, Path] = {}
    real = tempfile.mkstemp

    def wrapped(*args: object, **kwargs: object) -> tuple[int, str]:
        kwargs["dir"] = tmp_path
        descriptor, filename = real(*args, **kwargs)
        held["path"] = Path(filename)
        return descriptor, filename

    monkeypatch.setattr("pgrestoredrill.sources.s3.tempfile.mkstemp", wrapped)
    completed = _run(
        settings,
        tmp_path,
        monkeypatch,
        store,
        name,
        min_bytes=min_bytes,
        block_temp=False,
    )
    assert store.opened == ["backups/fresh.dump"]
    assert completed.status == STATUS_FAILED
    assert completed.database_name is None
    assert completed.restore_seconds is None
    assert completed.dump_path == "backups/fresh.dump"
    path = held["path"]
    assert path.name.startswith("pgrestoredrill-") and path.suffix == ".dump"
    assert list(tmp_path.glob("pgrestoredrill-*.dump")) == []
    _assert_failed(engine, completed.run_id)
    with Session(engine) as session:
        run = session.get(Run, completed.run_id)
    assert run is not None
    assert run.dump_bytes == completed.dump_bytes
    assert run.dump_sha256 == completed.dump_sha256
    return completed, path


def _run(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store: _Listing,
    name: str,
    *,
    min_bytes: int | None = None,
    block_temp: bool = True,
) -> CompletedRun:
    def fake_open(**kwargs: object) -> _Listing:
        return store

    def fail_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        raise AssertionError("should not create a temp file")

    def explode(url: str) -> str:
        raise AssertionError("should not create a database")

    if block_temp:
        monkeypatch.setattr("pgrestoredrill.sources.s3.tempfile.mkstemp", fail_mkstemp)
    monkeypatch.setattr("pgrestoredrill.runner.acquire.open_s3_store", fake_open)
    monkeypatch.setattr("pgrestoredrill.targets.opening.create_drill_database", explode)
    completed = execute_drill(settings, _config(tmp_path, name, min_bytes=min_bytes))
    assert completed.database_name is None
    return completed


class _Listing:
    def __init__(self, objects: tuple[RemoteObject, ...], payload: bytes = b"") -> None:
        self._objects = objects
        self._payload = payload
        self.opened: list[str] = []

    def list_dumps(self, bucket: str, prefix: str) -> tuple[RemoteObject, ...]:
        assert bucket == "drills"
        assert prefix == "backups/"
        return self._objects

    def open_dump(self, bucket: str, key: str) -> Iterator[bytes]:
        self.opened.append(key)
        yield self._payload


def _assert_listing_row(engine: Engine, run_id: object, key: str, size: int) -> None:
    _assert_failed(engine, run_id)
    with Session(engine) as session:
        run = session.get(Run, run_id)
    assert run is not None
    assert run.dump_key == key
    assert run.dump_bytes == size
    assert run.dump_sha256 is None


def _assert_failed(engine: Engine, run_id: object) -> None:
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


def _config(root: Path, name: str, *, min_bytes: int | None) -> Path:
    (root / "assertions.yaml").write_text(
        yaml.safe_dump([{"name": "present", "type": "rows_gte", "sql": "SELECT 1", "expected": 1}]),
        encoding="utf-8",
    )
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
    config = root / "drill.yaml"
    config.write_text(yaml.safe_dump(body), encoding="utf-8")
    return config
