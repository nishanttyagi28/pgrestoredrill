"""Alerts are sent once and never change the stored run."""

from __future__ import annotations

import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from pgrestoredrill.alerts.notify import notify_after_run
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_FAILED, STATUS_PASSED, Alert, Drill, Run
from pgrestoredrill.runner.report import CompletedRun
from pgrestoredrill.runner.service import execute_drill

_URL = "https://alerts.example/hook"


def test_a_failure_is_sent_once_and_the_breach_is_not_resent(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _capture(monkeypatch, lambda payload: 204)
    hooked = _hooked(settings)
    folder = _dumps(tmp_path)
    first = execute_drill(hooked, _config(tmp_path, "alert-once", folder))
    assert first.status == STATUS_FAILED
    assert first.error == "dump is empty"
    assert [item["status"] for item in posts] == ["failed", "breached"]
    assert posts[0]["reason"] == "dump is empty"
    assert posts[0]["run_id"] == str(first.run_id)
    assert posts[1]["reason"] == "drill is outside its rpo"
    assert set(posts[0]) == {"drill", "status", "reason", "run_id"}
    second = execute_drill(hooked, _config(tmp_path / "again", "alert-once", folder))
    assert [item["status"] for item in posts] == ["failed", "breached", "failed"]
    assert posts[2]["run_id"] == str(second.run_id)
    with Session(engine) as session:
        notify_after_run(session, hooked, first)
        stored = list(session.scalars(select(Alert).order_by(Alert.id)).all())
    assert len(posts) == 3
    assert [item.response_status for item in stored] == [204, 204, 204]
    assert all(item.sent_at is not None for item in stored)
    _assert_run(engine, first.run_id, STATUS_FAILED, "dump is empty")


def test_delivery_retries_then_gives_up_without_changing_the_run(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def reject(payload: dict[str, str]) -> int:
        attempts.append(payload["status"])
        raise urllib.error.URLError("down")

    _capture(monkeypatch, reject)
    hooked = _hooked(settings)
    completed = execute_drill(hooked, _config(tmp_path, "alert-retry", _dumps(tmp_path)))
    assert attempts == ["failed", "failed", "failed", "breached", "breached", "breached"]
    assert completed.status == STATUS_FAILED
    assert completed.error == "dump is empty"
    _assert_run(engine, completed.run_id, STATUS_FAILED, "dump is empty")
    with Session(engine) as session:
        stored = list(session.scalars(select(Alert).order_by(Alert.id)).all())
        notify_after_run(session, hooked, completed)
    assert attempts == ["failed", "failed", "failed", "breached", "breached", "breached"]
    assert [item.response_status for item in stored] == [None, None]
    assert all(item.sent_at is not None for item in stored)
    assert _URL not in (completed.error or "")


def test_an_unset_webhook_sends_nothing(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _capture(monkeypatch, lambda payload: 204)
    completed = execute_drill(settings, _config(tmp_path, "alert-quiet", _dumps(tmp_path)))
    assert completed.status == STATUS_FAILED
    assert posts == []
    with Session(engine) as session:
        assert list(session.scalars(select(Alert)).all()) == []


def test_a_fresh_pass_sends_nothing(
    settings: Settings,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _capture(monkeypatch, lambda payload: 204)
    hooked = _hooked(settings)
    now = datetime.now(UTC)
    with Session(engine) as session:
        drill = Drill(
            id=uuid4(),
            name="alert-pass",
            source_kind="local",
            source_uri="dumps",
            rpo_minutes=60,
            assertions=[],
            enabled=True,
        )
        session.add(drill)
        session.flush()
        run = Run(
            id=uuid4(),
            drill_id=drill.id,
            status=STATUS_PASSED,
            dump_key="backups/fresh.dump",
            dump_bytes=4,
            dump_sha256="abc",
            restore_seconds=1.5,
            started_at=now,
            finished_at=now,
            error=None,
        )
        session.add(run)
        session.commit()
        notify_after_run(session, hooked, _completed(run))
    assert posts == []
    with Session(engine) as session:
        assert list(session.scalars(select(Alert)).all()) == []


def _capture(
    monkeypatch: pytest.MonkeyPatch,
    handle: Callable[[dict[str, str]], int],
) -> list[dict[str, str]]:
    posts: list[dict[str, str]] = []

    def post(url: str, payload: dict[str, str], timeout: float) -> int:
        assert url == _URL
        assert timeout == 5.0
        posts.append(dict(payload))
        return handle(payload)

    monkeypatch.setattr("pgrestoredrill.alerts.webhook.post_json", post)
    monkeypatch.setattr("pgrestoredrill.alerts.webhook.time.sleep", lambda seconds: None)
    return posts


def _hooked(settings: Settings) -> Settings:
    return settings.model_copy(update={"alert_webhook_url": _URL})


def _dumps(root: Path) -> Path:
    folder = root / "dumps"
    folder.mkdir()
    (folder / "empty.dump").write_bytes(b"")
    return folder


def _config(root: Path, name: str, folder: Path) -> Path:
    root.mkdir(exist_ok=True)
    (root / "assertions.yaml").write_text(
        yaml.safe_dump([{"name": "present", "type": "rows_gte", "sql": "SELECT 1", "expected": 1}]),
        encoding="utf-8",
    )
    config = root / "drill.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "name": name,
                "source_kind": "local",
                "source_uri": folder.as_posix(),
                "rpo_minutes": 60,
                "assertions_file": "assertions.yaml",
            }
        ),
        encoding="utf-8",
    )
    return config


def _assert_run(engine: Engine, run_id: UUID | None, status: str, error: str) -> None:
    assert run_id is not None
    with Session(engine) as session:
        run = session.get(Run, run_id)
    assert run is not None
    assert run.status == status
    assert run.error == error
    assert run.acked_at is None
    assert run.acked_by is None
    assert run.note is None


def _completed(run: Run) -> CompletedRun:
    return CompletedRun(
        status=run.status,
        drill_name="alert-pass",
        run_id=run.id,
        database_name=None,
        dump_path=run.dump_key,
        dump_bytes=run.dump_bytes,
        dump_sha256=run.dump_sha256,
        restore_seconds=run.restore_seconds,
        error=run.error,
        assertions=(),
    )
