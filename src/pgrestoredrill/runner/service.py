"""Run one drill and store its history."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy.orm import Session

from pgrestoredrill.alerts.notify import notify_after_run
from pgrestoredrill.assertions.loader import load_assertions
from pgrestoredrill.assertions.models import AssertionSpec
from pgrestoredrill.assertions.runner import run_assertions
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_ERROR, STATUS_FAILED, STATUS_PASSED, Drill
from pgrestoredrill.db.session import make_engine
from pgrestoredrill.db.urls import database_name
from pgrestoredrill.errors import (
    DumpNotFound,
    DumpRejected,
    DumpSourceError,
    RestoreFailed,
    RestoreTimeout,
)
from pgrestoredrill.runner.acquire import acquire_dump
from pgrestoredrill.runner.finish import completed_result, finish_run, stored_error
from pgrestoredrill.runner.preflight import dump_rejection
from pgrestoredrill.runner.records import start_run, upsert_drill
from pgrestoredrill.runner.report import CompletedRun
from pgrestoredrill.runner.restore import restore_dump
from pgrestoredrill.runner.spec import DrillFile, load_drill, resolve_from_config
from pgrestoredrill.sources.local import LocalDump, release_dump
from pgrestoredrill.targets.external import ExternalTarget
from pgrestoredrill.targets.opening import open_restore_url

log = structlog.get_logger()


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
    drill = upsert_drill(session, spec, assertions)
    session.commit()
    log.info("drill started", drill=spec.name, source_kind=spec.source_kind)
    if not spec.enabled:
        return completed_result(
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
            run = start_run(session, drill.id, None)
            return finish_run(session, run, spec.name, None, None, STATUS_ERROR, None, str(exc), ())
        except DumpRejected as exc:
            run = start_run(session, drill.id, None)
            run.dump_key = exc.key
            run.dump_bytes = exc.size
            return finish_run(
                session, run, spec.name, None, None, STATUS_FAILED, None, str(exc), ()
            )
        except DumpSourceError as exc:
            run = start_run(session, drill.id, None)
            return finish_run(
                session,
                run,
                spec.name,
                None,
                None,
                STATUS_ERROR,
                None,
                stored_error(exc),
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
    run = start_run(session, drill.id, dump)
    reason = dump_rejection(
        dump,
        min_bytes=spec.min_bytes,
        max_age_minutes=spec.max_age_minutes,
        now=datetime.now(UTC),
    )
    if reason is not None:
        return finish_run(session, run, spec.name, None, dump, STATUS_FAILED, None, reason, ())
    database: str | None = None
    try:
        with open_restore_url(settings) as restore_url:
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
            return finish_run(
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
        return finish_run(
            session,
            run,
            spec.name,
            database,
            dump,
            STATUS_ERROR,
            seconds,
            stored_error(exc),
            (),
        )
