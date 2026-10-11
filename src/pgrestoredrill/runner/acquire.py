"""Select the dump for one drill."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pgrestoredrill.config import Settings
from pgrestoredrill.errors import DumpNotFound, DumpRejected, DumpSourceError
from pgrestoredrill.runner.preflight import dump_rejection
from pgrestoredrill.runner.spec import DrillFile, resolve_from_config
from pgrestoredrill.sources.local import LocalDump, newest_dump
from pgrestoredrill.sources.s3 import open_s3_store, select_newest_dump, stream_dump


def acquire_dump(settings: Settings, spec: DrillFile, config_path: Path) -> LocalDump:
    if spec.source_kind == "local":
        return newest_dump(resolve_from_config(config_path, spec.source_uri))
    if spec.source_kind == "s3":
        return _acquire_s3(settings, spec)
    raise DumpNotFound("no custom-format dump found")


def _acquire_s3(settings: Settings, spec: DrillFile) -> LocalDump:
    if spec.bucket is None:
        raise DumpSourceError("could not read the s3 dump")
    store = open_s3_store(
        endpoint_url=spec.endpoint_url,
        region=spec.region,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
    )
    chosen = select_newest_dump(store, bucket=spec.bucket, prefix=spec.source_uri)
    # Size and LastModified are checked before any object bytes are downloaded.
    reason = dump_rejection(
        LocalDump(
            path=Path(chosen.key),
            size=chosen.size,
            sha256="",
            modified=chosen.modified,
            key=chosen.key,
        ),
        min_bytes=spec.min_bytes,
        max_age_minutes=spec.max_age_minutes,
        now=datetime.now(UTC),
    )
    if reason is not None:
        raise DumpRejected(reason, chosen.key, chosen.size)
    return stream_dump(store, bucket=spec.bucket, obj=chosen)
