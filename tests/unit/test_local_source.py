"""Newest custom-format dump selection."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from pgrestoredrill.errors import DumpNotFound
from pgrestoredrill.sources.local import file_sha256, newest_dump

_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_checksum_matches_file_bytes(tmp_path: Path) -> None:
    path = tmp_path / "backup.dump"
    path.write_bytes(b"abc")
    found = newest_dump(tmp_path)
    assert found.path == path
    assert found.size == 3
    assert found.sha256 == file_sha256(path)
    assert found.sha256 == hashlib.sha256(b"abc").hexdigest()
    assert found.sha256 == _ABC


def test_picks_newest_dump_and_ignores_other_files(tmp_path: Path) -> None:
    older = tmp_path / "old.dump"
    newer = tmp_path / "new.dump"
    notes = tmp_path / "notes.txt"
    nested = tmp_path / "skip.dump"
    older.write_bytes(b"old")
    newer.write_bytes(b"new")
    notes.write_bytes(b"ignore me")
    nested.mkdir()
    _set_mtime(older, 1_000)
    _set_mtime(newer, 2_000)
    _set_mtime(notes, 9_000)
    found = newest_dump(tmp_path)
    assert found.path == newer
    assert found.sha256 == hashlib.sha256(b"new").hexdigest()


def test_tie_breaks_on_file_name(tmp_path: Path) -> None:
    first = tmp_path / "a.dump"
    second = tmp_path / "b.dump"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    _set_mtime(first, 5_000)
    _set_mtime(second, 5_000)
    assert newest_dump(tmp_path).path == second


def test_missing_dump_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DumpNotFound, match="no custom-format dump"):
        newest_dump(tmp_path)
    missing = tmp_path / "missing"
    with pytest.raises(DumpNotFound, match="dump folder not found"):
        newest_dump(missing)


def _set_mtime(path: Path, when: int) -> None:
    os.utime(path, (when, when))
