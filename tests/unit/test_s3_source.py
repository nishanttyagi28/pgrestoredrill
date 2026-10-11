"""S3 dump selection without a network."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from pgrestoredrill.errors import DumpNotFound, DumpSourceError
from pgrestoredrill.sources.s3 import BotoStore, RemoteObject, download_newest_dump

_NEWER = datetime(2024, 6, 1, tzinfo=UTC)
_OLDER = datetime(2020, 1, 1, tzinfo=UTC)
_PAYLOAD = b"newest-bytes"


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._payload)
        chunk = self._payload[:size]
        self._payload = self._payload[size:]
        return chunk

    def close(self) -> None:
        self.closed = True


class _Paginator:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self._pages = pages
        self.kwargs: dict[str, str] = {}

    def paginate(self, *, Bucket: str, Prefix: str) -> list[dict[str, object]]:
        self.kwargs = {"Bucket": Bucket, "Prefix": Prefix}
        return self._pages


class _Client:
    def __init__(self, pages: list[dict[str, object]], bodies: dict[str, bytes]) -> None:
        self._bodies = bodies
        self.paginator = _Paginator(pages)
        self.keys: list[str] = []
        self.body: _Body | None = None

    def get_paginator(self, name: str) -> _Paginator:
        assert name == "list_objects_v2"
        return self.paginator

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, _Body]:
        assert Bucket == "drills"
        self.keys.append(Key)
        body = _Body(self._bodies[Key])
        self.body = body
        return {"Body": body}


class _BrokenClient:
    def get_paginator(self, name: str) -> _Paginator:
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "test-secret"}},
            "ListObjectsV2",
        )


class _MemoryStore:
    def __init__(self, objects: tuple[RemoteObject, ...], bodies: dict[str, bytes]) -> None:
        self._objects = objects
        self._bodies = bodies

    def list_dumps(self, bucket: str, prefix: str) -> tuple[RemoteObject, ...]:
        assert bucket == "drills"
        assert prefix == "backups/"
        return self._objects

    def open_dump(self, bucket: str, key: str) -> Iterator[bytes]:
        yield self._bodies[key]


class _ExplodingStore:
    def list_dumps(self, bucket: str, prefix: str) -> tuple[RemoteObject, ...]:
        return (RemoteObject(key="backups/new.dump", modified=_NEWER, size=7),)

    def open_dump(self, bucket: str, key: str) -> Iterator[bytes]:
        yield b"partial"
        raise RuntimeError("boom")


class _InterruptStore:
    def list_dumps(self, bucket: str, prefix: str) -> tuple[RemoteObject, ...]:
        return (RemoteObject(key="backups/new.dump", modified=_NEWER, size=7),)

    def open_dump(self, bucket: str, key: str) -> Iterator[bytes]:
        yield b"partial"
        raise KeyboardInterrupt


def test_newest_dump_is_streamed_and_checksummed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keep_temp_files(tmp_path, monkeypatch)
    pages = [
        {
            "Contents": [
                {"Key": "backups/old.dump", "LastModified": _OLDER, "Size": 3},
                {"Key": "backups/notes.txt", "LastModified": datetime(2025, 1, 1, tzinfo=UTC)},
            ]
        },
        {"Contents": [{"Key": "backups/new.dump", "LastModified": _NEWER, "Size": len(_PAYLOAD)}]},
    ]
    client = _Client(pages, {"backups/new.dump": _PAYLOAD, "backups/old.dump": b"old"})
    dump = download_newest_dump(BotoStore(client), bucket="drills", prefix="backups/")
    try:
        assert client.paginator.kwargs == {"Bucket": "drills", "Prefix": "backups/"}
        assert client.keys == ["backups/new.dump"]
        assert dump.key == "backups/new.dump"
        assert dump.size == len(_PAYLOAD)
        assert dump.sha256 == hashlib.sha256(_PAYLOAD).hexdigest()
        assert dump.modified == _NEWER
        assert dump.temporary is True
        assert dump.path.read_bytes() == _PAYLOAD
        assert client.body is not None
        assert client.body.closed is True
    finally:
        dump.path.unlink(missing_ok=True)


def test_equal_timestamps_tie_break_on_the_key() -> None:
    store = _MemoryStore(
        (
            RemoteObject(key="backups/a.dump", modified=datetime(2024, 6, 1), size=1),
            RemoteObject(key="backups/b.dump", modified=datetime(2024, 6, 1), size=1),
        ),
        {"backups/a.dump": b"a", "backups/b.dump": b"b"},
    )
    dump = download_newest_dump(store, bucket="drills", prefix="backups/")
    try:
        assert dump.key == "backups/b.dump"
        assert dump.modified == _NEWER
        assert dump.path.read_bytes() == b"b"
    finally:
        dump.path.unlink(missing_ok=True)


def test_missing_object_is_an_error() -> None:
    store = _MemoryStore((), {})
    with pytest.raises(DumpNotFound, match="no custom-format dump"):
        download_newest_dump(store, bucket="drills", prefix="backups/")


def test_interrupted_download_deletes_the_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _keep_temp_files(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="boom"):
        download_newest_dump(_ExplodingStore(), bucket="drills", prefix="backups/")
    assert list(tmp_path.iterdir()) == []


def test_keyboard_interrupt_deletes_the_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Path] = []
    real = tempfile.mkstemp

    def wrapped(*args: object, **kwargs: object) -> tuple[int, str]:
        kwargs["dir"] = tmp_path
        descriptor, filename = real(*args, **kwargs)
        created.append(Path(filename))
        return descriptor, filename

    monkeypatch.setattr("pgrestoredrill.sources.s3.tempfile.mkstemp", wrapped)
    with pytest.raises(KeyboardInterrupt):
        download_newest_dump(_InterruptStore(), bucket="drills", prefix="backups/")
    assert created
    assert all(
        path.name.startswith("pgrestoredrill-") and path.suffix == ".dump" for path in created
    )
    assert all(path.exists() is False for path in created)
    assert list(tmp_path.glob("pgrestoredrill-*.dump")) == []


def test_a_dump_listing_needs_a_non_negative_size() -> None:
    for size in (None, -1, True, False, "12", 1.5):
        pages = [{"Contents": [{"Key": "backups/new.dump", "LastModified": _NEWER, "Size": size}]}]
        client = _Client(pages, {})
        with pytest.raises(DumpSourceError, match="could not read the s3 dump"):
            BotoStore(client).list_dumps("drills", "backups/")
        assert client.keys == []


def test_a_zero_byte_listing_is_not_a_read_error() -> None:
    pages = [{"Contents": [{"Key": "backups/empty.dump", "LastModified": _NEWER, "Size": 0}]}]
    client = _Client(pages, {})
    found = BotoStore(client).list_dumps("drills", "backups/")
    assert found == (RemoteObject(key="backups/empty.dump", modified=_NEWER, size=0),)
    assert client.keys == []


def test_client_error_hides_credentials() -> None:
    store = BotoStore(_BrokenClient())
    with pytest.raises(DumpSourceError, match="could not read the s3 dump") as caught:
        store.list_dumps("drills", "backups/")
    assert str(caught.value) == "could not read the s3 dump"
    assert "test-secret" not in str(caught.value)
    assert caught.value.__cause__ is None


def _keep_temp_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = tempfile.mkstemp

    def wrapped(*args: object, **kwargs: object) -> tuple[int, str]:
        kwargs["dir"] = tmp_path
        return real(*args, **kwargs)

    monkeypatch.setattr("pgrestoredrill.sources.s3.tempfile.mkstemp", wrapped)
