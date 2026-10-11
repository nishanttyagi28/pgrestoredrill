"""RPO status derived from finished runs. It is not stored."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgrestoredrill.db.models import STATUS_PASSED, Drill, Run

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


def rpo_for_drill(session: Session, drill: Drill, now: datetime) -> tuple[str, UUID | None]:
    finished = session.scalar(
        select(Run.id).where(Run.drill_id == drill.id, Run.finished_at.is_not(None)).limit(1)
    )
    last_passed = session.scalar(
        select(Run)
        .where(
            Run.drill_id == drill.id,
            Run.status == STATUS_PASSED,
            Run.finished_at.is_not(None),
        )
        .order_by(Run.finished_at.desc(), Run.id.desc())
        .limit(1)
    )
    passed_at = None if last_passed is None else last_passed.finished_at
    status = rpo_status(
        rpo_minutes=drill.rpo_minutes,
        has_finished_run=finished is not None,
        last_passed_at=passed_at,
        now=now,
    )
    passed_id = None if last_passed is None else last_passed.id
    return status, passed_id


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
