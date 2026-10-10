"""Dump checks that run before pg_restore."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pgrestoredrill.runner.preflight import dump_rejection
from pgrestoredrill.runner.spec import load_drill
from pgrestoredrill.sources.local import LocalDump

_NOW = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)


def test_empty_dump_wins_over_the_other_checks() -> None:
    dump = _dump(0, _NOW - timedelta(days=30))
    assert dump_rejection(dump, min_bytes=10, max_age_minutes=1, now=_NOW) == "dump is empty"


def test_small_dump_is_refused_before_age() -> None:
    dump = _dump(3, _NOW - timedelta(days=30))
    reason = dump_rejection(dump, min_bytes=10, max_age_minutes=1, now=_NOW)
    assert reason == "dump is smaller than min_bytes"


def test_age_limit_is_exclusive() -> None:
    fresh = _dump(10, _NOW - timedelta(minutes=60))
    stale = _dump(10, _NOW - timedelta(minutes=60, seconds=1))
    naive = _dump(10, datetime(2024, 6, 1, 11, 0))
    assert dump_rejection(fresh, min_bytes=10, max_age_minutes=60, now=_NOW) is None
    assert dump_rejection(naive, min_bytes=None, max_age_minutes=60, now=_NOW) is None
    assert (
        dump_rejection(stale, min_bytes=None, max_age_minutes=60, now=_NOW)
        == "dump is older than max_age_minutes"
    )


def test_checks_are_optional() -> None:
    dump = _dump(1, _NOW - timedelta(days=365))
    assert dump_rejection(dump, min_bytes=None, max_age_minutes=None, now=_NOW) is None


def test_limits_must_be_positive(tmp_path: Path) -> None:
    path = tmp_path / "drill.yaml"
    path.write_text(_drill("min_bytes: 0"), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid drill config"):
        load_drill(path)
    path.write_text(_drill("max_age_minutes: 0"), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid drill config"):
        load_drill(path)


def _dump(size: int, modified: datetime) -> LocalDump:
    return LocalDump(
        path=Path("backup.dump"),
        size=size,
        sha256="abc",
        modified=modified,
        key="backup.dump",
    )


def _drill(limit: str) -> str:
    return "\n".join(
        [
            "name: sample",
            "source_kind: local",
            "source_uri: dumps",
            "rpo_minutes: 60",
            "assertions_file: assertions.yaml",
            limit,
            "",
        ]
    )
