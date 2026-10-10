"""Select the dump for one drill."""

from __future__ import annotations

from pathlib import Path

from pgrestoredrill.config import Settings
from pgrestoredrill.errors import DumpNotFound, DumpSourceError
from pgrestoredrill.runner.spec import DrillFile, resolve_from_config
from pgrestoredrill.sources.local import LocalDump, newest_dump
from pgrestoredrill.sources.s3 import download_newest_dump, open_s3_store


def acquire_dump(settings: Settings, spec: DrillFile, config_path: Path) -> LocalDump:
    if spec.source_kind == "local":
        return newest_dump(resolve_from_config(config_path, spec.source_uri))
    if spec.source_kind == "s3":
        if spec.bucket is None:
            raise DumpSourceError("could not read the s3 dump")
        store = open_s3_store(
            endpoint_url=spec.endpoint_url,
            region=spec.region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
        )
        return download_newest_dump(store, bucket=spec.bucket, prefix=spec.source_uri)
    raise DumpNotFound("no custom-format dump found")
