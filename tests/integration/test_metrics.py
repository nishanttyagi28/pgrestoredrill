"""Metric values come from stored runs and use drill names as labels."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from pgrestoredrill.api.app import create_app
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import (
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_RUNNING,
    Drill,
    Run,
)
from pgrestoredrill.metrics import CONTENT_TYPE_LATEST

_NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
_SECRET_URI = "s3://secret-bucket/private.dump"
_SECRET_KEY = "private/secret.dump"
_SECRET_ERROR = "dump is empty"


def test_metrics_follow_pass_fail_and_rpo(
    settings: Settings,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pgrestoredrill.api.routes.clock", lambda: _NOW)
    passed_at = _NOW - timedelta(minutes=30)
    stale_at = _NOW - timedelta(minutes=61)
    with Session(engine) as session:
        orders = _drill(session, "orders")
        _run(session, orders, STATUS_PASSED, passed_at, 2.5, None, None)
        _run(
            session,
            orders,
            STATUS_FAILED,
            _NOW - timedelta(minutes=10),
            None,
            _SECRET_KEY,
            _SECRET_ERROR,
        )
        _run(session, orders, STATUS_RUNNING, None, None, _SECRET_KEY, None)
        stale = _drill(session, "stale-orders")
        _run(session, stale, STATUS_PASSED, stale_at, 9.0, None, None)
        failed_only = _drill(session, "failed-only")
        _run(
            session,
            failed_only,
            STATUS_FAILED,
            _NOW - timedelta(minutes=5),
            None,
            None,
            _SECRET_ERROR,
        )
        _drill(session, "quiet-drill")
        session.commit()
    with TestClient(create_app(settings)) as client:
        first = client.get("/metrics")
        second = client.get("/metrics")
    assert first.status_code == 200
    assert first.headers["content-type"] == CONTENT_TYPE_LATEST
    text = first.text
    assert _SECRET_URI not in text
    assert _SECRET_KEY not in text
    assert _SECRET_ERROR not in text
    assert "secret" not in text
    samples = _samples(text)
    assert _value(samples, "pgrestoredrill_restore_duration_seconds_sum", drill="orders") == 2.5
    assert _value(samples, "pgrestoredrill_restore_duration_seconds_count", drill="orders") == 1.0
    assert _value(samples, "pgrestoredrill_runs_total", drill="orders", status="passed") == 1.0
    assert _value(samples, "pgrestoredrill_runs_total", drill="orders", status="failed") == 1.0
    assert _value(samples, "pgrestoredrill_runs_total", drill="orders", status="running") == 1.0
    assert (
        _value(samples, "pgrestoredrill_last_success_timestamp_seconds", drill="orders")
        == passed_at.timestamp()
    )
    assert _value(samples, "pgrestoredrill_rpo_breached", drill="orders") == 0.0
    assert (
        _value(samples, "pgrestoredrill_restore_duration_seconds_sum", drill="stale-orders") == 9.0
    )
    assert _value(samples, "pgrestoredrill_rpo_breached", drill="stale-orders") == 1.0
    assert (
        _value(samples, "pgrestoredrill_last_success_timestamp_seconds", drill="stale-orders")
        == stale_at.timestamp()
    )
    assert _value(samples, "pgrestoredrill_runs_total", drill="failed-only", status="failed") == 1.0
    assert _value(samples, "pgrestoredrill_rpo_breached", drill="failed-only") == 1.0
    assert not _has(samples, "pgrestoredrill_last_success_timestamp_seconds", drill="failed-only")
    assert not _has(samples, "pgrestoredrill_restore_duration_seconds_count", drill="failed-only")
    assert _value(samples, "pgrestoredrill_rpo_breached", drill="quiet-drill") == 0.0
    assert not _labeled(samples, "pgrestoredrill_runs_total", "quiet-drill")
    assert not _labeled(samples, "pgrestoredrill_last_success_timestamp_seconds", "quiet-drill")
    assert _stable(samples) == _stable(_samples(second.text))


def _drill(session: Session, name: str) -> Drill:
    drill = Drill(
        id=uuid4(),
        name=name,
        source_kind="s3",
        source_uri=_SECRET_URI,
        rpo_minutes=60,
        assertions=[],
        enabled=True,
    )
    session.add(drill)
    session.flush()
    return drill


def _run(
    session: Session,
    drill: Drill,
    status: str,
    finished: datetime | None,
    restore_seconds: float | None,
    dump_key: str | None,
    error: str | None,
) -> None:
    started = _NOW if finished is None else finished
    session.add(
        Run(
            id=uuid4(),
            drill_id=drill.id,
            status=status,
            dump_key=dump_key,
            dump_bytes=None,
            dump_sha256=None,
            restore_seconds=restore_seconds,
            started_at=started,
            finished_at=finished,
            error=error,
        )
    )


def _samples(text: str) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    found: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        head, _, tail = line.partition(" ")
        if "{" in head:
            name, _, labels = head.partition("{")
            pairs = tuple(
                (key, value[1:-1])
                for key, value in (part.split("=", 1) for part in labels[:-1].split(","))
            )
        else:
            name = head
            pairs = ()
        found[(name, tuple(sorted(pairs)))] = float(tail.split()[0])
    return found


def _value(
    samples: dict[tuple[str, tuple[tuple[str, str], ...]], float], name: str, **labels: str
) -> float:
    return samples[(name, tuple(sorted(labels.items())))]


def _has(
    samples: dict[tuple[str, tuple[tuple[str, str], ...]], float], name: str, **labels: str
) -> bool:
    return (name, tuple(sorted(labels.items()))) in samples


def _labeled(
    samples: dict[tuple[str, tuple[tuple[str, str], ...]], float], name: str, drill: str
) -> bool:
    return any(metric == name and dict(pairs).get("drill") == drill for (metric, pairs) in samples)


def _stable(
    samples: dict[tuple[str, tuple[tuple[str, str], ...]], float],
) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    return {key: value for key, value in samples.items() if "_created" not in key[0]}
