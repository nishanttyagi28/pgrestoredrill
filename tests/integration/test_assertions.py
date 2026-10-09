"""Each assertion type against a real read-only transaction."""

from __future__ import annotations

import psycopg

from pgrestoredrill.assertions.models import AssertionOutcome, AssertionSpec
from pgrestoredrill.assertions.runner import run_assertions
from pgrestoredrill.db.urls import for_libpq
from tests.fixtures.sample_data import STATEMENTS


def test_rows_gte_passes(drill_url: str) -> None:
    _apply(drill_url, *STATEMENTS)
    outcome = _run(drill_url, "rows_gte", "SELECT count(*) FROM customers", 2)
    assert outcome.passed is True
    assert outcome.observed == "2"


def test_rows_gte_fails(drill_url: str) -> None:
    _apply(drill_url, *STATEMENTS)
    outcome = _run(drill_url, "rows_gte", "SELECT count(*) FROM customers", 3)
    assert outcome.passed is False
    assert outcome.observed == "2"


def test_equals_passes(drill_url: str) -> None:
    _apply(drill_url, *STATEMENTS)
    outcome = _run(
        drill_url,
        "equals",
        "SELECT email FROM customers WHERE id = 1",
        "a@example.com",
    )
    assert outcome.passed is True
    assert outcome.observed == "a@example.com"


def test_equals_fails(drill_url: str) -> None:
    _apply(drill_url, *STATEMENTS)
    outcome = _run(
        drill_url,
        "equals",
        "SELECT email FROM customers WHERE id = 1",
        "other@example.com",
    )
    assert outcome.passed is False


def test_modulo_equals_passes(drill_url: str) -> None:
    outcome = _run(drill_url, "equals", "SELECT 10 % 4", 2)
    assert outcome.passed is True
    assert outcome.observed == "2"


def test_max_age_minutes_passes(drill_url: str) -> None:
    _apply(drill_url, *STATEMENTS)
    outcome = _run(drill_url, "max_age_minutes", "SELECT max(created_at) FROM orders", 60)
    assert outcome.passed is True
    assert outcome.observed is not None


def test_max_age_minutes_fails(drill_url: str) -> None:
    _apply(
        drill_url,
        """
        CREATE TABLE events (
            id integer PRIMARY KEY,
            created_at timestamptz NOT NULL
        )
        """,
        """
        INSERT INTO events (id, created_at)
        VALUES (1, CURRENT_TIMESTAMP - INTERVAL '2 days')
        """,
    )
    outcome = _run(drill_url, "max_age_minutes", "SELECT max(created_at) FROM events", 60)
    assert outcome.passed is False


def test_later_assertion_runs_after_a_failure(drill_url: str) -> None:
    _apply(drill_url, *STATEMENTS)
    outcomes = run_assertions(
        drill_url,
        [
            _spec("too_many", "rows_gte", "SELECT count(*) FROM customers", 100),
            _spec(
                "first_email",
                "equals",
                "SELECT email FROM customers WHERE id = 1",
                "a@example.com",
            ),
        ],
        statement_timeout_ms=5000,
    )
    assert [item.passed for item in outcomes] == [False, True]


def test_write_sql_is_rejected(drill_url: str) -> None:
    _apply(drill_url, "CREATE TABLE notes (id integer PRIMARY KEY)")
    outcome = _run(drill_url, "equals", "INSERT INTO notes (id) VALUES (1)", 1)
    assert outcome.passed is False
    assert outcome.observed is not None
    assert "25006" in outcome.observed
    with psycopg.connect(for_libpq(drill_url), autocommit=True) as conn:
        count = conn.execute("SELECT count(*) FROM notes").fetchone()
    assert count is not None
    assert count[0] == 0


def test_statement_timeout(drill_url: str) -> None:
    outcome = run_assertions(
        drill_url,
        [_spec("slow", "equals", "SELECT pg_sleep(5)", 1)],
        statement_timeout_ms=200,
    )[0]
    assert outcome.passed is False
    assert outcome.observed is not None
    assert "57014" in outcome.observed
    assert outcome.duration_ms < 4000


def _run(url: str, kind: str, query: str, expected: object) -> AssertionOutcome:
    return run_assertions(
        url,
        [_spec("check", kind, query, expected)],
        statement_timeout_ms=5000,
    )[0]


def _spec(name: str, kind: str, query: str, expected: object) -> AssertionSpec:
    return AssertionSpec.model_validate(
        {"name": name, "type": kind, "sql": query, "expected": expected}
    )


def _apply(url: str, *statements: str) -> None:
    with psycopg.connect(for_libpq(url), autocommit=True) as conn:
        for statement in statements:
            conn.execute(statement)
