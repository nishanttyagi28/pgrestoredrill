"""Run pg_restore against a database the drill created."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from pgrestoredrill.db.urls import database_name, for_libpq
from pgrestoredrill.errors import RestoreFailed, RestoreTimeout
from pgrestoredrill.redact import redact
from pgrestoredrill.targets.base import TargetProvider

_STDERR_LIMIT = 2000


@dataclass(frozen=True)
class RestoreOutcome:
    duration_seconds: float
    stderr_tail: str


def pg_restore_command(dump_path: Path, database_url: str) -> tuple[list[str], dict[str, str]]:
    parts = urlsplit(for_libpq(database_url))
    command = [
        "pg_restore",
        "--no-owner",
        "--no-acl",
        "--exit-on-error",
        "--no-password",
    ]
    if parts.hostname:
        command.extend(["--host", parts.hostname])
    if parts.port is not None:
        command.extend(["--port", str(parts.port)])
    if parts.username:
        command.extend(["--username", parts.username])
    command.extend(["--dbname", database_name(database_url), str(dump_path)])
    env = os.environ.copy()
    password = _password(parts.password, parts.query)
    if password is not None:
        env["PGPASSWORD"] = password
    return command, env


def _password(userinfo: str | None, query: str) -> str | None:
    found = userinfo
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key == "password":
            found = value
    return found


def restore_dump(
    dump_path: Path,
    target: TargetProvider,
    timeout_seconds: float,
) -> RestoreOutcome:
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    target.assert_empty()
    command, env = pg_restore_command(dump_path, target.restore_url())
    return _run(command, env, timeout_seconds)


def _run(command: list[str], env: dict[str, str], timeout_seconds: float) -> RestoreOutcome:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
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
