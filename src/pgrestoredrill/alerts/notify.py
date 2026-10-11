"""Send each failure once. A delivery error does not change the run."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pgrestoredrill.alerts.webhook import deliver
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_ERROR, STATUS_FAILED, Alert, Drill, Run
from pgrestoredrill.runner.report import CompletedRun
from pgrestoredrill.runner.rpo import RPO_BREACHED, rpo_for_drill

log = structlog.get_logger()


def notify_after_run(session: Session, settings: Settings, completed: CompletedRun) -> None:
    url = settings.alert_webhook_url
    if completed.run_id is None or url == "":
        return
    try:
        _dispatch(session, url, completed.run_id, datetime.now(UTC))
    except Exception:
        log.info("alert delivery failed")


def _dispatch(session: Session, url: str, run_id: UUID, now: datetime) -> None:
    run = session.get(Run, run_id)
    if run is None:
        return
    drill = session.get(Drill, run.drill_id)
    if drill is None:
        return
    if run.status in {STATUS_FAILED, STATUS_ERROR}:
        _once(
            session,
            url,
            dedup_key=f"run:{run.id}",
            drill_id=drill.id,
            run_id=run.id,
            drill_name=drill.name,
            status=run.status,
            reason=run.error or "run failed",
            now=now,
        )
    status, passed_id = rpo_for_drill(session, drill, now)
    if status != RPO_BREACHED:
        return
    marker = "none" if passed_id is None else str(passed_id)
    _once(
        session,
        url,
        dedup_key=f"rpo:{drill.id}:{marker}",
        drill_id=drill.id,
        run_id=run.id,
        drill_name=drill.name,
        status=RPO_BREACHED,
        reason="drill is outside its rpo",
        now=now,
    )


def _once(
    session: Session,
    url: str,
    *,
    dedup_key: str,
    drill_id: UUID,
    run_id: UUID,
    drill_name: str,
    status: str,
    reason: str,
    now: datetime,
) -> None:
    existing = session.scalar(select(Alert.id).where(Alert.dedup_key == dedup_key))
    if existing is not None:
        return
    code = deliver(
        url,
        {"drill": drill_name, "status": status, "reason": reason, "run_id": str(run_id)},
    )
    session.add(
        Alert(
            drill_id=drill_id,
            run_id=run_id,
            dedup_key=dedup_key,
            status=status,
            reason=reason,
            sent_at=now,
            response_status=code,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
