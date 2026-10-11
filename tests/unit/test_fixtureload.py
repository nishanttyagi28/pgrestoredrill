"""Fixture upload does not print credentials."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from pgrestoredrill.fixtureload import main, upload_dump


class _Store:
    def __init__(self, *, owned: bool = False, code: str = "") -> None:
        self.owned = owned
        self.code = code
        self.objects: dict[tuple[str, str], bytes] = {}

    def create_bucket(self, *, Bucket: str) -> None:
        if self.owned or self.code:
            error = self.code or "BucketAlreadyOwnedByYou"
            raise ClientError({"Error": {"Code": error}}, "CreateBucket")

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self.objects[(Bucket, Key)] = Body


def test_upload_creates_the_bucket_and_object(tmp_path: Path) -> None:
    dump = tmp_path / "sample.dump"
    dump.write_bytes(b"dump-bytes")
    store = _Store()
    upload_dump(
        endpoint="http://silo:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket="pgrestoredrill",
        key="backups/sample.dump",
        path=dump,
        client=store,
    )
    assert store.objects[("pgrestoredrill", "backups/sample.dump")] == b"dump-bytes"


def test_existing_bucket_is_reused(tmp_path: Path) -> None:
    dump = tmp_path / "sample.dump"
    dump.write_bytes(b"dump-bytes")
    store = _Store(owned=True)
    upload_dump(
        endpoint="http://silo:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket="pgrestoredrill",
        key="backups/sample.dump",
        path=dump,
        client=store,
    )
    assert store.objects[("pgrestoredrill", "backups/sample.dump")] == b"dump-bytes"


def test_unexpected_bucket_error_is_raised(tmp_path: Path) -> None:
    dump = tmp_path / "sample.dump"
    dump.write_bytes(b"dump-bytes")
    store = _Store(code="AccessDenied")
    with pytest.raises(ClientError):
        upload_dump(
            endpoint="http://silo:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            bucket="pgrestoredrill",
            key="backups/sample.dump",
            path=dump,
            client=store,
        )


def test_main_refuses_missing_credentials(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dump = tmp_path / "sample.dump"
    dump.write_bytes(b"dump-bytes")
    code = main(["--dump", str(dump), "--endpoint", "http://silo:9000"])
    assert code == 1
    assert "minioadmin" not in capsys.readouterr().err


def test_module_invokes_main() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "pgrestoredrill.fixtureload"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
