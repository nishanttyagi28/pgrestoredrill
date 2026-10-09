"""pg_restore command, timeout, and the empty-target guard."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pgrestoredrill.errors import RestoreFailed, RestoreTimeout, TargetNotEmpty
from pgrestoredrill.runner.restore import restore_dump

_URL = "postgresql+psycopg://user:secret@localhost:5432/pgrestoredrill_" + ("ab" * 16)


class Allow:
    def __init__(self) -> None:
        self.checks = 0

    def assert_empty(self) -> None:
        self.checks += 1

    def restore_url(self) -> str:
        return _URL


class QueryPassword:
    def assert_empty(self) -> None:
        return None

    def restore_url(self) -> str:
        name = "pgrestoredrill_" + ("ab" * 16)
        return f"postgresql://user@localhost/{name}?password=secret"


class Refuse:
    def assert_empty(self) -> None:
        raise TargetNotEmpty("pgrestoredrill_" + ("ab" * 16))

    def restore_url(self) -> str:
        raise AssertionError("restore url should not be read")


def test_password_is_only_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGRESTOREDRILL_MARKER", "kept")
    seen: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["command"] = command
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("pgrestoredrill.runner.restore.subprocess.run", fake_run)
    restore_dump(Path("backup.dump"), Allow(), 5)
    command = seen["command"]
    assert isinstance(command, list)
    assert all("secret" not in str(part) for part in command)
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["PGPASSWORD"] == "secret"
    assert env["PGRESTOREDRILL_MARKER"] == "kept"
    assert command[command.index("--host") + 1] == "localhost"
    assert command[command.index("--port") + 1] == "5432"
    assert command[command.index("--username") + 1] == "user"
    assert command[command.index("--dbname") + 1] == "pgrestoredrill_" + ("ab" * 16)
    restore_dump(Path("backup.dump"), QueryPassword(), 5)
    query_command = seen["command"]
    assert isinstance(query_command, list)
    assert all("secret" not in str(part) for part in query_command)
    query_env = seen["env"]
    assert isinstance(query_env, dict)
    assert query_env["PGPASSWORD"] == "secret"


def test_restore_command_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["command"] = command
        seen["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("pgrestoredrill.runner.restore.subprocess.run", fake_run)
    target = Allow()
    outcome = restore_dump(Path("backup.dump"), target, 12)
    command = seen["command"]
    assert isinstance(command, list)
    assert command[:4] == ["pg_restore", "--no-owner", "--no-acl", "--exit-on-error"]
    assert "--dbname" in command
    assert all(not str(part).startswith("postgresql+psycopg://") for part in command)
    assert seen["timeout"] == 12
    assert target.checks == 1
    assert outcome.duration_seconds >= 0


def test_restore_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=0.2,
            stderr=b"still working\npassword=secret",
        )

    monkeypatch.setattr("pgrestoredrill.runner.restore.subprocess.run", fake_run)
    with pytest.raises(RestoreTimeout) as caught:
        restore_dump(Path("backup.dump"), Allow(), 0.2)
    assert "secret" not in str(caught.value)
    assert caught.value.stderr_tail == "still working\npassword=***"
    assert caught.value.duration_seconds >= 0


def test_restore_failure_redacts_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 1, b"", b"boom password=secret")

    monkeypatch.setattr("pgrestoredrill.runner.restore.subprocess.run", fake_run)
    with pytest.raises(RestoreFailed) as caught:
        restore_dump(Path("backup.dump"), Allow(), 5)
    assert caught.value.returncode == 1
    assert "secret" not in str(caught.value)
    assert "***" in caught.value.stderr_tail


def test_missing_pg_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError

    monkeypatch.setattr("pgrestoredrill.runner.restore.subprocess.run", fake_run)
    with pytest.raises(RestoreFailed, match="not found") as caught:
        restore_dump(Path("backup.dump"), Allow(), 5)
    assert caught.value.returncode == 127


def test_non_empty_target_does_not_call_pg_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise AssertionError("pg_restore should not run")

    monkeypatch.setattr("pgrestoredrill.runner.restore.subprocess.run", fake_run)
    with pytest.raises(TargetNotEmpty):
        restore_dump(Path("backup.dump"), Refuse(), 30)


def test_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="timeout"):
        restore_dump(Path("backup.dump"), Refuse(), 0)


def test_stderr_tail_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 1, b"", b"x" * 5000)

    monkeypatch.setattr("pgrestoredrill.runner.restore.subprocess.run", fake_run)
    with pytest.raises(RestoreFailed) as caught:
        restore_dump(Path("backup.dump"), Allow(), 5)
    assert len(caught.value.stderr_tail) == 2000
