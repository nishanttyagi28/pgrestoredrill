"""A stuck alert is sent once on a later run. A 3xx resend is final."""

from __future__ import annotations

import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from pgrestoredrill.alerts.notify import notify_after_run
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_FAILED, STATUS_PASSED, Alert, Drill, Run
from pgrestoredrill.runner.report import CompletedRun

_URL = "https://alerts.example/hook"


def test_a_stuck_alert_is_resent_once(
    settings: Settings,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _capture(monkeypatch, lambda payload: 204)
    now = datetime.now(UTC)
    with Session(engine) as session:
        old, fresh = _pair(session, now, minutes=11)
        old_id = str(old.id)
        hooked = _hooked(settings)
        notify_after_run(session, hooked, _completed(fresh))
        notify_after_run(session, hooked, _completed(fresh))
        stored = list(session.scalars(select(Alert).order_by(Alert.id)).all())
    assert [item["run_id"] for item in posts] == [old_id]
    assert posts[0]["reason"] == "dump is empty"
    assert len(stored) == 1
    assert stored[0].response_status == 204
    assert stored[0].sent_at is not None


def test_a_recent_undelivered_alert_waits(
    settings: Settings,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _capture(monkeypatch, lambda payload: 204)
    now = datetime.now(UTC)
    with Session(engine) as session:
        _old, fresh = _pair(session, now, minutes=9)
        notify_after_run(session, _hooked(settings), _completed(fresh))
        stored = session.scalars(select(Alert)).one()
    assert posts == []
    assert stored.sent_at is None
    assert stored.response_status is None


def test_a_failed_resend_is_not_selected_again(
    settings: Settings,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def reject(payload: dict[str, str]) -> int:
        attempts.append(payload["run_id"])
        raise urllib.error.URLError("down")

    _capture(monkeypatch, reject)
    now = datetime.now(UTC)
    with Session(engine) as session:
        old, fresh = _pair(session, now, minutes=11)
        old_id = str(old.id)
        hooked = _hooked(settings)
        notify_after_run(session, hooked, _completed(fresh))
        notify_after_run(session, hooked, _completed(fresh))
        stored = session.scalars(select(Alert)).one()
    assert attempts == [old_id, old_id, old_id]
    assert stored.sent_at is None
    assert stored.response_status == 0


def test_a_redirected_resend_is_final(
    settings: Settings,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _capture(monkeypatch, lambda payload: 302)
    now = datetime.now(UTC)
    with Session(engine) as session:
        old, fresh = _pair(session, now, minutes=11)
        old_id = str(old.id)
        hooked = _hooked(settings)
        notify_after_run(session, hooked, _completed(fresh))
        notify_after_run(session, hooked, _completed(fresh))
        stored = session.scalars(select(Alert)).one()
    assert [item["run_id"] for item in posts] == [old_id]
    assert stored.sent_at is None
    assert stored.response_status == 302


def _pair(session: Session, now: datetime, *, minutes: int) -> tuple[Run, Run]:
    drill = Drill(
        id=uuid4(),
        name=f"resend-{minutes}-{uuid4().hex[:8]}",
        source_kind="local",
        source_uri="dumps",
        rpo_minutes=60,
        assertions=[],
        enabled=True,
    )
    session.add(drill)
    session.flush()
    old = Run(
        id=uuid4(),
        drill_id=drill.id,
        status=STATUS_FAILED,
        dump_key="backups/old.dump",
        dump_bytes=0,
        dump_sha256=None,
        restore_seconds=None,
        started_at=now - timedelta(minutes=minutes),
        finished_at=now - timedelta(minutes=minutes),
        error="dump is empty",
    )
    fresh = Run(
        id=uuid4(),
        drill_id=drill.id,
        status=STATUS_PASSED,
        dump_key="backups/fresh.dump",
        dump_bytes=4,
        dump_sha256="abc",
        restore_seconds=1.0,
        started_at=now,
        finished_at=now,
        error=None,
    )
    session.add(old)
    session.add(fresh)
    session.flush()
    session.add(
        Alert(
            drill_id=drill.id,
            run_id=old.id,
            dedup_key=f"run:{old.id}",
            status=STATUS_FAILED,
            reason="dump is empty",
            sent_at=None,
            response_status=None,
        )
    )
    session.commit()
    return old, fresh


def _capture(
    monkeypatch: pytest.MonkeyPatch,
    handle: Callable[[dict[str, str]], int],
) -> list[dict[str, str]]:
    posts: list[dict[str, str]] = []

    def post(url: str, payload: dict[str, str], timeout: float) -> int:
        assert url == _URL
        posts.append(dict(payload))
        return handle(payload)

    monkeypatch.setattr("pgrestoredrill.alerts.webhook.post_json", post)
    monkeypatch.setattr("pgrestoredrill.alerts.webhook.time.sleep", lambda seconds: None)
    return posts


def _hooked(settings: Settings) -> Settings:
    return settings.model_copy(update={"alert_webhook_url": _URL})


def _completed(run: Run) -> CompletedRun:
    return CompletedRun(
        status=run.status,
        drill_name="resend",
        run_id=run.id,
        database_name=None,
        dump_path=run.dump_key,
        dump_bytes=run.dump_bytes,
        dump_sha256=run.dump_sha256,
        restore_seconds=run.restore_seconds,
        error=run.error,
        assertions=(),
    )
