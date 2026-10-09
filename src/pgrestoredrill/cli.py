"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from pgrestoredrill.config import Settings
from pgrestoredrill.logging import configure_logging
from pgrestoredrill.redact import redact
from pgrestoredrill.runner.report import format_summary
from pgrestoredrill.runner.service import execute_drill


def main(argv: list[str] | None = None) -> None:
    sys.exit(dispatch(argv))


def dispatch(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pgrestoredrill")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="restore the newest dump and run assertions")
    run_parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command != "run":
        return 2
    config = args.config
    if not isinstance(config, Path):
        return 2
    return _run_cli(config)


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


def _print_error(message: str) -> None:
    print("status: error")
    print(f"error: {' '.join(message.split())}")
