"""Custom-format dump headers are read before restore."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pgrestoredrill.runner.header import pg_restore_major, read_dump_major, version_refusal

_REFUSAL = "dump is from Postgres 17; this image restores 16 or older"
_PG_DUMP = "dump was written by pg_dump 17; this image restores with pg_restore 16"
_ARCHIVE = "dump archive is 1.16; this image needs pg_restore 17 or newer"
_UNREADABLE = "dump header is unreadable"


def test_a_postgres_16_header_reports_16(tmp_path: Path) -> None:
    assert _major(tmp_path, "16.15") == 16


def test_a_postgres_17_header_reports_17(tmp_path: Path) -> None:
    assert _major(tmp_path, "17.2", archive=(1, 16, 0)) == 17
    assert _major(tmp_path, "17") == 17


def test_an_older_archive_still_reports_its_server(tmp_path: Path) -> None:
    assert _major(tmp_path, "15.8", archive=(1, 14, 0)) == 15


def test_garbage_and_short_headers_are_ignored(tmp_path: Path) -> None:
    assert read_dump_major(tmp_path / "missing.dump") is None
    folder = tmp_path / "dumps"
    folder.mkdir()
    (folder / "plain.dump").write_bytes(b"abcd")
    assert read_dump_major(folder / "plain.dump") is None
    short = bytearray(b"PGDMP")
    short.extend(bytes((1, 15, 0, 4)))
    (folder / "short.dump").write_bytes(short)
    assert read_dump_major(folder / "short.dump") is None
    bad = bytearray(_header("16.15"))
    bad[8] = 3
    (folder / "bad-int.dump").write_bytes(bad)
    assert read_dump_major(folder / "bad-int.dump") is None
    assert _major(tmp_path, "beta") is None
    assert _major(tmp_path, "16.0", archive=(1, 4, 0)) is None


def test_a_newer_dump_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write(tmp_path, "17.2")
    monkeypatch.setattr("pgrestoredrill.runner.header.pg_restore_major", lambda: 16)
    assert version_refusal(path) == _REFUSAL


def test_an_equal_or_older_dump_is_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pgrestoredrill.runner.header.pg_restore_major", lambda: 16)
    assert version_refusal(_write(tmp_path, "16.15")) is None
    assert version_refusal(_write(tmp_path, "15.8", archive=(1, 14, 0))) is None
    assert version_refusal(_write(tmp_path, "9.6", archive=(1, 4, 0))) is None


def test_server_and_pg_dump_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pgrestoredrill.runner.header.pg_restore_major", lambda: 16)
    assert version_refusal(_write(tmp_path, "16.4", dump="16.4")) is None
    newer_server = _write(tmp_path, "17.2", archive=(1, 16, 0), dump="17.5")
    assert version_refusal(newer_server) == _REFUSAL
    newer_dump = _write(tmp_path, "16.4", archive=(1, 16, 0), dump="17.2")
    assert version_refusal(newer_dump) == _PG_DUMP
    newer_archive = _write(tmp_path, "16.4", archive=(1, 16, 0), dump="16.4")
    assert version_refusal(newer_archive) == _ARCHIVE


def test_truncated_and_garbage_headers_are_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pgrestoredrill.runner.header.pg_restore_major", lambda: 16)
    garbage = tmp_path / "garbage.dump"
    garbage.write_bytes(b"this is not a dump")
    truncated = tmp_path / "truncated.dump"
    truncated.write_bytes(_header("16.4", dump="16.4")[:12])
    assert version_refusal(garbage) == _UNREADABLE
    assert version_refusal(truncated) == _UNREADABLE
    assert version_refusal(tmp_path / "missing.dump") == _UNREADABLE


def test_a_missing_restore_client_does_not_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pgrestoredrill.runner.header.pg_restore_major", lambda: None)
    assert version_refusal(_write(tmp_path, "17.2")) is None


def test_pg_restore_major_reads_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        assert args == ["pg_restore", "--version"]
        return SimpleNamespace(stdout="pg_restore (PostgreSQL) 16.15\n")

    monkeypatch.setattr("pgrestoredrill.runner.header.subprocess.run", fake_run)
    assert pg_restore_major() == 16


def test_pg_restore_major_ignores_a_missing_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        raise OSError("missing")

    monkeypatch.setattr("pgrestoredrill.runner.header.subprocess.run", fake_run)
    assert pg_restore_major() is None
    monkeypatch.setattr(
        "pgrestoredrill.runner.header.subprocess.run",
        lambda args, **kwargs: SimpleNamespace(stdout="pg_restore\n"),
    )
    assert pg_restore_major() is None


def _major(root: Path, remote: str, archive: tuple[int, int, int] = (1, 15, 0)) -> int | None:
    return read_dump_major(_write(root, remote, archive=archive))


def _write(
    root: Path,
    remote: str,
    archive: tuple[int, int, int] = (1, 15, 0),
    *,
    dump: str = "16.15",
) -> Path:
    path = root / f"{archive[1]}-{remote}-{dump}.dump"
    path.write_bytes(_header(remote, archive, dump=dump))
    return path


def _header(
    remote: str,
    archive: tuple[int, int, int] = (1, 15, 0),
    *,
    dump: str = "16.15",
) -> bytes:
    out = bytearray(b"PGDMP")
    out.extend(bytes(archive))
    int_size = 4
    out.append(int_size)
    if archive >= (1, 7, 0):
        out.append(8)
    out.append(1)
    if archive >= (1, 15, 0):
        out.append(0)
    elif archive >= (1, 4, 0):
        out.extend(_signed(0, int_size))
    if archive >= (1, 4, 0):
        for _ in range(7):
            out.extend(_signed(1, int_size))
        out.extend(_text("app", int_size))
    if archive >= (1, 10, 0):
        out.extend(_text(remote, int_size))
        out.extend(_text(dump, int_size))
    return bytes(out)


def _signed(value: int, int_size: int) -> bytes:
    sign = 1 if value < 0 else 0
    return bytes([sign]) + abs(value).to_bytes(int_size, "little")


def _text(value: str, int_size: int) -> bytes:
    raw = value.encode()
    return _signed(len(raw), int_size) + raw
