"""Prometheus text computed from stored runs. Labels are drill names only."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from pgrestoredrill.db.models import STATUS_PASSED, Drill, Run
from pgrestoredrill.runner.rpo import RPO_BREACHED, rpo_status

__all__ = ["CONTENT_TYPE_LATEST", "render_metrics"]


def render_metrics(session: Session, now: datetime) -> bytes:
    registry = CollectorRegistry()
    duration = Histogram(
        "pgrestoredrill_restore_duration_seconds",
        "Seconds spent restoring a dump.",
        labelnames=("drill",),
        registry=registry,
    )
    totals = Counter(
        "pgrestoredrill_runs_total",
        "Recorded runs.",
        labelnames=("drill", "status"),
        registry=registry,
    )
    last_success = Gauge(
        "pgrestoredrill_last_success_timestamp_seconds",
        "Unix time of the newest passed run.",
        labelnames=("drill",),
        registry=registry,
    )
    breached = Gauge(
        "pgrestoredrill_rpo_breached",
        "1 when the drill is outside its RPO.",
        labelnames=("drill",),
        registry=registry,
    )
    for drill, runs in _runs_by_drill(session):
        _fill(drill, runs, now, duration, totals, last_success, breached)
    return generate_latest(registry)


def _runs_by_drill(session: Session) -> list[tuple[Drill, list[Run]]]:
    drills = list(session.scalars(select(Drill).order_by(Drill.name)))
    grouped: dict[UUID, list[Run]] = {drill.id: [] for drill in drills}
    for run in session.scalars(select(Run)):
        rows = grouped.get(run.drill_id)
        if rows is not None:
            rows.append(run)
    return [(drill, grouped[drill.id]) for drill in drills]


def _fill(
    drill: Drill,
    runs: list[Run],
    now: datetime,
    duration: Histogram,
    totals: Counter,
    last_success: Gauge,
    breached: Gauge,
) -> None:
    counts: dict[str, int] = {}
    latest: datetime | None = None
    saw_finished = False
    for run in runs:
        counts[run.status] = counts.get(run.status, 0) + 1
        if run.restore_seconds is not None:
            duration.labels(drill.name).observe(run.restore_seconds)
        if run.finished_at is not None:
            saw_finished = True
        if run.status == STATUS_PASSED and run.finished_at is not None:
            latest = _later(latest, run.finished_at)
    status = rpo_status(
        rpo_minutes=drill.rpo_minutes,
        has_finished_run=saw_finished,
        last_passed_at=latest,
        now=now,
    )
    breached.labels(drill.name).set(1.0 if status == RPO_BREACHED else 0.0)
    if latest is not None:
        last_success.labels(drill.name).set(latest.timestamp())
    for run_status, count in sorted(counts.items()):
        totals.labels(drill.name, run_status).inc(count)


def _later(current: datetime | None, finished: datetime) -> datetime:
    aware = _aware(finished)
    if current is None or aware > current:
        return aware
    return current


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
