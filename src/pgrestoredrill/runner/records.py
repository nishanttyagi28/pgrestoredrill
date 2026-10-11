"""Persist a drill row and open a running history row."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgrestoredrill.assertions.models import AssertionSpec
from pgrestoredrill.db.models import STATUS_RUNNING, Drill, Run
from pgrestoredrill.runner.spec import DrillFile
from pgrestoredrill.sources.local import LocalDump


def upsert_drill(session: Session, spec: DrillFile, assertions: list[AssertionSpec]) -> Drill:
    payload = [item.model_dump(by_alias=True) for item in assertions]
    drill = session.scalar(select(Drill).where(Drill.name == spec.name))
    if drill is None:
        drill = Drill(
            id=uuid4(),
            name=spec.name,
            source_kind=spec.source_kind,
            source_uri=spec.source_uri,
            rpo_minutes=spec.rpo_minutes,
            assertions=payload,
            enabled=spec.enabled,
        )
        session.add(drill)
        return drill
    drill.source_kind = spec.source_kind
    drill.source_uri = spec.source_uri
    drill.rpo_minutes = spec.rpo_minutes
    drill.assertions = payload
    drill.enabled = spec.enabled
    return drill


def start_run(session: Session, drill_id: UUID, dump: LocalDump | None) -> Run:
    run = Run(
        id=uuid4(),
        drill_id=drill_id,
        status=STATUS_RUNNING,
        dump_key=None if dump is None else dump.key,
        dump_bytes=None if dump is None else dump.size,
        dump_sha256=None if dump is None else dump.sha256,
        restore_seconds=None,
        started_at=datetime.now(UTC),
        finished_at=None,
        error=None,
    )
    session.add(run)
    session.commit()
    return run
