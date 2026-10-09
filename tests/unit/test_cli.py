"""CLI exit codes and secret redaction."""

from __future__ import annotations

from pathlib import Path

import pytest
import structlog

from pgrestoredrill.cli import dispatch, main
from pgrestoredrill.config import Settings
from pgrestoredrill.logging import configure_logging
from pgrestoredrill.runner.report import CompletedRun, format_summary


def test_usage_error() -> None:
    with pytest.raises(SystemExit) as caught:
        dispatch([])
    assert caught.value.code == 2
    with pytest.raises(SystemExit) as caught_main:
        main([])
    assert caught_main.value.code == 2


def test_failed_drill_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)

    def fake(settings: Settings, path: Path) -> CompletedRun:
        return _run("failed")

    monkeypatch.setattr("pgrestoredrill.cli.execute_drill", fake)
    code = dispatch(["run", "--config", str(tmp_path / "drill.yaml")])
    assert code == 1
    assert "status: failed" in capsys.readouterr().out


def test_passed_drill_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)

    def fake(settings: Settings, path: Path) -> CompletedRun:
        return _run("passed")

    monkeypatch.setattr("pgrestoredrill.cli.execute_drill", fake)
    assert dispatch(["run", "--config", str(tmp_path / "drill.yaml")]) == 0
    assert "status: passed" in capsys.readouterr().out


def test_invalid_configuration_hides_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TARGET_URL", raising=False)
    code = dispatch(["run", "--config", str(tmp_path / "drill.yaml")])
    output = capsys.readouterr().out
    assert code == 1
    assert "invalid configuration" in output
    assert "://" not in output


def test_cli_redacts_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)

    def fake(settings: Settings, path: Path) -> CompletedRun:
        raise RuntimeError("failed postgresql://user:secret@localhost/pgrestoredrill")

    monkeypatch.setattr("pgrestoredrill.cli.execute_drill", fake)
    assert dispatch(["run", "--config", str(tmp_path / "drill.yaml")]) == 1
    output = capsys.readouterr().out
    assert "secret" not in output
    assert "***" in output


def test_summary_lists_assertions() -> None:
    from pgrestoredrill.assertions.models import AssertionOutcome

    text = format_summary(
        CompletedRun(
            status="failed",
            drill_name="sample",
            run_id=None,
            database_name="pgrestoredrill_" + ("ab" * 16),
            dump_path="backup.dump",
            dump_bytes=3,
            dump_sha256="abc",
            restore_seconds=1.2,
            error="pg_restore exited 1",
            assertions=(AssertionOutcome("customers_present", False, "1", "2", 4),),
        )
    )
    assert "status: failed" in text
    assert "customers_present failed observed=1 expected=2 4ms" in text
    assert "restore_seconds: 1.200" in text


def test_configure_logging_omits_urls(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    structlog.get_logger().info("drill finished", drill="sample", status="passed")
    captured = capsys.readouterr().err
    assert "sample" in captured
    assert "postgresql://" not in captured


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/pgrestoredrill")
    monkeypatch.setenv("TARGET_URL", "postgresql://localhost/postgres")
    monkeypatch.setenv("LOG_LEVEL", "INFO")


def _run(status: str) -> CompletedRun:
    return CompletedRun(
        status=status,
        drill_name="sample",
        run_id=None,
        database_name=None,
        dump_path=None,
        dump_bytes=None,
        dump_sha256=None,
        restore_seconds=None,
        error=None,
        assertions=(),
    )
