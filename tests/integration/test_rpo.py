"""Stored runs produce ok, breached, and unknown at the injected clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from pgrestoredrill.db.models import STATUS_ERROR, STATUS_PASSED, Drill, Run
from pgrestoredrill.runner.rpo import RPO_BREACHED, RPO_OK, RPO_UNKNOWN, rpo_for_drill

_NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def test_rpo_follows_the_boundary_of_the_injected_clock(engine: Engine) -> None:
    with Session(engine) as session:
        drill = Drill(
            id=uuid4(),
            name="rpo-boundary",
            source_kind="local",
            source_uri="dumps",
            rpo_minutes=60,
            assertions=[],
            enabled=True,
        )
        session.add(drill)
        session.commit()
        assert rpo_for_drill(session, drill, _NOW) == (RPO_UNKNOWN, None)
        failed = _add(session, drill, STATUS_ERROR, _NOW - timedelta(minutes=10), "boom")
        assert rpo_for_drill(session, drill, _NOW) == (RPO_BREACHED, None)
        passed = _add(session, drill, STATUS_PASSED, _NOW - timedelta(minutes=60), None)
        assert rpo_for_drill(session, drill, _NOW) == (RPO_OK, passed.id)
        passed.finished_at = _NOW - timedelta(minutes=60, microseconds=1)
        session.commit()
        assert rpo_for_drill(session, drill, _NOW) == (RPO_BREACHED, passed.id)
        assert failed.id != passed.id


def _add(
    session: Session,
    drill: Drill,
    status: str,
    finished: datetime,
    error: str | None,
) -> Run:
    run = Run(
        id=uuid4(),
        drill_id=drill.id,
        status=status,
        dump_key=None,
        dump_bytes=None,
        dump_sha256=None,
        restore_seconds=None,
        started_at=finished,
        finished_at=finished,
        error=error,
    )
    session.add(run)
    session.commit()
    return run
