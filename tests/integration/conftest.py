"""Postgres fixtures for drill tests. Each database is created here and dropped here."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from pgrestoredrill.config import Settings
from pgrestoredrill.db.session import make_engine
from pgrestoredrill.db.urls import database_name
from pgrestoredrill.targets.external import create_drill_database, drop_database
from tests.dbutil import create_database, drop_named_database

_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def admin_url() -> str:
    return os.environ.get(
        "TARGET_URL",
        "postgresql://postgres:postgres@localhost:5432/postgres",
    )


@pytest.fixture(scope="session")
def database_url(admin_url: str) -> Iterator[str]:
    from uuid import uuid4

    name = f"pgrestoredrill_meta_{uuid4().hex}"
    url = create_database(admin_url, name)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = Config(str(_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(_ROOT / "migrations"))
        cfg.set_main_option("prepend_sys_path", str(_ROOT / "src"))
        command.upgrade(cfg, "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        drop_named_database(admin_url, name)


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    db_engine = make_engine(database_url)
    try:
        yield db_engine
    finally:
        db_engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        _delete_history(conn)


@pytest.fixture
def settings(database_url: str, admin_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        target_url=admin_url,
        log_level="INFO",
    )


@pytest.fixture
def drill_url(admin_url: str) -> Iterator[str]:
    url = create_drill_database(admin_url)
    try:
        yield url
    finally:
        drop_database(admin_url, database_name(url))


def _delete_history(conn: Connection) -> None:
    conn.execute(text("DELETE FROM alerts"))
    conn.execute(text("DELETE FROM assertion_results"))
    conn.execute(text("DELETE FROM runs"))
    conn.execute(text("DELETE FROM drills"))
