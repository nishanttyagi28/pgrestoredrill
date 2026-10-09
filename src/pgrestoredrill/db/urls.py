"""Postgres URL helpers. These never log the URL."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit, urlunsplit

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")


def for_libpq(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url.removeprefix("postgresql+psycopg://")
    if url.startswith("postgresql://"):
        return url
    if url.startswith("postgres://"):
        return "postgresql://" + url.removeprefix("postgres://")
    raise ValueError("unsupported database url scheme")


def for_sqlalchemy(url: str) -> str:
    libpq = for_libpq(url)
    return "postgresql+psycopg://" + libpq.removeprefix("postgresql://")


def database_name(url: str) -> str:
    parts = urlsplit(for_libpq(url))
    name = unquote(parts.path.strip("/"))
    if not name or "/" in name:
        raise ValueError("database url is missing a database name")
    return name


def swap_database(url: str, database: str) -> str:
    if _IDENT.fullmatch(database) is None:
        raise ValueError("invalid database name")
    parts = urlsplit(for_libpq(url))
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, ""))
