"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from pgrestoredrill.config import Settings
from pgrestoredrill.db.session import make_engine
from pgrestoredrill.errors import AckInvalid, AckNotAllowed, AlreadyAcked, RunNotFound
from pgrestoredrill.logging import configure_logging
from pgrestoredrill.redact import redact
from pgrestoredrill.runner.ack import ack_run
from pgrestoredrill.runner.report import format_summary
from pgrestoredrill.runner.rpo import clock
from pgrestoredrill.runner.service import execute_drill


def main(argv: list[str] | None = None) -> None:
    sys.exit(dispatch(argv))


def dispatch(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pgrestoredrill")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="restore the newest dump and run assertions")
    run_parser.add_argument("--config", required=True, type=Path)
    ack_parser = sub.add_parser("ack", help="ack a failed or errored run")
    ack_parser.add_argument("run_id")
    ack_parser.add_argument("--by", required=True)
    ack_parser.add_argument("--note", required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        config = args.config
        if not isinstance(config, Path):
            return 2
        return _run_cli(config)
    if args.command == "ack":
        run_id = args.run_id
        by = args.by
        note = args.note
        if not isinstance(run_id, str) or not isinstance(by, str) or not isinstance(note, str):
            return 2
        return _ack_cli(run_id, by, note)
    return 2


def _run_cli(config: Path) -> int:
    try:
        settings = Settings()
    except ValidationError:
        _print_error("invalid configuration")
        return 1
    configure_logging(settings.log_level)
    try:
        completed = execute_drill(settings, config)
    except Exception as exc:
        _print_error(redact(str(exc)))
        return 1
    print(format_summary(completed))
    if completed.status == "passed":
        return 0
    return 1


def _ack_cli(run_id: str, by: str, note: str) -> int:
    try:
        parsed = UUID(run_id)
    except ValueError:
        _print_error("run not found")
        return 1
    try:
        settings = Settings()
    except ValidationError:
        _print_error("invalid configuration")
        return 1
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    try:
        with Session(engine) as session:
            record = ack_run(session, parsed, by=by, note=note, now=clock())
    except (RunNotFound, AckNotAllowed, AlreadyAcked, AckInvalid) as exc:
        _print_error(str(exc))
        return 1
    except Exception as exc:
        _print_error(redact(str(exc)))
        return 1
    finally:
        engine.dispose()
    print(f"run_id: {record.run_id}")
    print(f"acked_by: {record.by}")
    print(f"note: {record.note}")
    return 0


def _print_error(message: str) -> None:
    print("status: error")
    print(f"error: {' '.join(message.split())}")
