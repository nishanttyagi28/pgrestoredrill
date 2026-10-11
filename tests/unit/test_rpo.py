"""RPO status at the boundary, with the caller supplying the clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pgrestoredrill.runner.rpo import RPO_BREACHED, RPO_OK, RPO_UNKNOWN, rpo_status

_NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
_RPO = 60


def test_unknown_when_the_drill_has_never_finished() -> None:
    assert (
        rpo_status(
            rpo_minutes=_RPO,
            has_finished_run=False,
            last_passed_at=None,
            now=_NOW,
        )
        == RPO_UNKNOWN
    )


def test_breached_when_no_run_passed() -> None:
    assert (
        rpo_status(
            rpo_minutes=_RPO,
            has_finished_run=True,
            last_passed_at=None,
            now=_NOW,
        )
        == RPO_BREACHED
    )


def test_ok_when_the_last_pass_is_exactly_the_rpo() -> None:
    assert (
        rpo_status(
            rpo_minutes=_RPO,
            has_finished_run=True,
            last_passed_at=_NOW - timedelta(minutes=_RPO),
            now=_NOW,
        )
        == RPO_OK
    )


def test_breached_when_the_last_pass_is_older_than_the_rpo() -> None:
    assert (
        rpo_status(
            rpo_minutes=_RPO,
            has_finished_run=True,
            last_passed_at=_NOW - timedelta(minutes=_RPO, microseconds=1),
            now=_NOW,
        )
        == RPO_BREACHED
    )


def test_a_naive_pass_time_is_read_as_utc() -> None:
    naive = (_NOW - timedelta(minutes=1)).replace(tzinfo=None)
    assert (
        rpo_status(
            rpo_minutes=_RPO,
            has_finished_run=True,
            last_passed_at=naive,
            now=_NOW,
        )
        == RPO_OK
    )
