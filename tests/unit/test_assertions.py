"""Assertion documents and comparisons, without a database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pgrestoredrill.assertions.evaluate import judge
from pgrestoredrill.assertions.loader import load_assertions
from pgrestoredrill.assertions.models import AssertionSpec
from pgrestoredrill.runner.spec import load_drill, resolve_from_config

_NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _spec(kind: str, expected: object, sql: str = "SELECT 1") -> AssertionSpec:
    return AssertionSpec.model_validate(
        {"name": "check", "type": kind, "sql": sql, "expected": expected}
    )


def test_rows_gte_pass_and_fail() -> None:
    assert judge(_spec("rows_gte", 2), 2)[0] is True
    assert judge(_spec("rows_gte", 2), 1)[0] is False
    assert judge(_spec("rows_gte", 2), None)[0] is False


def test_equals_pass_and_fail() -> None:
    assert judge(_spec("equals", "a@example.com"), "a@example.com")[0] is True
    assert judge(_spec("equals", "a@example.com"), "other@example.com")[0] is False
    assert judge(_spec("equals", 2), 2)[0] is True
    assert judge(_spec("equals", 2), 3)[0] is False


def test_max_age_minutes_pass_and_fail() -> None:
    fresh = _NOW - timedelta(minutes=5)
    old = _NOW - timedelta(days=2)
    boundary = _NOW - timedelta(minutes=60)
    assert judge(_spec("max_age_minutes", 60), fresh, now=_NOW)[0] is True
    assert judge(_spec("max_age_minutes", 60), boundary, now=_NOW)[0] is True
    assert judge(_spec("max_age_minutes", 60), old, now=_NOW)[0] is False
    assert judge(_spec("max_age_minutes", 60), None, now=_NOW)[0] is False


def test_load_assertions_yaml(tmp_path: Path) -> None:
    path = tmp_path / "assertions.yaml"
    path.write_text(
        """
assertions:
  - name: customers_present
    type: rows_gte
    sql: "SELECT count(*) FROM customers"
    expected: 2
  - name: modulo
    type: equals
    sql: "SELECT 10 % 4"
    expected: 2
""",
        encoding="utf-8",
    )
    loaded = load_assertions(path)
    assert [item.name for item in loaded] == ["customers_present", "modulo"]
    assert loaded[1].sql == "SELECT 10 % 4"
    assert loaded[0].assertion_type == "rows_gte"


def test_rejects_bad_assertion_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("[]\n", encoding="utf-8")
    multi = tmp_path / "multi.yaml"
    multi.write_text(
        "- {name: x, type: equals, sql: 'SELECT 1; SELECT 2', expected: 1}\n",
        encoding="utf-8",
    )
    broken = tmp_path / "broken.yaml"
    broken.write_text(":\n  - [", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid assertions file"):
        load_assertions(empty)
    with pytest.raises(ValueError, match="invalid assertions file"):
        load_assertions(multi)
    with pytest.raises(ValueError, match="invalid assertions file"):
        load_assertions(broken)
    with pytest.raises(FileNotFoundError):
        load_assertions(tmp_path / "missing.yaml")


def test_drill_file_and_relative_paths(tmp_path: Path) -> None:
    assertions = tmp_path / "assertions.yaml"
    assertions.write_text(
        "- {name: customers_present, type: rows_gte, sql: 'SELECT 1', expected: 1}\n",
        encoding="utf-8",
    )
    config = tmp_path / "drill.yaml"
    config.write_text(
        "\n".join(
            [
                "name: sample",
                "source_kind: local",
                "source_uri: dumps",
                "rpo_minutes: 1440",
                "assertions_file: assertions.yaml",
            ]
        ),
        encoding="utf-8",
    )
    drill = load_drill(config)
    assert drill.source_kind == "local"
    assert drill.restore_timeout_seconds == 60
    assert resolve_from_config(config, drill.source_uri) == (tmp_path / "dumps").resolve()
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: sample\nsource_kind: ftp\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid drill config"):
        load_drill(bad)
