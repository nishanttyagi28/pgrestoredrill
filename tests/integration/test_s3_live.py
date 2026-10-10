"""Download the newest object from the CI object store.

The test skips when MINIO_ENDPOINT is unset. In GitHub Actions a missing
endpoint is a failure. Unit tests never call this module's network path.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid

import boto3
import pytest

from pgrestoredrill.sources.local import LocalDump, release_dump
from pgrestoredrill.sources.s3 import download_newest_dump, open_s3_store

_OLD = b"older-dump"
_NEW = b"newer-dump"
_PREFIX = "backups/"


def test_live_store_returns_the_newest_dump_and_removes_the_temp_file() -> None:
    endpoint = _endpoint()
    access, secret = _credentials()
    bucket = "drill" + uuid.uuid4().hex
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
    )
    client.create_bucket(Bucket=bucket)
    downloaded: LocalDump | None = None
    try:
        client.put_object(Bucket=bucket, Key=_PREFIX + "z-old.dump", Body=_OLD)
        # LastModified has to beat the key: z-old.dump sorts after a-new.dump.
        time.sleep(1.1)
        client.put_object(Bucket=bucket, Key=_PREFIX + "a-new.dump", Body=_NEW)
        client.put_object(Bucket=bucket, Key=_PREFIX + "notes.txt", Body=b"notes")
        store = open_s3_store(
            endpoint_url=endpoint,
            region="us-east-1",
            access_key=access,
            secret_key=secret,
        )
        downloaded = download_newest_dump(store, bucket=bucket, prefix=_PREFIX)
        assert downloaded.key == _PREFIX + "a-new.dump"
        assert downloaded.size == len(_NEW)
        assert downloaded.sha256 == hashlib.sha256(_NEW).hexdigest()
        assert downloaded.temporary is True
        assert downloaded.path.is_file()
        assert downloaded.path.read_bytes() == _NEW
    finally:
        removed = True
        if downloaded is not None:
            path = downloaded.path
            release_dump(downloaded)
            removed = not path.exists()
        try:
            _remove_bucket(client, bucket)
        finally:
            assert removed


def _endpoint() -> str:
    value = os.environ.get("MINIO_ENDPOINT", "").strip()
    if value:
        return value
    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.fail("MINIO_ENDPOINT is required in CI")
    pytest.skip("MINIO_ENDPOINT is unset")


def _credentials() -> tuple[str, str]:
    access = os.environ.get("MINIO_ROOT_USER", "")
    secret = os.environ.get("MINIO_ROOT_PASSWORD", "")
    if not access or not secret:
        pytest.fail("object store credentials are unset")
    return access, secret


def _remove_bucket(client: object, bucket: str) -> None:
    listed = client.list_objects_v2(Bucket=bucket)
    contents = listed.get("Contents") or []
    keys = [item["Key"] for item in contents if item.get("Key")]
    if keys:
        client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in keys]},
        )
    client.delete_bucket(Bucket=bucket)
