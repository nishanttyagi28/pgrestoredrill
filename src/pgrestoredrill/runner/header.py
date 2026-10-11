"""Read the Postgres major from a custom-format dump header."""

from __future__ import annotations

import re
import subprocess
from enum import Enum
from pathlib import Path
from typing import NamedTuple

_MAGIC = b"PGDMP"
_MAJOR = re.compile(r"(\d+)")
_VERSION = re.compile(r"(\d+)\.")
_INT_SIZES = {2, 4, 8}
_MAX_TEXT = 128
_PREFIX = 4096
_UNREADABLE = "dump header is unreadable"
_ARCHIVE_NEEDS_17 = (1, 16, 0)


class _DumpHeader(NamedTuple):
    archive: tuple[int, int, int]
    server_major: int
    dump_major: int


class _Kind(Enum):
    BAD = 1
    OLD = 2


def version_refusal(path: Path) -> str | None:
    try:
        parsed = _load(path)
    except OSError:
        return _UNREADABLE
    if parsed is _Kind.OLD:
        return None
    if parsed is _Kind.BAD:
        return _UNREADABLE
    restore_major = pg_restore_major()
    if restore_major is None:
        return None
    if parsed.server_major > restore_major:
        return (
            f"dump is from Postgres {parsed.server_major}; "
            f"this image restores {restore_major} or older"
        )
    if parsed.dump_major > restore_major:
        return (
            f"dump was written by pg_dump {parsed.dump_major}; "
            f"this image restores with pg_restore {restore_major}"
        )
    if parsed.archive >= _ARCHIVE_NEEDS_17 and restore_major < 17:
        minor = parsed.archive[1]
        return f"dump archive is 1.{minor}; this image needs pg_restore 17 or newer"
    return None


def read_dump_major(path: Path) -> int | None:
    try:
        parsed = _load(path)
    except OSError:
        return None
    if isinstance(parsed, _DumpHeader):
        return parsed.server_major
    return None


def pg_restore_major() -> int | None:
    try:
        result = subprocess.run(
            ["pg_restore", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = _VERSION.search(result.stdout)
    if match is None:
        return None
    return int(match.group(1))


def _load(path: Path) -> _DumpHeader | _Kind:
    with path.open("rb") as handle:
        data = handle.read(_PREFIX)
    return _parse(data)


def _parse(data: bytes) -> _DumpHeader | _Kind:
    if len(data) < 9 or not data.startswith(_MAGIC):
        return _Kind.BAD
    archive = (data[5], data[6], data[7])
    if archive < (1, 10, 0):
        return _Kind.OLD
    int_size = data[8]
    if int_size not in _INT_SIZES:
        return _Kind.BAD
    cursor = _Cursor(data, int_size)
    if not _skip_fixed(cursor, archive):
        return _Kind.BAD
    for _ in range(7):
        if cursor.integer() is None:
            return _Kind.BAD
    if cursor.text() is None:
        return _Kind.BAD
    server_major = _leading_major(cursor.text())
    dump_major = _leading_major(cursor.text())
    if server_major is None or dump_major is None:
        return _Kind.BAD
    return _DumpHeader(archive, server_major, dump_major)


def _leading_major(value: str | None) -> int | None:
    if value is None:
        return None
    match = _MAJOR.match(value)
    if match is None:
        return None
    return int(match.group(1))


def _skip_fixed(cursor: _Cursor, version: tuple[int, int, int]) -> bool:
    if not cursor.skip(2):
        return False
    if version >= (1, 15, 0):
        return cursor.skip(1)
    return cursor.integer() is not None


class _Cursor:
    def __init__(self, data: bytes, int_size: int) -> None:
        self._data = data
        self._int_size = int_size
        self._at = 9

    def skip(self, count: int) -> bool:
        return self._take(count) is not None

    def integer(self) -> int | None:
        sign = self._take(1)
        magnitude = self._take(self._int_size)
        if sign is None or magnitude is None:
            return None
        value = int.from_bytes(magnitude, "little")
        if sign[0]:
            return -value
        return value

    def text(self) -> str | None:
        length = self.integer()
        if length is None or length < 0 or length > _MAX_TEXT:
            return None
        raw = self._take(length)
        if raw is None:
            return None
        return raw.decode("utf-8", "replace")

    def _take(self, count: int) -> bytes | None:
        end = self._at + count
        if count < 0 or end > len(self._data):
            return None
        chunk = self._data[self._at : end]
        self._at = end
        return chunk
