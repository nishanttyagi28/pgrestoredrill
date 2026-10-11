"""Local throwaway Postgres container. This target is never used in Kubernetes."""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

import structlog

from pgrestoredrill.db.urls import libpq_url
from pgrestoredrill.errors import TargetError
from pgrestoredrill.targets.external import create_drill_database

log = structlog.get_logger()

_NAME = re.compile(r"^pgrestoredrill-[0-9a-f]{32}$")
_PORT = re.compile(r"^127\.0\.0\.1:(?P<port>\d+)$")
_IMAGE = "postgres:16@sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d"
_START_FAILED = "could not start the docker target"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str


class Runner(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult: ...


class DockerTarget:
    """One Postgres container for a single drill, removed when the drill finishes."""

    def __init__(
        self,
        *,
        runner: Runner | None = None,
        sleep: Callable[[float], None] = time.sleep,
        attempts: int = 30,
        pause: float = 0.5,
        name: str | None = None,
        password: str | None = None,
    ) -> None:
        if name is not None and _NAME.fullmatch(name) is None:
            raise TargetError("refusing to manage this container")
        self._runner = runner or _subprocess
        self._sleep = sleep
        self._attempts = attempts
        self._pause = pause
        self._name = name
        self._password = secrets.token_hex(24) if password is None else password

    def open(self) -> str:
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            raise TargetError("docker target is local only")
        if self._name is None:
            self._name = f"pgrestoredrill-{uuid4().hex}"
        self._start()
        port = self._published_port()
        self._wait_until_ready()
        return create_drill_database(self._admin_url(port))

    def close(self) -> None:
        name = self._name
        self._name = None
        if name is None or _NAME.fullmatch(name) is None:
            return
        try:
            self._runner(["docker", "rm", "-f", "-v", name])
        except Exception:
            log.info("docker target cleanup failed")

    def _start(self) -> None:
        name = self._require_name()
        env = dict(os.environ)
        env["POSTGRES_PASSWORD"] = self._password
        result = self._run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--label",
                "pgrestoredrill=drill",
                "-p",
                "127.0.0.1::5432",
                "-e",
                "POSTGRES_PASSWORD",
                "-e",
                "POSTGRES_USER=postgres",
                "-e",
                "POSTGRES_DB=postgres",
                _IMAGE,
            ],
            env=env,
        )
        if result.returncode != 0:
            raise TargetError(_START_FAILED)

    def _published_port(self) -> int:
        result = self._run(["docker", "port", self._require_name(), "5432/tcp"])
        if result.returncode != 0:
            raise TargetError(_START_FAILED)
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise TargetError(_START_FAILED)
        match = _PORT.fullmatch(lines[0])
        if match is None:
            raise TargetError(_START_FAILED)
        return int(match.group("port"))

    def _wait_until_ready(self) -> None:
        command = [
            "docker",
            "exec",
            self._require_name(),
            "pg_isready",
            "-U",
            "postgres",
            "-d",
            "postgres",
        ]
        for _ in range(self._attempts):
            if self._run(command).returncode == 0:
                return
            self._sleep(self._pause)
        raise TargetError(_START_FAILED)

    def _admin_url(self, port: int) -> str:
        try:
            return libpq_url(
                user="postgres",
                password=self._password,
                host="127.0.0.1",
                port=port,
                database="postgres",
            )
        except ValueError:
            raise TargetError(_START_FAILED) from None

    def _require_name(self) -> str:
        name = self._name
        if name is None or _NAME.fullmatch(name) is None:
            raise TargetError("refusing to manage this container")
        return name

    def _run(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        try:
            return self._runner(args, env=env)
        except Exception:
            raise TargetError(_START_FAILED) from None


@contextmanager
def docker_database() -> Iterator[str]:
    """Start a throwaway Postgres and remove it even when the drill fails."""
    target = DockerTarget()
    try:
        yield target.open()
    finally:
        target.close()


def _subprocess(
    args: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    completed = subprocess.run(
        list(args),
        check=False,
        capture_output=True,
        env=None if env is None else dict(env),
        text=True,
    )
    return CommandResult(returncode=completed.returncode, stdout=completed.stdout)
