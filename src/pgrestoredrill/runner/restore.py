"""Run pg_restore against a database the drill created."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from pgrestoredrill.db.urls import for_libpq
from pgrestoredrill.errors import RestoreFailed, RestoreTimeout
from pgrestoredrill.redact import redact
from pgrestoredrill.targets.base import TargetProvider

_STDERR_LIMIT = 2000


@dataclass(frozen=True)
class RestoreOutcome:
    duration_seconds: float
    stderr_tail: str


def pg_restore_command(dump_path: Path, database_url: str) -> list[str]:
    return [
        "pg_restore",
        "--no-owner",
        "--no-acl",
        "--exit-on-error",
        "--dbname",
        for_libpq(database_url),
        str(dump_path),
    ]


def restore_dump(
    dump_path: Path,
    target: TargetProvider,
    timeout_seconds: float,
) -> RestoreOutcome:
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    target.assert_empty()
    command = pg_restore_command(dump_path, target.restore_url())
    return _run(command, timeout_seconds)


def _run(command: list[str], timeout_seconds: float) -> RestoreOutcome:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - started
        raw = exc.stderr
        tail = redact(_tail(raw if isinstance(raw, (bytes, str)) else None))
        raise RestoreTimeout(duration, tail) from None
    except FileNotFoundError:
        duration = time.perf_counter() - started
        raise RestoreFailed(127, "pg_restore not found", duration) from None
    duration = time.perf_counter() - started
    tail = redact(_tail(completed.stderr))
    if completed.returncode != 0:
        raise RestoreFailed(completed.returncode, tail, duration)
    return RestoreOutcome(duration_seconds=duration, stderr_tail=tail)


def _tail(data: bytes | str | None) -> str:
    if data is None:
        return ""
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    stripped = text.strip()
    if len(stripped) <= _STDERR_LIMIT:
        return stripped
    return stripped[-_STDERR_LIMIT:]
