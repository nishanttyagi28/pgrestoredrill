"""Upload one fixture dump to an S3-compatible bucket."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Protocol

import boto3
from botocore.exceptions import ClientError

_OWNED = {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}


class _BucketClient(Protocol):
    def create_bucket(self, *, Bucket: str) -> object: ...

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> object: ...


def upload_dump(
    *,
    endpoint: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    key: str,
    path: Path,
    client: _BucketClient | None = None,
) -> None:
    """Put the dump at key. Credentials are not logged."""
    store = client or _client(endpoint, access_key, secret_key)
    _create_bucket(store, bucket)
    store.put_object(Bucket=bucket, Key=key, Body=path.read_bytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pgrestoredrill.fixtureload")
    parser.add_argument("--dump", required=True, type=Path)
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--access-key", default="")
    parser.add_argument("--secret-key", default="")
    parser.add_argument("--bucket", default="pgrestoredrill")
    parser.add_argument("--key", default="backups/sample.dump")
    args = parser.parse_args(argv)
    endpoint = _text(args.endpoint)
    access_key = _text(args.access_key)
    secret_key = _text(args.secret_key)
    dump = args.dump
    bucket = args.bucket
    key = args.key
    if (
        not isinstance(endpoint, str)
        or not isinstance(access_key, str)
        or not isinstance(secret_key, str)
        or not isinstance(dump, Path)
        or not isinstance(bucket, str)
        or not isinstance(key, str)
        or endpoint == ""
        or access_key == ""
        or secret_key == ""
    ):
        print("fixture endpoint and credentials are required", file=sys.stderr)
        return 1
    if not dump.is_file():
        print("fixture dump was not found", file=sys.stderr)
        return 1
    upload_dump(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
        key=key,
        path=dump,
    )
    return 0


def _client(endpoint: str, access_key: str, secret_key: str) -> _BucketClient:
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def _create_bucket(client: _BucketClient, bucket: str) -> None:
    try:
        client.create_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in _OWNED:
            raise


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


if __name__ == "__main__":
    raise SystemExit(main())
