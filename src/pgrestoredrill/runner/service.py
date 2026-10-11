"""Run one drill and store its history."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from pgrestoredrill.alerts.notify import notify_after_run
from pgrestoredrill.assertions.loader import load_assertions
from pgrestoredrill.assertions.models import AssertionOutcome, AssertionSpec
from pgrestoredrill.assertions.runner import run_assertions
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import (
    STATUS_ERROR,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_RUNNING,
    AssertionResult,
    Drill,
    Run,
)
from pgrestoredrill.db.session import make_engine
from pgrestoredrill.db.urls import database_name
from pgrestoredrill.errors import (
    DumpNotFound,
    DumpRejected,
    DumpSourceError,
    RestoreFailed,
    RestoreTimeout,
)
from pgrestoredrill.redact import redact
from pgrestoredrill.runner.acquire import acquire_dump
from pgrestoredrill.runner.preflight import dump_rejection
from pgrestoredrill.runner.report import CompletedRun
from pgrestoredrill.runner.restore import restore_dump
from pgrestoredrill.runner.spec import DrillFile, load_drill, resolve_from_config
from pgrestoredrill.sources.local import LocalDump, release_dump
from pgrestoredrill.targets.external import ExternalTarget, create_drill_database

log = structlog.get_logger()
_ERROR_LIMIT = 2000


def execute_drill(settings: Settings, config_path: Path) -> CompletedRun:
    spec = load_drill(config_path)
    assertions = load_assertions(resolve_from_config(config_path, spec.assertions_file))
    engine = make_engine(settings.database_url)
    try:
        with Session(engine, expire_on_commit=False) as session:
            completed = _execute(session, settings, spec, config_path, assertions)
            notify_after_run(session, settings, completed)
            return completed
    finally:
        engine.dispose()


def _execute(
    session: Session,
    settings: Settings,
    spec: DrillFile,
    config_path: Path,
    assertions: list[AssertionSpec],
) -> CompletedRun:
    drill = _upsert_drill(session, spec, assertions)
    session.commit()
    log.info("drill started", drill=spec.name, source_kind=spec.source_kind)
    if not spec.enabled:
        return _result(
            status=STATUS_ERROR,
            drill_name=spec.name,
            run_id=None,
            database=None,
            dump_path=None,
            dump_bytes=None,
            dump_sha256=None,
            restore_seconds=None,
            error="drill is disabled",
            assertions=(),
        )
    dump: LocalDump | None = None
    try:
        try:
            dump = acquire_dump(settings, spec, config_path)
        except DumpNotFound as exc:
            run = _start_run(session, drill.id, None)
            return _finish(session, run, spec.name, None, None, STATUS_ERROR, None, str(exc), ())
        except DumpRejected as exc:
            run = _start_run(session, drill.id, None)
            run.dump_key = exc.key
            run.dump_bytes = exc.size
            return _finish(session, run, spec.name, None, None, STATUS_FAILED, None, str(exc), ())
        except DumpSourceError as exc:
            run = _start_run(session, drill.id, None)
            return _finish(
                session,
                run,
                spec.name,
                None,
                None,
                STATUS_ERROR,
                None,
                _stored_error(exc),
                (),
            )
        return _restore(session, settings, spec, drill, dump, assertions)
    finally:
        if dump is not None:
            release_dump(dump)


def _restore(
    session: Session,
    settings: Settings,
    spec: DrillFile,
    drill: Drill,
    dump: LocalDump,
    assertions: list[AssertionSpec],
) -> CompletedRun:
    run = _start_run(session, drill.id, dump)
    reason = dump_rejection(
        dump,
        min_bytes=spec.min_bytes,
        max_age_minutes=spec.max_age_minutes,
        now=datetime.now(UTC),
    )
    if reason is not None:
        return _finish(session, run, spec.name, None, dump, STATUS_FAILED, None, reason, ())
    database: str | None = None
    try:
        restore_url = create_drill_database(settings.target_url)
        database = database_name(restore_url)
        outcome = restore_dump(
            dump.path,
            ExternalTarget(restore_url),
            spec.restore_timeout_seconds,
        )
        results = run_assertions(
            restore_url,
            assertions,
            statement_timeout_ms=spec.statement_timeout_ms,
        )
        status = STATUS_PASSED if all(item.passed for item in results) else STATUS_FAILED
        return _finish(
            session,
            run,
            spec.name,
            database,
            dump,
            status,
            outcome.duration_seconds,
            None,
            tuple(results),
        )
    except Exception as exc:
        seconds = exc.duration_seconds if isinstance(exc, (RestoreFailed, RestoreTimeout)) else None
        return _finish(
            session,
            run,
            spec.name,
            database,
            dump,
            STATUS_ERROR,
            seconds,
            _stored_error(exc),
            (),
        )


def _upsert_drill(session: Session, spec: DrillFile, assertions: list[AssertionSpec]) -> Drill:
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


def _start_run(session: Session, drill_id: UUID, dump: LocalDump | None) -> Run:
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


def _finish(
    session: Session,
    run: Run,
    drill_name: str,
    database: str | None,
    dump: LocalDump | None,
    status: str,
    restore_seconds: float | None,
    error: str | None,
    assertions: tuple[AssertionOutcome, ...],
) -> CompletedRun:
    run.status = status
    run.restore_seconds = restore_seconds
    run.finished_at = datetime.now(UTC)
    run.error = error
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
    return _result(
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


def _result(
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


def _stored_error(exc: Exception) -> str:
    text = redact(str(exc)).strip()
    if len(text) <= _ERROR_LIMIT:
        return text
    return text[-_ERROR_LIMIT:]
