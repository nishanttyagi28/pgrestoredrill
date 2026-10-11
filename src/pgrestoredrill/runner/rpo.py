"""RPO status derived from finished runs. It is not stored."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

RPO_OK = "ok"
RPO_BREACHED = "breached"
RPO_UNKNOWN = "unknown"


def rpo_status(
    *,
    rpo_minutes: int,
    has_finished_run: bool,
    last_passed_at: datetime | None,
    now: datetime,
) -> str:
    if not has_finished_run:
        return RPO_UNKNOWN
    if last_passed_at is None:
        return RPO_BREACHED
    if _aware(now) - _aware(last_passed_at) > timedelta(minutes=rpo_minutes):
        return RPO_BREACHED
    return RPO_OK


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
