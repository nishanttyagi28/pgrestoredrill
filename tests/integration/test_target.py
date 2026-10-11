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


def test_large_object_makes_target_non_empty(admin_url: str) -> None:
    _refuse_after(admin_url, _sql("SELECT lo_create(0)"))


def test_collation_makes_target_non_empty(admin_url: str) -> None:
    _refuse_after(admin_url, _sql('CREATE COLLATION drill_coll FROM "C"'))


def test_aggregate_makes_target_non_empty(admin_url: str) -> None:
    statement = "CREATE AGGREGATE drill_sum(integer) (sfunc = int4pl, stype = integer)"
    _refuse_after(admin_url, _sql(statement))


def test_operator_makes_target_non_empty(admin_url: str) -> None:
    statement = (
        "CREATE OPERATOR public.~== (LEFTARG = integer, RIGHTARG = integer, FUNCTION = int4eq)"
    )
    _refuse_after(admin_url, _sql(statement))


def test_text_search_config_makes_target_non_empty(admin_url: str) -> None:
    statement = "CREATE TEXT SEARCH CONFIGURATION public.drill_ts (COPY = pg_catalog.simple)"
    _refuse_after(admin_url, _sql(statement))


def test_publication_makes_target_non_empty(admin_url: str) -> None:
    _refuse_after(admin_url, _sql("CREATE PUBLICATION drill_pub FOR ALL TABLES"))


def test_foreign_data_wrapper_makes_target_non_empty(admin_url: str) -> None:
    _refuse_after(admin_url, _sql("CREATE FOREIGN DATA WRAPPER drill_fdw"))


def test_extra_schema_makes_target_non_empty(admin_url: str) -> None:
    _refuse_after(admin_url, lambda conn: conn.execute("CREATE SCHEMA extra"))


def test_enum_type_makes_target_non_empty(admin_url: str) -> None:
    _refuse_after(admin_url, lambda conn: conn.execute("CREATE TYPE mood AS ENUM ('ok', 'bad')"))


def test_function_makes_target_non_empty(admin_url: str) -> None:
    statement = "CREATE FUNCTION drill_marker() RETURNS integer LANGUAGE sql AS 'SELECT 1'"
    _refuse_after(admin_url, lambda conn: conn.execute(statement))


def _sql(statement: str) -> Callable[[psycopg.Connection], object]:
    def setup(conn: psycopg.Connection) -> object:
        return conn.execute(statement)

    return setup


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
    # file_fdw ships with Postgres 16 and 17. Members are detached and dropped
    # so the pg_extension row is the only reason the target is refused.
    conn.execute(sql.SQL("CREATE EXTENSION {}").format(sql.Identifier(_EXTENSION)))
    members = _extension_members(conn)
    if not members:
        raise AssertionError("extension has no members")
    for kind, identity in members:
        conn.execute(_alter_member(kind, identity))
    ordered = sorted(members, key=lambda item: _drop_rank(item[0]))
    for kind, identity in ordered:
        conn.execute(_drop_member(kind, identity))
    row = conn.execute(
        """
        SELECT
          (
            SELECT count(*)
            FROM pg_proc AS p
            JOIN pg_namespace AS n ON n.oid = p.pronamespace
            WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          ),
          (
            SELECT count(*)
            FROM pg_type AS t
            JOIN pg_namespace AS n ON n.oid = t.typnamespace
            WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
          )
        """
    ).fetchone()
    if row != (0, 0):
        raise AssertionError("extension left functions or types behind")
    still_there = conn.execute(
        "SELECT 1 FROM pg_extension WHERE extname = %s",
        (_EXTENSION,),
    ).fetchone()
    if still_there is None:
        raise AssertionError("extension row is missing")


def _extension_members(conn: psycopg.Connection) -> list[tuple[str, str]]:
    rows = conn.execute(
        """
        SELECT kind, identity
        FROM (
          SELECT
            (pg_identify_object(d.classid, d.objid, 0)).type AS kind,
            (pg_identify_object(d.classid, d.objid, 0)).identity AS identity
          FROM pg_depend AS d
          WHERE d.refclassid = 'pg_extension'::regclass
            AND d.refobjid = (SELECT oid FROM pg_extension WHERE extname = %s)
            AND d.deptype = 'e'
        ) AS members
        """,
        (_EXTENSION,),
    ).fetchall()
    return [(str(kind), str(identity)) for kind, identity in rows]


def _alter_member(kind: str, identity: str) -> sql.Composed:
    keyword, ident = _member_sql(kind, identity)
    return sql.SQL("ALTER EXTENSION {} DROP {} {}").format(
        sql.Identifier(_EXTENSION),
        sql.SQL(keyword),
        sql.SQL(ident),
    )


def _drop_member(kind: str, identity: str) -> sql.Composed:
    keyword, ident = _member_sql(kind, identity)
    return sql.SQL("DROP {} {}").format(sql.SQL(keyword), sql.SQL(ident))


def _member_sql(kind: str, identity: str) -> tuple[str, str]:
    keyword = _MEMBER_KIND.get(kind)
    if keyword is None or not _safe_identity(identity):
        raise AssertionError("unexpected extension member")
    return keyword, identity


def _safe_identity(identity: str) -> bool:
    if not identity:
        return False
    allowed = set("._,[]() ")
    return all(char.isalnum() or char in allowed for char in identity)


def _drop_rank(kind: str) -> int:
    try:
        return _DROP_ORDER.index(kind)
    except ValueError:
        return len(_DROP_ORDER)


_EXTENSION = "file_fdw"
_MEMBER_KIND = {
    "aggregate": "AGGREGATE",
    "collation": "COLLATION",
    "foreign-data wrapper": "FOREIGN DATA WRAPPER",
    "function": "FUNCTION",
    "operator": "OPERATOR",
    "operator class": "OPERATOR CLASS",
    "operator family": "OPERATOR FAMILY",
    "procedure": "PROCEDURE",
    "schema": "SCHEMA",
    "sequence": "SEQUENCE",
    "table": "TABLE",
    "text search configuration": "TEXT SEARCH CONFIGURATION",
    "type": "TYPE",
    "view": "VIEW",
}
_DROP_ORDER = (
    "foreign-data wrapper",
    "operator",
    "operator class",
    "operator family",
    "function",
    "aggregate",
    "procedure",
    "type",
    "table",
    "view",
    "sequence",
    "collation",
    "text search configuration",
    "schema",
)
