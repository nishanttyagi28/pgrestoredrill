"""Read-only run history routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from pgrestoredrill.api.auth import require_admin
from pgrestoredrill.api.schemas import (
    AssertionResultOut,
    DrillOut,
    Health,
    RunDetail,
    RunOut,
)
from pgrestoredrill.api.state import get_state
from pgrestoredrill.db.models import AssertionResult, Drill, Run
from pgrestoredrill.db.session import connect

router = APIRouter()
_AUTH = [Depends(require_admin)]


@router.get("/healthz", response_model=Health)
def healthz() -> Health:
    return Health(status="ok")


@router.get("/readyz", response_model=Health)
def readyz(request: Request) -> Health:
    url = get_state(request.app).settings.database_url
    try:
        with connect(url, autocommit=True) as connection:
            row = connection.execute("SELECT 1").fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="metadata database is unavailable") from None
    if row is None:
        raise HTTPException(status_code=503, detail="metadata database is unavailable")
    return Health(status="ok")


@router.get("/drills", response_model=list[DrillOut], dependencies=_AUTH)
def list_drills(request: Request) -> list[DrillOut]:
    with _session(request) as session:
        rows = session.scalars(select(Drill).order_by(Drill.name)).all()
        return [DrillOut.model_validate(row) for row in rows]


@router.get("/drills/{drill_id}/runs", response_model=list[RunOut], dependencies=_AUTH)
def list_runs(
    drill_id: UUID,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[RunOut]:
    with _session(request) as session:
        if session.get(Drill, drill_id) is None:
            raise HTTPException(status_code=404, detail="drill not found")
        rows = session.scalars(
            select(Run)
            .where(Run.drill_id == drill_id)
            .order_by(Run.started_at.desc(), Run.id.desc())
            .limit(limit)
        ).all()
        return [RunOut.model_validate(row) for row in rows]


@router.get("/runs/{run_id}", response_model=RunDetail, dependencies=_AUTH)
def get_run(run_id: UUID, request: Request) -> RunDetail:
    with _session(request) as session:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        results = session.scalars(
            select(AssertionResult)
            .where(AssertionResult.run_id == run.id)
            .order_by(AssertionResult.id)
        ).all()
        base = RunOut.model_validate(run)
        return RunDetail(
            id=base.id,
            drill_id=base.drill_id,
            status=base.status,
            dump_key=base.dump_key,
            dump_bytes=base.dump_bytes,
            dump_sha256=base.dump_sha256,
            restore_seconds=base.restore_seconds,
            started_at=base.started_at,
            finished_at=base.finished_at,
            error=base.error,
            assertions=[AssertionResultOut.model_validate(item) for item in results],
        )


def _session(request: Request) -> Session:
    engine = get_state(request.app).engine
    if engine is None:
        raise HTTPException(status_code=503, detail="metadata database is unavailable")
    return Session(engine, expire_on_commit=False)
