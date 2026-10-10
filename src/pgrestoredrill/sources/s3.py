"""Newest custom-format object in an S3-compatible bucket."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_s3.client import S3Client

from pgrestoredrill.errors import DumpNotFound, DumpSourceError
from pgrestoredrill.sources.local import LocalDump

_CHUNK = 1024 * 1024
_QUIET_LOGGERS = ("boto3", "botocore", "s3transfer", "urllib3")
_CLIENT_ERRORS = (BotoCoreError, ClientError)


@dataclass(frozen=True)
class RemoteObject:
    key: str
    modified: datetime


class ObjectStore(Protocol):
    def list_dumps(self, bucket: str, prefix: str) -> tuple[RemoteObject, ...]: ...

    def open_dump(self, bucket: str, key: str) -> Iterator[bytes]: ...


class BotoStore:
    def __init__(self, client: S3Client) -> None:
        self._client = client

    def list_dumps(self, bucket: str, prefix: str) -> tuple[RemoteObject, ...]:
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            found: list[RemoteObject] = []
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for item in page.get("Contents") or []:
                    listed = _listed(item.get("Key"), item.get("LastModified"))
                    if listed is not None:
                        found.append(listed)
            return tuple(found)
        except _CLIENT_ERRORS:
            raise DumpSourceError("could not read the s3 dump") from None

    def open_dump(self, bucket: str, key: str) -> Iterator[bytes]:
        try:
            body = self._client.get_object(Bucket=bucket, Key=key)["Body"]
        except _CLIENT_ERRORS:
            raise DumpSourceError("could not read the s3 dump") from None
        try:
            while True:
                try:
                    chunk = body.read(_CHUNK)
                except _CLIENT_ERRORS:
                    raise DumpSourceError("could not read the s3 dump") from None
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()


def open_s3_store(
    *,
    endpoint_url: str | None,
    region: str | None,
    access_key: str | None,
    secret_key: str | None,
) -> ObjectStore:
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    key = access_key or None
    secret = secret_key or None
    if (key is None) != (secret is None):
        raise DumpSourceError("s3 credentials are incomplete")
    try:
        client = boto3.client(
            "s3",
            region_name=region or None,
            endpoint_url=endpoint_url or None,
            aws_access_key_id=key,
            aws_secret_access_key=secret,
        )
    except _CLIENT_ERRORS:
        raise DumpSourceError("could not read the s3 dump") from None
    return BotoStore(client)


def download_newest_dump(store: ObjectStore, *, bucket: str, prefix: str) -> LocalDump:
    dumps = [item for item in store.list_dumps(bucket, prefix) if item.key.endswith(".dump")]
    if not dumps:
        raise DumpNotFound("no custom-format dump found")
    chosen = max(dumps, key=lambda item: (_aware(item.modified), item.key))
    return _stream(store, bucket, chosen)


def _listed(key: str | None, modified: datetime | None) -> RemoteObject | None:
    if key is None or not key.endswith(".dump"):
        return None
    if not isinstance(modified, datetime):
        raise DumpSourceError("could not read the s3 dump")
    return RemoteObject(key=key, modified=_aware(modified))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _stream(store: ObjectStore, bucket: str, obj: RemoteObject) -> LocalDump:
    descriptor, name = tempfile.mkstemp(prefix="pgrestoredrill-", suffix=".dump")
    path = Path(name)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as handle:
            for chunk in store.open_dump(bucket, obj.key):
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    except Exception:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
        raise
    return LocalDump(
        path=path,
        size=size,
        sha256=digest.hexdigest(),
        modified=_aware(obj.modified),
        key=obj.key,
        temporary=True,
    )
