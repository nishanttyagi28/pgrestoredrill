"""Empty drill databases are required before pg_restore."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import Engine, inspect

from pgrestoredrill.db.urls import database_name, for_libpq
from pgrestoredrill.errors import TargetNotEmpty
from pgrestoredrill.runner.restore import restore_dump
from pgrestoredrill.targets.external import (
    ExternalTarget,
    create_drill_database,
    drop_database,
    ensure_restore_allowed,
    is_drill_database,
)


def test_history_tables_exist(engine: Engine) -> None:
    names = set(inspect(engine).get_table_names())
    assert {"drills", "runs", "assertion_results"} <= names


def test_new_drill_database_is_empty(admin_url: str) -> None:
    url = create_drill_database(admin_url)
    name = database_name(url)
    try:
        assert is_drill_database(name) is True
        ensure_restore_allowed(url)
    finally:
        drop_database(admin_url, name)


def test_non_empty_target_is_refused(admin_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    url = create_drill_database(admin_url)
    name = database_name(url)
    calls: list[object] = []

    def fake_run(*args: object, **kwargs: object) -> None:
        calls.append(args)
        raise AssertionError("pg_restore should not run")

    monkeypatch.setattr("pgrestoredrill.runner.restore.subprocess.run", fake_run)
    try:
        with psycopg.connect(for_libpq(url), autocommit=True) as conn:
            conn.execute("CREATE TABLE leak (id integer)")
        with pytest.raises(TargetNotEmpty):
            restore_dump(Path("unused.dump"), ExternalTarget(url), 30)
        assert calls == []
        with psycopg.connect(for_libpq(url), autocommit=True) as conn:
            leak = conn.execute("SELECT to_regclass('public.leak')").fetchone()
            customers = conn.execute("SELECT to_regclass('public.customers')").fetchone()
        assert leak is not None and leak[0] is not None
        assert customers is not None and customers[0] is None
    finally:
        drop_database(admin_url, name)


def test_extension_makes_target_non_empty(admin_url: str) -> None:
    _refuse_after(admin_url, _create_extension)


def test_extra_schema_makes_target_non_empty(admin_url: str) -> None:
    _refuse_after(admin_url, lambda conn: conn.execute("CREATE SCHEMA extra"))


def test_enum_type_makes_target_non_empty(admin_url: str) -> None:
    _refuse_after(admin_url, lambda conn: conn.execute("CREATE TYPE mood AS ENUM ('ok', 'bad')"))


def test_function_makes_target_non_empty(admin_url: str) -> None:
    statement = "CREATE FUNCTION drill_marker() RETURNS integer LANGUAGE sql AS 'SELECT 1'"
    _refuse_after(admin_url, lambda conn: conn.execute(statement))


def _refuse_after(admin_url: str, setup: Callable[[psycopg.Connection], object]) -> None:
    url = create_drill_database(admin_url)
    name = database_name(url)
    try:
        with psycopg.connect(for_libpq(url), autocommit=True) as conn:
            setup(conn)
        with pytest.raises(TargetNotEmpty):
            ensure_restore_allowed(url)
    finally:
        drop_database(admin_url, name)


def _create_extension(conn: psycopg.Connection) -> None:
    row = conn.execute(
        """
        SELECT name
        FROM pg_available_extensions
        WHERE name <> 'plpgsql'
        ORDER BY name
        LIMIT 1
        """
    ).fetchone()
    if row is None or not isinstance(row[0], str):
        raise AssertionError("postgres has no extension besides plpgsql")
    conn.execute(sql.SQL("CREATE EXTENSION {}").format(sql.Identifier(row[0])))
