"""Local docker target. The docker CLI is fake; these tests do not start a container."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence

import pytest

from pgrestoredrill.errors import TargetError
from pgrestoredrill.targets.docker import CommandResult, DockerTarget, _subprocess, docker_database

_PASSWORD = "s3cret-token"
_DRILL = "postgresql://127.0.0.1/pgrestoredrill_" + ("ab" * 16)


class FakeDocker:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Mapping[str, str] | None]] = []
        self.exec_codes = [0]
        self.port_stdout = "127.0.0.1:54321\n"
        self.run_code = 0

    def __call__(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        recorded = list(args)
        self.calls.append((recorded, env))
        command = recorded[1]
        if command == "run":
            return CommandResult(self.run_code, "container\n")
        if command == "port":
            return CommandResult(0, self.port_stdout)
        if command == "exec":
            code = self.exec_codes.pop(0) if self.exec_codes else 1
            return CommandResult(code, "")
        if command == "rm":
            return CommandResult(0, "")
        return CommandResult(1, "")


def test_open_starts_postgres_16_on_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def created(url: str) -> str:
        seen.append(url)
        return _DRILL

    monkeypatch.setattr("pgrestoredrill.targets.docker.create_drill_database", created)
    fake = FakeDocker()
    fake.exec_codes = [1, 0]
    slept: list[float] = []
    target = DockerTarget(
        runner=fake,
        sleep=slept.append,
        password=_PASSWORD,
        attempts=3,
        pause=0.1,
    )
    try:
        assert target.open() == _DRILL
    finally:
        target.close()
    run = next(call for call in fake.calls if call[0][1] == "run")
    assert run[0][-1] == "postgres:16"
    assert "127.0.0.1::5432" in run[0]
    assert run[1] is not None
    assert run[1]["POSTGRES_PASSWORD"] == _PASSWORD
    assert all(_PASSWORD not in arg for args, _env in fake.calls for arg in args)
    assert not any("docker.sock" in arg for args, _env in fake.calls for arg in args)
    name = run[0][run[0].index("--name") + 1]
    assert fake.calls[-1][0] == ["docker", "rm", "-f", "-v", name]
    assert seen == ["postgresql://postgres:s3cret-token@127.0.0.1:54321/postgres"]
    assert slept == [0.1]


def test_container_is_removed_when_startup_fails() -> None:
    fake = FakeDocker()
    fake.port_stdout = "0.0.0.0:54321\n"
    target = DockerTarget(runner=fake, password=_PASSWORD, attempts=1, pause=0)
    with pytest.raises(TargetError, match="could not start") as caught:
        try:
            target.open()
        finally:
            target.close()
    assert "s3cret-token" not in str(caught.value)
    assert fake.calls[-1][0][1] == "rm"
    assert all(_PASSWORD not in arg for args, _env in fake.calls for arg in args)


def test_runner_errors_hide_the_password() -> None:
    def explode(args: Sequence[str], *, env: Mapping[str, str] | None = None) -> CommandResult:
        raise OSError(f"failed with {_PASSWORD}")

    target = DockerTarget(runner=explode, password=_PASSWORD, attempts=1)
    with pytest.raises(TargetError, match="could not start") as caught:
        target.open()
    assert _PASSWORD not in str(caught.value)


def test_unready_container_is_removed() -> None:
    fake = FakeDocker()
    fake.exec_codes = []
    slept: list[float] = []
    target = DockerTarget(
        runner=fake,
        sleep=slept.append,
        password=_PASSWORD,
        attempts=2,
        pause=0.2,
    )
    with pytest.raises(TargetError, match="could not start"):
        try:
            target.open()
        finally:
            target.close()
    assert slept == [0.2, 0.2]
    assert fake.calls[-1][0][1] == "rm"


def test_kubernetes_never_calls_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    fake = FakeDocker()
    target = DockerTarget(runner=fake, password=_PASSWORD)
    with pytest.raises(TargetError, match="local only"):
        target.open()
    assert fake.calls == []


def test_unexpected_container_name_is_refused() -> None:
    with pytest.raises(TargetError, match="refusing"):
        DockerTarget(name="postgres")
    fake = FakeDocker()
    DockerTarget(runner=fake).close()
    assert fake.calls == []


def test_failed_docker_run_is_removed() -> None:
    fake = FakeDocker()
    fake.run_code = 1
    target = DockerTarget(runner=fake, password=_PASSWORD, attempts=1)
    with pytest.raises(TargetError, match="could not start"):
        try:
            target.open()
        finally:
            target.close()
    assert fake.calls[-1][0][1] == "rm"


def test_missing_port_is_removed() -> None:
    fake = FakeDocker()
    fake.port_stdout = "\n"
    target = DockerTarget(runner=fake, password=_PASSWORD, attempts=1)
    with pytest.raises(TargetError, match="could not start"):
        try:
            target.open()
        finally:
            target.close()
    assert fake.calls[-1][0][1] == "rm"


def test_port_command_failure_is_removed() -> None:
    class _PortFails(FakeDocker):
        def __call__(
            self,
            args: Sequence[str],
            *,
            env: Mapping[str, str] | None = None,
        ) -> CommandResult:
            if list(args)[1] == "port":
                self.calls.append((list(args), env))
                return CommandResult(1, "")
            return super().__call__(args, env=env)

    fake = _PortFails()
    target = DockerTarget(runner=fake, password=_PASSWORD, attempts=1)
    with pytest.raises(TargetError, match="could not start"):
        try:
            target.open()
        finally:
            target.close()
    assert fake.calls[-1][0][1] == "rm"


def test_oversized_port_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pgrestoredrill.targets.docker.create_drill_database",
        lambda url: _DRILL,
    )
    fake = FakeDocker()
    fake.port_stdout = "127.0.0.1:99999\n"
    target = DockerTarget(runner=fake, password=_PASSWORD, attempts=1)
    with pytest.raises(TargetError, match="could not start"):
        target.open()


def test_docker_database_removes_the_container(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[str] = []

    class _Stub:
        def open(self) -> str:
            return _DRILL

        def close(self) -> None:
            closed.append("closed")

    monkeypatch.setattr("pgrestoredrill.targets.docker.DockerTarget", lambda: _Stub())
    with docker_database() as url:
        assert url == _DRILL
    assert closed == ["closed"]


def test_docker_database_removes_the_container_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []

    class _Stub:
        def open(self) -> str:
            raise TargetError("could not start the docker target")

        def close(self) -> None:
            closed.append("closed")

    monkeypatch.setattr("pgrestoredrill.targets.docker.DockerTarget", lambda: _Stub())
    with pytest.raises(TargetError, match="could not start"), docker_database():
        pass
    assert closed == ["closed"]


def test_subprocess_runner_returns_stdout() -> None:
    result = _subprocess([sys.executable, "-c", "print('ready')"])
    assert result.returncode == 0
    assert result.stdout.strip() == "ready"


def test_cleanup_failure_is_swallowed() -> None:
    def explode(args: Sequence[str], *, env: Mapping[str, str] | None = None) -> CommandResult:
        raise OSError(_PASSWORD)

    target = DockerTarget(runner=explode, password=_PASSWORD, name="pgrestoredrill-" + ("ab" * 16))
    target.close()
