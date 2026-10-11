"""Postgres sidecar in the same pod. The drill connects over localhost."""

from __future__ import annotations

import time
from collections.abc import Callable

import psycopg

from pgrestoredrill.db.session import connect
from pgrestoredrill.db.urls import libpq_url
from pgrestoredrill.errors import TargetError
from pgrestoredrill.targets.external import create_drill_database


def prepare_sidecar(
    *,
    user: str,
    password: str,
    host: str = "127.0.0.1",
    port: int = 5432,
    attempts: int = 30,
    pause: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Create an empty drill database on the sidecar. The password is not logged."""
    if password.strip() == "":
        raise TargetError("sidecar password is required")
    try:
        admin = libpq_url(
            user=user,
            password=password,
            host=host,
            port=port,
            database="postgres",
        )
    except ValueError:
        raise TargetError("invalid sidecar address") from None
    _wait_until_ready(admin, attempts=attempts, pause=pause, sleep=sleep)
    return create_drill_database(admin)


def _wait_until_ready(
    url: str,
    *,
    attempts: int,
    pause: float,
    sleep: Callable[[float], None],
) -> None:
    for _ in range(attempts):
        try:
            with connect(url, autocommit=True) as connection:
                connection.execute("SELECT 1")
        except psycopg.Error:
            sleep(pause)
            continue
        return
    raise TargetError("sidecar postgres is not ready")
