"""Build the image, run one drill on kind, and delete the cluster afterwards."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pgrestoredrill.fixtureload import upload_dump
from pgrestoredrill.redact import redact
from pgrestoredrill.smoke import CLUSTER, require_passed, require_smoke_cluster

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "pgrestoredrill"
_TOKEN = "smoke-token"


def main() -> int:
    require_smoke_cluster(CLUSTER)
    _tools()
    _image()
    subprocess.run(["kind", "delete", "cluster", "--name", CLUSTER], check=False)
    try:
        subprocess.run(["kind", "create", "cluster", "--name", CLUSTER], check=True)
        subprocess.run(
            ["kind", "load", "docker-image", "pgrestoredrill:kind", "--name", CLUSTER],
            check=True,
        )
        subprocess.run(
            ["kubectl", "apply", "-k", str(ROOT / "deploy" / "k8s" / "overlays" / "smoke")],
            check=True,
        )
        _wait_workloads()
        _upload_fixture()
        _run_drill()
        _assert_api()
    finally:
        subprocess.run(["kind", "delete", "cluster", "--name", CLUSTER], check=False)
    return 0


def _tools() -> None:
    checks = (
        ("docker", ["docker", "version"]),
        ("kind", ["kind", "version"]),
        ("kubectl", ["kubectl", "version", "--client"]),
    )
    for name, command in checks:
        if subprocess.run(command, check=False, capture_output=True).returncode != 0:
            print(f"{name} is required", file=sys.stderr)
            raise SystemExit(1)


def _image() -> None:
    existing = os.environ.get("PGRESTOREDRILL_IMAGE", "").strip()
    if existing:
        subprocess.run(["docker", "tag", existing, "pgrestoredrill:kind"], check=True)
        return
    subprocess.run(["docker", "build", "-t", "pgrestoredrill:kind", str(ROOT)], check=True)


def _wait_workloads() -> None:
    for name in ("deploy/metadata", "deploy/silo", "deploy/pgrestoredrill-api"):
        subprocess.run(
            ["kubectl", "-n", NAMESPACE, "rollout", "status", name, "--timeout=180s"],
            check=True,
        )
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
        _job_logs("job/pgrestoredrill-migrate")
        raise SystemExit(1)


def _upload_fixture() -> None:
    dump = _fixture_dump()
    with _forward("svc/silo", 19000, 9000):
        upload_dump(
            endpoint="http://127.0.0.1:19000",
            access_key="minioadmin",
            secret_key="minioadmin",
            bucket="pgrestoredrill",
            key="backups/sample.dump",
            path=dump,
        )


def _fixture_dump() -> Path:
    output = ROOT / "tests" / "fixtures" / "dumps" / "sample.dump"
    output.parent.mkdir(parents=True, exist_ok=True)
    url = os.environ.get("TARGET_URL", "").strip()
    name = ""
    if not url:
        name = "pgrestoredrill-smoke-fixture"
        url = _start_fixture_postgres(name)
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


def _start_fixture_postgres(name: str) -> str:
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
            "postgres:16",
        ],
        check=True,
        env=env,
    )
    port = _container_port(name)
    admin = f"postgresql://postgres:postgres@127.0.0.1:{port}/postgres"
    _wait_postgres(admin)
    return admin


def _container_port(name: str) -> int:
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


def _wait_postgres(url: str) -> None:
    import psycopg

    for _ in range(30):
        try:
            with psycopg.connect(url, connect_timeout=3) as connection:
                connection.execute("SELECT 1")
            return
        except psycopg.Error:
            time.sleep(1)
    raise RuntimeError("could not start the fixture database")


def _run_drill() -> None:
    subprocess.run(
        ["kubectl", "-n", NAMESPACE, "delete", "job", "smoke-drill", "--ignore-not-found"],
        check=True,
    )
    subprocess.run(
        [
            "kubectl",
            "-n",
            NAMESPACE,
            "create",
            "job",
            "smoke-drill",
            "--from=cronjob/pgrestoredrill-drill",
        ],
        check=True,
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        result = subprocess.run(
            ["kubectl", "-n", NAMESPACE, "get", "job", "smoke-drill", "-o", "json"],
            check=True,
            capture_output=True,
            text=True,
        )
        status = json.loads(result.stdout).get("status", {})
        if status.get("succeeded", 0) >= 1:
            return
        if status.get("failed", 0) >= 1:
            _job_logs("job/smoke-drill")
            raise SystemExit(1)
        time.sleep(3)
    _job_logs("job/smoke-drill")
    raise SystemExit(1)


def _assert_api() -> None:
    with _forward("svc/pgrestoredrill-api", 18000, 8000):
        drills = _get("/drills")
        if not isinstance(drills, list) or not drills or not isinstance(drills[0], dict):
            raise RuntimeError("drill did not pass")
        drill_id = drills[0].get("id")
        require_passed(_get(f"/drills/{drill_id}/runs?limit=1"))


def _get(path: str) -> object:
    request = urllib.request.Request(
        f"http://127.0.0.1:18000{path}",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read()
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, (dict, list)):
        raise RuntimeError("drill did not pass")
    return parsed


def _job_logs(job: str) -> None:
    result = subprocess.run(
        ["kubectl", "-n", NAMESPACE, "logs", job, "--all-containers", "--tail=80"],
        check=False,
        capture_output=True,
        text=True,
    )
    print(redact(result.stdout[-2000:]), file=sys.stderr)


@contextmanager
def _forward(resource: str, local: int, remote: int) -> Iterator[None]:
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


if __name__ == "__main__":
    raise SystemExit(main())
