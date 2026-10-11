"""A person acks a failed run. The program never acks one itself."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from pgrestoredrill.api.app import create_app
from pgrestoredrill.cli import dispatch
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_ERROR, STATUS_FAILED, STATUS_PASSED, Drill, Run

_TOKEN = "test-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def test_ack_closes_the_failure_and_leaves_rpo_breached(
    settings: Settings,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("pgrestoredrill.api.routes.clock", lambda: _NOW)
    monkeypatch.setattr("pgrestoredrill.cli.clock", lambda: _NOW)
    drill_id, failed_id, passed_id, errored_id = _seed(engine)
    app = create_app(settings.model_copy(update={"admin_token": _TOKEN}))
    with TestClient(app) as client:
        missing_token = client.post(
            f"/runs/{failed_id}/ack",
            json={"by": "Ada", "note": "checked"},
        )
        missing_run = client.post(
            f"/runs/{uuid4()}/ack",
            headers=_AUTH,
            json={"by": "Ada", "note": "checked"},
        )
        passed = client.post(
            f"/runs/{passed_id}/ack",
            headers=_AUTH,
            json={"by": "Ada", "note": "checked"},
        )
        before = client.get(f"/drills/{drill_id}", headers=_AUTH)
        acked = client.post(
            f"/runs/{failed_id}/ack",
            headers=_AUTH,
            json={"by": " Ada ", "note": " checked the rows "},
        )
        again = client.post(
            f"/runs/{failed_id}/ack",
            headers=_AUTH,
            json={"by": "Ada", "note": "again"},
        )
    assert missing_token.status_code == 401
    assert "test-token" not in missing_token.text
    assert missing_run.status_code == 404
    assert passed.status_code == 400
    assert passed.json()["detail"] == "only a failed or error run can be acked"
    assert before.json()["rpo_status"] == "breached"
    assert [item["id"] for item in before.json()["open_failures"]] == [errored_id, failed_id]
    assert acked.status_code == 200
    assert acked.json()["acked_by"] == "Ada"
    assert acked.json()["note"] == "checked the rows"
    assert again.status_code == 409
    _env(monkeypatch, settings)
    assert dispatch(["ack", errored_id, "--by", "Bea", "--note", "looked at the log"]) == 0
    assert dispatch(["ack", errored_id, "--by", "Bea", "--note", "again"]) == 1
    output = capsys.readouterr().out
    assert "acked_by: Bea" in output
    assert "already acked" in output
    with TestClient(app) as client:
        after = client.get(f"/drills/{drill_id}", headers=_AUTH)
    assert after.json()["rpo_status"] == "breached"
    assert after.json()["open_failures"] == []
    with Session(engine) as session:
        untouched = session.get(Run, UUID(passed_id))
    assert untouched is not None
    assert untouched.acked_at is None


def test_rpo_on_the_drill_route_uses_the_injected_clock(
    settings: Settings,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pgrestoredrill.api.routes.clock", lambda: _NOW)
    drill_id = _drill(engine, "rpo-route")
    with Session(engine) as session:
        _run(session, UUID(drill_id), STATUS_PASSED, _NOW - timedelta(minutes=60), None)
        session.commit()
    app = create_app(settings.model_copy(update={"admin_token": _TOKEN}))
    with TestClient(app) as client:
        fresh = client.get(f"/drills/{drill_id}", headers=_AUTH)
    assert fresh.json()["rpo_status"] == "ok"
    with Session(engine) as session:
        stored = session.scalar(select(Run).where(Run.drill_id == UUID(drill_id)))
        assert stored is not None
        stored.finished_at = _NOW - timedelta(minutes=60, microseconds=1)
        session.commit()
    with TestClient(app) as client:
        stale = client.get(f"/drills/{drill_id}", headers=_AUTH)
    assert stale.json()["rpo_status"] == "breached"
    quiet = _drill(engine, "rpo-quiet")
    with TestClient(app) as client:
        unknown = client.get(f"/drills/{quiet}", headers=_AUTH)
    assert unknown.json()["rpo_status"] == "unknown"
    assert unknown.json()["open_failures"] == []


def _seed(engine: Engine) -> tuple[str, str, str, str]:
    with Session(engine) as session:
        drill = _add_drill(session, "ack-drill")
        failed = _run(session, drill.id, STATUS_FAILED, _NOW - timedelta(hours=2), "dump is empty")
        passed = _run(session, drill.id, STATUS_PASSED, _NOW - timedelta(days=3), None)
        errored = _run(session, drill.id, STATUS_ERROR, _NOW - timedelta(hours=1), "restore failed")
        session.commit()
        return str(drill.id), str(failed.id), str(passed.id), str(errored.id)


def _drill(engine: Engine, name: str) -> str:
    with Session(engine) as session:
        drill = _add_drill(session, name)
        session.commit()
        return str(drill.id)


def _add_drill(session: Session, name: str) -> Drill:
    drill = Drill(
        id=uuid4(),
        name=name,
        source_kind="local",
        source_uri="dumps",
        rpo_minutes=60,
        assertions=[],
        enabled=True,
    )
    session.add(drill)
    session.flush()
    return drill


def _run(
    session: Session,
    drill_id: UUID,
    status: str,
    finished: datetime,
    error: str | None,
) -> Run:
    run = Run(
        id=uuid4(),
        drill_id=drill_id,
        status=status,
        dump_key=None,
        dump_bytes=None,
        dump_sha256=None,
        restore_seconds=None,
        started_at=finished,
        finished_at=finished,
        error=error,
    )
    session.add(run)
    session.flush()
    return run


def _env(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("TARGET_URL", settings.target_url)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
