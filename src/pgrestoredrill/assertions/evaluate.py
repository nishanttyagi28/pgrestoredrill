"""Compare one assertion result with its expected value."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from pgrestoredrill.assertions.models import AssertionSpec


def judge(
    spec: AssertionSpec,
    observed: object,
    *,
    now: datetime | None = None,
) -> tuple[bool, str | None]:
    rendered = format_observed(observed)
    if spec.assertion_type == "rows_gte":
        return _rows_gte(observed, spec.expected), rendered
    if spec.assertion_type == "equals":
        return _equals(observed, spec.expected), rendered
    return _max_age(observed, spec.expected, now or datetime.now(UTC)), rendered


def format_observed(value: object) -> str | None:
    if value is None:
        return None
    moment = _as_utc(value)
    if moment is not None:
        return moment.isoformat()
    return str(value)


def _rows_gte(observed: object, expected: int | float | str) -> bool:
    try:
        return _as_decimal(observed) >= _as_decimal(expected)
    except (ArithmeticError, TypeError, ValueError):
        return False


def _equals(observed: object, expected: int | float | str) -> bool:
    if observed is None:
        return False
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return _as_decimal(observed) == _as_decimal(expected)
        except (ArithmeticError, TypeError, ValueError):
            return False
    return format_observed(observed) == str(expected)


def _max_age(observed: object, expected: int | float | str, now: datetime) -> bool:
    moment = _as_utc(observed)
    if moment is None:
        return False
    try:
        limit = timedelta(minutes=float(expected))
    except (TypeError, ValueError):
        return False
    return now - moment <= limit


def _as_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise TypeError("not a number")
    return Decimal(str(value))


def _as_utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return None
