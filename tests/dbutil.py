"""Create and drop databases owned by the test process."""

from __future__ import annotations

import re

import psycopg
from psycopg import sql

from pgrestoredrill.db.urls import for_libpq, swap_database
from pgrestoredrill.targets.external import is_drill_database

_SAFE_NAME = re.compile(r"^pgrestoredrill_(meta|fixture)_[0-9a-f]{32}$")


def create_database(admin_url: str, name: str) -> str:
    _require_safe_name(name)
    with psycopg.connect(for_libpq(admin_url), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return swap_database(admin_url, name)


def drop_named_database(admin_url: str, name: str) -> None:
    _require_safe_name(name)
    statement = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
    with psycopg.connect(for_libpq(admin_url), autocommit=True) as conn:
        conn.execute(statement)


def _require_safe_name(name: str) -> None:
    if is_drill_database(name) or _SAFE_NAME.fullmatch(name):
        return
    raise RuntimeError("refusing to manage an unexpected database name")
