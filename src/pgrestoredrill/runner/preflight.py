"""Refuse a dump before pg_restore runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pgrestoredrill.sources.local import LocalDump


def dump_rejection(
    dump: LocalDump,
    *,
    min_bytes: int | None,
    max_age_minutes: int | None,
    now: datetime,
) -> str | None:
    if dump.size == 0:
        return "dump is empty"
    if min_bytes is not None and dump.size < min_bytes:
        return "dump is smaller than min_bytes"
    if max_age_minutes is None:
        return None
    modified = _aware(dump.modified)
    if now - modified > timedelta(minutes=max_age_minutes):
        return "dump is older than max_age_minutes"
    return None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
