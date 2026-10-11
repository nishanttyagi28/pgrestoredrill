"""Throwaway Postgres used to build the smoke fixture dump."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_IMAGE = "postgres:16@sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d"


def fixture_dump() -> Path:
    output = ROOT / "tests" / "fixtures" / "dumps" / "sample.dump"
    output.parent.mkdir(parents=True, exist_ok=True)
    url = os.environ.get("TARGET_URL", "").strip()
    name = ""
    if not url:
        name = "pgrestoredrill-smoke-fixture"
        url = start_fixture_postgres(name)
    try:
        env = os.environ.copy()
        env["TARGET_URL"] = url
        subprocess.run(
            [sys.executable, str(ROOT / "tests" / "fixtures" / "build_fixture.py")],
            check=True,
            env=env,
        )
    finally:
        if name:
            subprocess.run(["docker", "rm", "-f", "-v", name], check=False, capture_output=True)
    return output


def start_fixture_postgres(name: str) -> str:
    subprocess.run(["docker", "rm", "-f", "-v", name], check=False, capture_output=True)
    env = os.environ.copy()
    env["POSTGRES_PASSWORD"] = "postgres"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-e",
            "POSTGRES_PASSWORD",
            "-e",
            "POSTGRES_USER=postgres",
            "-e",
            "POSTGRES_DB=postgres",
            "-p",
            "127.0.0.1::5432",
            _IMAGE,
        ],
        check=True,
        env=env,
    )
    port = container_port(name)
    admin = f"postgresql://postgres:postgres@127.0.0.1:{port}/postgres"
    wait_postgres(admin)
    return admin


def container_port(name: str) -> int:
    for _ in range(30):
        result = subprocess.run(
            ["docker", "port", name, "5432/tcp"],
            check=False,
            capture_output=True,
            text=True,
        )
        line = result.stdout.strip().splitlines()
        if result.returncode == 0 and line and ":" in line[0]:
            return int(line[0].rsplit(":", 1)[1])
        time.sleep(0.5)
    raise RuntimeError("could not start the fixture database")


def wait_postgres(url: str) -> None:
    import psycopg

    for _ in range(30):
        try:
            with psycopg.connect(url, connect_timeout=3) as connection:
                connection.execute("SELECT 1")
            return
        except psycopg.Error:
            time.sleep(1)
    raise RuntimeError("could not start the fixture database")
