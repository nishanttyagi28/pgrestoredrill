"""Read the Postgres major from a custom-format dump header."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_MAGIC = b"PGDMP"
_MAJOR = re.compile(r"(\d+)")
_VERSION = re.compile(r"(\d+)\.")
_INT_SIZES = {2, 4, 8}
_MAX_TEXT = 128
_PREFIX = 4096


def version_refusal(path: Path) -> str | None:
    dump_major = read_dump_major(path)
    restore_major = pg_restore_major()
    if dump_major is None or restore_major is None or dump_major <= restore_major:
        return None
    return f"dump is from Postgres {dump_major}; this image restores {restore_major} or older"


def read_dump_major(path: Path) -> int | None:
    try:
        with path.open("rb") as handle:
            data = handle.read(_PREFIX)
    except OSError:
        return None
    return _major(data)


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


def _major(data: bytes) -> int | None:
    if len(data) < 9 or not data.startswith(_MAGIC):
        return None
    version = (data[5], data[6], data[7])
    if version < (1, 10, 0):
        return None
    int_size = data[8]
    if int_size not in _INT_SIZES:
        return None
    cursor = _Cursor(data, int_size)
    if not _skip_fixed(cursor, version):
        return None
    for _ in range(7):
        if cursor.integer() is None:
            return None
    if cursor.text() is None:
        return None
    remote = cursor.text()
    if remote is None:
        return None
    match = _MAJOR.match(remote)
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
