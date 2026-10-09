"""Connections for the metadata database and for drill targets."""

from __future__ import annotations

from typing import Any

import psycopg
from sqlalchemy import Engine, create_engine

from pgrestoredrill.db.urls import for_libpq, for_sqlalchemy


def make_engine(url: str) -> Engine:
    return create_engine(for_sqlalchemy(url), pool_pre_ping=True)


def connect(url: str, *, autocommit: bool) -> psycopg.Connection[tuple[Any, ...]]:
    return psycopg.connect(
        for_libpq(url),
        autocommit=autocommit,
        connect_timeout=10,
        prepare_threshold=None,
    )
