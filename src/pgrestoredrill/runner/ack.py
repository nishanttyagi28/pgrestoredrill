"""Human acknowledgement. No other code path sets these fields."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgrestoredrill.db.models import STATUS_ERROR, STATUS_FAILED, Drill, Run
from pgrestoredrill.errors import (
    AckInvalid,
    AckNotAllowed,
    AlreadyAcked,
    DrillNotFound,
    RunNotFound,
)
from pgrestoredrill.runner.rpo import rpo_for_drill

_BY_LIMIT = 200
_NOTE_LIMIT = 500


@dataclass(frozen=True)
class AckRecord:
    run_id: UUID
    by: str
    note: str
    acked_at: datetime


@dataclass(frozen=True)
class OpenFailure:
    id: UUID
    status: str
    finished_at: datetime | None
    error: str | None


@dataclass(frozen=True)
class DrillView:
    id: UUID
    name: str
    rpo_minutes: int
    rpo_status: str
    open_failures: tuple[OpenFailure, ...]


def ack_run(
    session: Session,
    run_id: UUID,
    *,
    by: str,
    note: str,
    now: datetime,
) -> AckRecord:
    actor = by.strip()
    text = note.strip()
    if actor == "" or len(actor) > _BY_LIMIT or text == "" or len(text) > _NOTE_LIMIT:
        raise AckInvalid()
    run = session.get(Run, run_id)
    if run is None:
        raise RunNotFound()
    if run.status not in {STATUS_FAILED, STATUS_ERROR}:
        raise AckNotAllowed()
    if run.acked_at is not None:
        raise AlreadyAcked()
    run.acked_by = actor
    run.acked_at = now
    run.note = text
    session.commit()
    return AckRecord(run_id=run.id, by=actor, note=text, acked_at=now)


def drill_view(session: Session, drill_id: UUID, now: datetime) -> DrillView:
    drill = session.get(Drill, drill_id)
    if drill is None:
        raise DrillNotFound()
    status, _passed_id = rpo_for_drill(session, drill, now)
    rows = session.scalars(
        select(Run)
        .where(
            Run.drill_id == drill.id,
            Run.status.in_((STATUS_FAILED, STATUS_ERROR)),
            Run.acked_at.is_(None),
        )
        .order_by(Run.finished_at.desc(), Run.id.desc())
    ).all()
    return DrillView(
        id=drill.id,
        name=drill.name,
        rpo_minutes=drill.rpo_minutes,
        rpo_status=status,
        open_failures=tuple(
            OpenFailure(
                id=row.id,
                status=row.status,
                finished_at=row.finished_at,
                error=row.error,
            )
            for row in rows
        ),
    )
