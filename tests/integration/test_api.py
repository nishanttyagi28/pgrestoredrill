"""Run history API against the metadata database."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from pgrestoredrill.api.app import create_app
from pgrestoredrill.cli import dispatch
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import Run
from pgrestoredrill.targets.external import drop_database, is_drill_database
from tests.fixtures.build_fixture import build_dump

_TOKEN = "test-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def test_authorized_reads_and_readiness(settings: Settings) -> None:
    with _client(settings) as client:
        open_health = client.get("/healthz")
        ready = client.get("/readyz")
        drills = client.get("/drills", headers=_AUTH)
        missing_drill = client.get(f"/drills/{uuid4()}/runs", headers=_AUTH)
        missing_run = client.get(f"/runs/{uuid4()}", headers=_AUTH)
    assert open_health.status_code == 200
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok"}
    assert drills.status_code == 200
    assert drills.json() == []
    assert missing_drill.status_code == 404
    assert missing_run.status_code == 404
    assert "postgres:postgres" not in ready.text


def test_readyz_fails_when_the_metadata_database_is_down(settings: Settings) -> None:
    offline = settings.model_copy(
        update={"database_url": "postgresql://postgres:postgres@127.0.0.1:1/postgres"}
    )
    with _client(offline) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["detail"] == "metadata database is unavailable"
    assert "postgres:postgres" not in response.text
    assert "127.0.0.1" not in response.text


def test_cli_run_is_listed_with_assertion_results(
    settings: Settings,
    admin_url: str,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dump = build_dump(admin_url, tmp_path / "sample.dump")
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("TARGET_URL", settings.target_url)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    code = dispatch(["run", "--config", str(_config(tmp_path, dump.parent))])
    output = capsys.readouterr().out
    try:
        assert code == 0
        with _client(settings) as client:
            drills = client.get("/drills", headers=_AUTH)
            assert drills.status_code == 200
            listed = drills.json()
            assert [item["name"] for item in listed] == ["api-history"]
            drill_id = listed[0]["id"]
            _insert_older_run(engine, drill_id)
            runs = client.get(f"/drills/{drill_id}/runs", headers=_AUTH)
            newest = client.get(f"/drills/{drill_id}/runs?limit=1", headers=_AUTH)
            assert runs.status_code == 200
            body = runs.json()
            assert [item["status"] for item in body] == ["passed", "error"]
            assert newest.json()[0]["id"] == body[0]["id"]
            detail = client.get(f"/runs/{body[0]['id']}", headers=_AUTH)
            assert detail.status_code == 200
            payload = detail.json()
            assert payload["status"] == "passed"
            assert payload["dump_sha256"]
            assert [item["name"] for item in payload["assertions"]] == [
                "customers_present",
                "first_email",
            ]
            assert [item["passed"] for item in payload["assertions"]] == [True, True]
            assert "postgres:postgres" not in detail.text
    finally:
        _drop_printed(admin_url, output)


def _client(settings: Settings) -> TestClient:
    app = create_app(settings.model_copy(update={"admin_token": _TOKEN}))
    return TestClient(app)


def _insert_older_run(engine: Engine, drill_id: str) -> None:
    with Session(engine) as session:
        session.add(
            Run(
                id=uuid4(),
                drill_id=UUID(drill_id),
                status="error",
                dump_key=None,
                dump_bytes=None,
                dump_sha256=None,
                restore_seconds=None,
                started_at=datetime(2020, 1, 1, tzinfo=UTC),
                finished_at=datetime(2020, 1, 1, tzinfo=UTC),
                error="older",
            )
        )
        session.commit()


def _config(root: Path, source: Path) -> Path:
    assertions = [
        {
            "name": "customers_present",
            "type": "rows_gte",
            "sql": "SELECT count(*) FROM customers",
            "expected": 2,
        },
        {
            "name": "first_email",
            "type": "equals",
            "sql": "SELECT email FROM customers WHERE id = 1",
            "expected": "a@example.com",
        },
    ]
    (root / "assertions.yaml").write_text(yaml.safe_dump(assertions), encoding="utf-8")
    config = root / "drill.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "name": "api-history",
                "source_kind": "local",
                "source_uri": source.as_posix(),
                "rpo_minutes": 60,
                "assertions_file": "assertions.yaml",
            }
        ),
        encoding="utf-8",
    )
    return config


def _drop_printed(admin_url: str, output: str) -> None:
    for name in re.findall(r"^database: (\S+)$", output, re.MULTILINE):
        if is_drill_database(name):
            drop_database(admin_url, name)
