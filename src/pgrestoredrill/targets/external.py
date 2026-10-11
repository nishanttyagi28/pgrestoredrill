"""External Postgres target. Restores only into an empty drill database."""

from __future__ import annotations

import contextlib
import re
from uuid import uuid4

import psycopg
from psycopg import sql

from pgrestoredrill.db.session import connect
from pgrestoredrill.db.urls import database_name, for_libpq, swap_database
from pgrestoredrill.errors import TargetError, TargetNotDrillDatabase, TargetNotEmpty

_DRILL_DATABASE = re.compile(r"^pgrestoredrill_[0-9a-f]{32}$")
_NONEMPTY_SQL = """
SELECT 1
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
UNION ALL
SELECT 1
FROM pg_extension
WHERE extname <> 'plpgsql'
UNION ALL
SELECT 1
FROM pg_namespace
WHERE nspname <> 'public'
  AND nspname <> 'information_schema'
  AND left(nspname, 3) <> 'pg_'
UNION ALL
SELECT 1
FROM pg_type AS t
JOIN pg_namespace AS n ON n.oid = t.typnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
UNION ALL
SELECT 1
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND p.prokind IN ('f', 'p')
UNION ALL
SELECT 1
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND p.prokind = 'a'
UNION ALL
SELECT 1 FROM pg_largeobject_metadata
UNION ALL
SELECT 1
FROM pg_collation AS c
JOIN pg_namespace AS n ON n.oid = c.collnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
UNION ALL
SELECT 1
FROM pg_operator AS o
JOIN pg_namespace AS n ON n.oid = o.oprnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
UNION ALL
SELECT 1
FROM pg_ts_config AS cfg
JOIN pg_namespace AS n ON n.oid = cfg.cfgnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
UNION ALL
SELECT 1 FROM pg_publication
UNION ALL
SELECT 1 FROM pg_foreign_data_wrapper
LIMIT 1
"""


def is_drill_database(name: str) -> bool:
    return _DRILL_DATABASE.fullmatch(name) is not None


class ExternalTarget:
    """A caller-supplied Postgres database that must already be an empty drill database."""

    def __init__(self, url: str) -> None:
        self._url = for_libpq(url)

    def assert_empty(self) -> None:
        ensure_restore_allowed(self._url)

    def restore_url(self) -> str:
        return self._url


def ensure_restore_allowed(database_url: str) -> None:
    name = database_name(database_url)
    if not is_drill_database(name):
        raise TargetNotDrillDatabase(name)
    if not _is_empty(database_url):
        raise TargetNotEmpty(name)


def create_drill_database(admin_url: str) -> str:
    name = f"pgrestoredrill_{uuid4().hex}"
    try:
        with connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except psycopg.Error:
        raise TargetError("could not create a drill database") from None
    restore_url = swap_database(admin_url, name)
    try:
        ensure_restore_allowed(restore_url)
    except Exception:
        _drop_quietly(admin_url, name)
        raise
    return restore_url


def drop_database(admin_url: str, name: str) -> None:
    if not is_drill_database(name):
        raise TargetNotDrillDatabase(name)
    try:
        with connect(admin_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
    except psycopg.Error:
        raise TargetError("could not drop a drill database") from None


def _is_empty(database_url: str) -> bool:
    try:
        with connect(database_url, autocommit=True) as conn:
            row = conn.execute(_NONEMPTY_SQL).fetchone()
    except psycopg.Error:
        raise TargetError("could not inspect the target database") from None
    return row is None


def _drop_quietly(admin_url: str, name: str) -> None:
    with contextlib.suppress(TargetError):
        drop_database(admin_url, name)
