"""End-to-end local drills: one pass and one deliberate failure."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from pgrestoredrill.cli import dispatch
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_FAILED, STATUS_PASSED, AssertionResult, Run
from pgrestoredrill.runner.report import CompletedRun
from pgrestoredrill.runner.service import execute_drill
from pgrestoredrill.targets.external import drop_database, is_drill_database
from tests.fixtures.build_fixture import build_dump

_PASSING = [
    {
        "name": "customers_present",
        "type": "rows_gte",
        "sql": "SELECT count(*) FROM customers",
        "expected": 2,
    },
    {
        "name": "first_email",
        "type": "equals",
        "sql": "SELECT email FROM customers WHERE id = 1",
        "expected": "a@example.com",
    },
    {
        "name": "orders_are_fresh",
        "type": "max_age_minutes",
        "sql": "SELECT max(created_at) FROM orders",
        "expected": 60,
    },
]


@pytest.fixture(scope="module")
def sample_dump(admin_url: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("sample-dump")
    return build_dump(admin_url, folder / "sample.dump")


def test_passing_drill(
    settings: Settings,
    engine: Engine,
    admin_url: str,
    sample_dump: Path,
    tmp_path: Path,
) -> None:
    completed = execute_drill(
        settings, _config(tmp_path, "pass-drill", sample_dump.parent, _PASSING)
    )
    try:
        assert completed.status == STATUS_PASSED
        assert completed.dump_sha256 is not None
        assert completed.dump_bytes == sample_dump.stat().st_size
        assert completed.restore_seconds is not None
        assert completed.restore_seconds >= 0
        assert completed.database_name is not None
        assert is_drill_database(completed.database_name) is True
        assert [item.passed for item in completed.assertions] == [True, True, True]
        assert completed.run_id is not None
        run, results = _history(engine, completed.run_id)
        assert run.status == STATUS_PASSED
        assert run.dump_sha256 == completed.dump_sha256
        assert run.error is None
        assert len(results) == 3
        assert all(item.passed for item in results)
    finally:
        _drop(admin_url, completed)


def test_failing_drill(
    settings: Settings,
    engine: Engine,
    admin_url: str,
    sample_dump: Path,
    tmp_path: Path,
) -> None:
    failing = [_PASSING[0] | {"expected": 100}, _PASSING[1], _PASSING[2]]
    completed = execute_drill(
        settings, _config(tmp_path, "fail-drill", sample_dump.parent, failing)
    )
    try:
        assert completed.status == STATUS_FAILED
        assert completed.error is None
        assert completed.restore_seconds is not None
        assert [item.passed for item in completed.assertions] == [False, True, True]
        assert completed.run_id is not None
        run, results = _history(engine, completed.run_id)
        assert run.status == STATUS_FAILED
        assert [item.passed for item in results] == [False, True, True]
    finally:
        _drop(admin_url, completed)


def test_cli_pass_and_fail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: Settings,
    admin_url: str,
    sample_dump: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("TARGET_URL", settings.target_url)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    passing = _config(tmp_path, "cli-pass", sample_dump.parent, _PASSING)
    failing = _config(
        tmp_path,
        "cli-fail",
        sample_dump.parent,
        [_PASSING[0] | {"expected": 100}, _PASSING[1], _PASSING[2]],
    )
    pass_code = dispatch(["run", "--config", str(passing)])
    pass_out = capsys.readouterr().out
    fail_code = dispatch(["run", "--config", str(failing)])
    fail_out = capsys.readouterr().out
    try:
        assert pass_code == 0
        assert "status: passed" in pass_out
        assert fail_code == 1
        assert "status: failed" in fail_out
        assert "postgres:postgres" not in pass_out
        assert "postgres:postgres" not in fail_out
    finally:
        _drop_printed(admin_url, pass_out)
        _drop_printed(admin_url, fail_out)


def test_disabled_drill_does_not_restore(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(url: str) -> str:
        raise AssertionError("should not create a database")

    monkeypatch.setattr("pgrestoredrill.runner.service.create_drill_database", explode)
    config = _config(tmp_path, "disabled", tmp_path / "missing.dump", _PASSING, enabled=False)
    completed = execute_drill(settings, config)
    assert completed.status == "error"
    assert completed.error == "drill is disabled"
    assert completed.run_id is None


def test_missing_dump_is_recorded(settings: Settings, engine: Engine, tmp_path: Path) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()
    completed = execute_drill(settings, _config(tmp_path, "empty", folder, _PASSING))
    assert completed.status == "error"
    assert completed.error is not None
    assert "no custom-format dump" in completed.error
    assert completed.dump_sha256 is None
    assert completed.run_id is not None
    run, results = _history(engine, completed.run_id)
    assert run.status == "error"
    assert run.dump_key is None
    assert results == []


def test_corrupt_dump_is_an_error(
    settings: Settings,
    admin_url: str,
    tmp_path: Path,
) -> None:
    folder = tmp_path / "dumps"
    folder.mkdir()
    (folder / "bad.dump").write_bytes(b"this is not a dump")
    completed = execute_drill(settings, _config(tmp_path, "corrupt", folder, _PASSING))
    try:
        assert completed.status == "error"
        assert completed.error is not None
        assert "not found" not in completed.error
        assert completed.database_name is not None
    finally:
        _drop(admin_url, completed)


def _config(
    root: Path,
    name: str,
    source: Path,
    assertions: list[dict[str, object]],
    *,
    enabled: bool = True,
) -> Path:
    assertions_path = root / f"{name}-assertions.yaml"
    assertions_path.write_text(yaml.safe_dump(assertions), encoding="utf-8")
    config_path = root / f"{name}.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "name": name,
                "source_kind": "local",
                "source_uri": source.as_posix(),
                "rpo_minutes": 1440,
                "assertions_file": assertions_path.as_posix(),
                "enabled": enabled,
                "restore_timeout_seconds": 60,
            }
        ),
        encoding="utf-8",
    )
    return config_path


def _history(engine: Engine, run_id: object) -> tuple[Run, list[AssertionResult]]:
    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        results = list(
            session.scalars(
                select(AssertionResult)
                .where(AssertionResult.run_id == run.id)
                .order_by(AssertionResult.id)
            ).all()
        )
    return run, results


def _drop(admin_url: str, completed: CompletedRun) -> None:
    if completed.database_name is None:
        return
    if is_drill_database(completed.database_name):
        drop_database(admin_url, completed.database_name)


def _drop_printed(admin_url: str, output: str) -> None:
    for name in re.findall(r"^database: (\S+)$", output, re.MULTILINE):
        if is_drill_database(name):
            drop_database(admin_url, name)
