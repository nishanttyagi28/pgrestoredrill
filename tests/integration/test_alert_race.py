"""One sender posts each failure, and a dispatch error leaves the run alone."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Barrier, Lock, Thread
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from pgrestoredrill.alerts.notify import notify_after_run
from pgrestoredrill.cli import dispatch
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_FAILED, Alert, Drill, Run
from pgrestoredrill.runner.report import CompletedRun

_WORKERS = 4


def test_concurrent_notify_posts_once_per_dedup_key(
    settings: Settings,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[dict[str, str]] = []
    server = _server(posts)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever)
    thread.start()
    hooked = settings.model_copy(update={"alert_webhook_url": f"http://127.0.0.1:{port}/hook"})
    completed = _seed_failure(engine)
    barrier = Barrier(_WORKERS)
    original = Session.commit

    def commit(self: Session) -> None:
        if any(isinstance(obj, Alert) for obj in self.new):
            barrier.wait(timeout=10)
        original(self)

    monkeypatch.setattr(Session, "commit", commit)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with Session(engine, expire_on_commit=False) as session:
                notify_after_run(session, hooked, completed)
        except BaseException as exc:
            errors.append(exc)

    workers = [Thread(target=worker) for _ in range(_WORKERS)]
    try:
        for worker_thread in workers:
            worker_thread.start()
        for worker_thread in workers:
            worker_thread.join(timeout=20)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert errors == []
    assert [item.is_alive() for item in workers] == [False, False, False, False]
    assert sorted(item["status"] for item in posts) == ["breached", "failed"]
    with Session(engine) as session:
        stored = list(session.scalars(select(Alert).order_by(Alert.id)).all())
    assert [item.status for item in stored] == ["failed", "breached"]
    assert [item.response_status for item in stored] == [204, 204]
    assert all(item.sent_at is not None for item in stored)


def test_an_alert_exception_leaves_the_cli_status(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def explode(url: str, payload: dict[str, str]) -> int:
        raise RuntimeError("alert boom")

    monkeypatch.setattr("pgrestoredrill.alerts.notify.deliver", explode)
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("TARGET_URL", settings.target_url)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://alerts.example/hook")
    code = dispatch(["run", "--config", str(_config(tmp_path))])
    captured = capsys.readouterr()
    assert code == 1
    assert "status: failed" in captured.out
    assert "error: dump is empty" in captured.out
    assert "status: error" not in captured.out
    assert "alert boom" not in captured.out
    assert "alert boom" not in captured.err
    with Session(engine) as session:
        run = session.scalars(select(Run)).one()
        stored = list(session.scalars(select(Alert)).all())
    assert run.status == STATUS_FAILED
    assert run.error == "dump is empty"
    assert len(stored) == 1
    assert stored[0].sent_at is None
    assert stored[0].response_status is None


def _server(posts: list[dict[str, str]]) -> HTTPServer:
    lock = Lock()

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw.decode("utf-8"))
            with lock:
                posts.append({str(key): str(value) for key, value in body.items()})
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    return HTTPServer(("127.0.0.1", 0), _Handler)


def _seed_failure(engine: Engine) -> CompletedRun:
    now = datetime.now(UTC)
    with Session(engine) as session:
        drill = Drill(
            id=uuid4(),
            name="alert-race",
            source_kind="local",
            source_uri="dumps",
            rpo_minutes=60,
            assertions=[],
            enabled=True,
        )
        session.add(drill)
        session.flush()
        run = Run(
            id=uuid4(),
            drill_id=drill.id,
            status=STATUS_FAILED,
            dump_key=None,
            dump_bytes=None,
            dump_sha256=None,
            restore_seconds=None,
            started_at=now,
            finished_at=now,
            error="dump is empty",
        )
        session.add(run)
        session.commit()
        return CompletedRun(
            status=STATUS_FAILED,
            drill_name=drill.name,
            run_id=run.id,
            database_name=None,
            dump_path=None,
            dump_bytes=None,
            dump_sha256=None,
            restore_seconds=None,
            error=run.error,
            assertions=(),
        )


def _config(root: Path) -> Path:
    folder = root / "dumps"
    folder.mkdir(parents=True)
    (folder / "empty.dump").write_bytes(b"")
    (root / "assertions.yaml").write_text(
        yaml.safe_dump([{"name": "present", "type": "rows_gte", "sql": "SELECT 1", "expected": 1}]),
        encoding="utf-8",
    )
    config = root / "drill.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "name": "alert-boom",
                "source_kind": "local",
                "source_uri": folder.as_posix(),
                "rpo_minutes": 60,
                "assertions_file": "assertions.yaml",
            }
        ),
        encoding="utf-8",
    )
    return config
