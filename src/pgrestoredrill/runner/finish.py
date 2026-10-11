"""Store the outcome of one drill run."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from pgrestoredrill.assertions.models import AssertionOutcome
from pgrestoredrill.db.models import AssertionResult, Run
from pgrestoredrill.notes.schema import FailureNote
from pgrestoredrill.redact import redact
from pgrestoredrill.runner.report import CompletedRun
from pgrestoredrill.sources.local import LocalDump

log = structlog.get_logger()
_ERROR_LIMIT = 2000


def finish_run(
    session: Session,
    run: Run,
    drill_name: str,
    database: str | None,
    dump: LocalDump | None,
    status: str,
    restore_seconds: float | None,
    error: str | None,
    assertions: tuple[AssertionOutcome, ...],
    note: FailureNote | None = None,
) -> CompletedRun:
    run.status = status
    run.restore_seconds = restore_seconds
    run.finished_at = datetime.now(UTC)
    run.error = error
    if note is not None:
        run.failure_category = note.category
        run.failure_reason = note.short_reason
        run.failure_step = note.suggested_next_step
    for item in assertions:
        session.add(
            AssertionResult(
                run_id=run.id,
                name=item.name,
                passed=item.passed,
                observed=item.observed,
                expected=item.expected,
                duration_ms=item.duration_ms,
            )
        )
    session.commit()
    log.info("drill finished", drill=drill_name, status=status)
    return completed_result(
        status=status,
        drill_name=drill_name,
        run_id=run.id,
        database=database,
        dump_path=dump.key if dump is not None else run.dump_key,
        dump_bytes=dump.size if dump is not None else run.dump_bytes,
        dump_sha256=dump.sha256 if dump is not None else run.dump_sha256,
        restore_seconds=restore_seconds,
        error=error,
        assertions=assertions,
    )


def completed_result(
    *,
    status: str,
    drill_name: str,
    run_id: UUID | None,
    database: str | None,
    dump_path: str | None,
    dump_bytes: int | None,
    dump_sha256: str | None,
    restore_seconds: float | None,
    error: str | None,
    assertions: tuple[AssertionOutcome, ...],
) -> CompletedRun:
    return CompletedRun(
        status=status,
        drill_name=drill_name,
        run_id=run_id,
        database_name=database,
        dump_path=dump_path,
        dump_bytes=dump_bytes,
        dump_sha256=dump_sha256,
        restore_seconds=restore_seconds,
        error=error,
        assertions=assertions,
    )


def stored_error(exc: Exception) -> str:
    text = redact(str(exc)).strip()
    if len(text) <= _ERROR_LIMIT:
        return text
    return text[-_ERROR_LIMIT:]
