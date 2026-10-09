"""Run assertions in read-only transactions."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg import sql

from pgrestoredrill.assertions.evaluate import judge
from pgrestoredrill.assertions.models import AssertionOutcome, AssertionSpec
from pgrestoredrill.db.session import connect


def run_assertions(
    database_url: str,
    specs: Sequence[AssertionSpec],
    *,
    statement_timeout_ms: int,
) -> list[AssertionOutcome]:
    timeout_ms = _validated_timeout(statement_timeout_ms)
    outcomes: list[AssertionOutcome] = []
    with connect(database_url, autocommit=True) as conn:
        # psycopg opens each transaction block with BEGIN READ ONLY.
        conn.set_read_only(True)
        for spec in specs:
            outcomes.append(_one(conn, spec, timeout_ms))
    return outcomes


def _one(
    conn: psycopg.Connection[tuple[Any, ...]],
    spec: AssertionSpec,
    timeout_ms: int,
) -> AssertionOutcome:
    started = time.perf_counter()
    try:
        with conn.transaction():
            conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
            cursor = conn.execute(sql.SQL(spec.sql))
            rows = cursor.fetchmany(2)
        passed, observed = _interpret(spec, rows)
    except Exception as exc:
        passed = False
        observed = _safe_error(exc)
    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    return AssertionOutcome(
        name=spec.name,
        passed=passed,
        observed=observed,
        expected=str(spec.expected),
        duration_ms=duration_ms,
    )


def _interpret(
    spec: AssertionSpec,
    rows: Sequence[tuple[Any, ...]],
) -> tuple[bool, str | None]:
    if len(rows) != 1:
        return False, f"rows={len(rows)}"
    return judge(spec, rows[0][0])


def _safe_error(exc: Exception) -> str:
    diag = getattr(exc, "diag", None)
    sqlstate = getattr(diag, "sqlstate", None) if diag is not None else None
    if isinstance(sqlstate, str) and sqlstate:
        return f"{type(exc).__name__} {sqlstate}"
    return type(exc).__name__


def _validated_timeout(timeout_ms: int) -> int:
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
        raise ValueError("statement_timeout_ms must be an integer")
    if timeout_ms < 1 or timeout_ms > 3_600_000:
        raise ValueError("statement_timeout_ms out of range")
    return timeout_ms
