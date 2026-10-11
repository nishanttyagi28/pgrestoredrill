"""Build the image, run one drill on kind, and delete the cluster afterwards."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

from kind_cluster import (
    NAMESPACE,
    job_logs,
    port_forward,
    prepare_image,
    require_tools,
    wait_workloads,
)
from kind_fixture import fixture_dump

from pgrestoredrill.fixtureload import upload_dump
from pgrestoredrill.smoke import CLUSTER, require_passed, require_smoke_cluster

ROOT = Path(__file__).resolve().parents[1]
_TOKEN = "smoke-token"


def main() -> int:
    require_smoke_cluster(CLUSTER)
    require_tools()
    prepare_image()
    subprocess.run(["kind", "delete", "cluster", "--name", CLUSTER], check=False)
    try:
        subprocess.run(["kind", "create", "cluster", "--name", CLUSTER], check=True)
        subprocess.run(
            ["kind", "load", "docker-image", "pgrestoredrill:kind", "--name", CLUSTER],
            check=True,
        )
        subprocess.run(["kubectl", "apply", "-k", overlay()], check=True)
        wait_workloads()
        upload_fixture()
        run_drill()
        assert_api()
    finally:
        subprocess.run(["kind", "delete", "cluster", "--name", CLUSTER], check=False)
    return 0


def overlay() -> str:
    return str(ROOT / "deploy" / "k8s" / "overlays" / "smoke")


def upload_fixture() -> None:
    dump = fixture_dump()
    with port_forward("svc/silo", 19000, 9000):
        upload_dump(
            endpoint="http://127.0.0.1:19000",
            access_key="minioadmin",
            secret_key="minioadmin",
            bucket="pgrestoredrill",
            key="backups/sample.dump",
            path=dump,
        )


def run_drill() -> None:
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
            job_logs("job/smoke-drill")
            raise SystemExit(1)
        time.sleep(3)
    job_logs("job/smoke-drill")
    raise SystemExit(1)


def assert_api() -> None:
    with port_forward("svc/pgrestoredrill-api", 18000, 8000):
        drills = get_json("/drills")
        if not isinstance(drills, list) or not drills or not isinstance(drills[0], dict):
            raise RuntimeError("drill did not pass")
        drill_id = drills[0].get("id")
        runs = get_json(f"/drills/{drill_id}/runs?limit=1")
        require_passed(runs)
        if not isinstance(runs, list) or not isinstance(runs[0], dict):
            raise RuntimeError("drill did not pass")
        print(f"run_id: {runs[0].get('id')}")
        print(f"status: {runs[0].get('status')}")


def get_json(path: str) -> object:
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


if __name__ == "__main__":
    raise SystemExit(main())
