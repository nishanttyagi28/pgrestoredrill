"""Kind cluster setup used by the smoke script."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pgrestoredrill.redact import redact

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "pgrestoredrill"


def require_tools() -> None:
    checks = (
        ("docker", ["docker", "version"]),
        ("kind", ["kind", "version"]),
        ("kubectl", ["kubectl", "version", "--client"]),
    )
    for name, command in checks:
        if subprocess.run(command, check=False, capture_output=True).returncode != 0:
            print(f"{name} is required", file=sys.stderr)
            raise SystemExit(1)


def prepare_image() -> None:
    existing = os.environ.get("PGRESTOREDRILL_IMAGE", "").strip()
    if existing:
        subprocess.run(["docker", "tag", existing, "pgrestoredrill:kind"], check=True)
        return
    subprocess.run(["docker", "build", "-t", "pgrestoredrill:kind", str(ROOT)], check=True)


def wait_workloads() -> None:
    for name in ("deploy/metadata", "deploy/silo", "deploy/pgrestoredrill-api"):
        rollout(name)
    completed = subprocess.run(
        [
            "kubectl",
            "-n",
            NAMESPACE,
            "wait",
            "--for=condition=complete",
            "job/pgrestoredrill-migrate",
            "--timeout=180s",
        ],
        check=False,
    )
    if completed.returncode != 0:
        job_logs("job/pgrestoredrill-migrate")
        raise SystemExit(1)


def rollout(name: str) -> None:
    completed = subprocess.run(
        ["kubectl", "-n", NAMESPACE, "rollout", "status", name, "--timeout=180s"],
        check=False,
    )
    if completed.returncode == 0:
        return
    subprocess.run(["kubectl", "-n", NAMESPACE, "describe", name], check=False)
    raise SystemExit(1)


def job_logs(job: str) -> None:
    result = subprocess.run(
        ["kubectl", "-n", NAMESPACE, "logs", job, "--all-containers", "--tail=80"],
        check=False,
        capture_output=True,
        text=True,
    )
    print(redact(result.stdout[-2000:]), file=sys.stderr)


@contextmanager
def port_forward(resource: str, local: int, remote: int) -> Iterator[None]:
    proc = subprocess.Popen(
        ["kubectl", "-n", NAMESPACE, "port-forward", resource, f"{local}:{remote}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("port-forward exited")
            try:
                with socket.create_connection(("127.0.0.1", local), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("port-forward did not open")
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
