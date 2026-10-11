"""Four sessions resend one stuck alert, and only one post is made."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Barrier, BrokenBarrierError, Lock, Thread
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

import pgrestoredrill.alerts.notify as notify
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_FAILED, STATUS_PASSED, Alert, Drill, Run
from pgrestoredrill.runner.report import CompletedRun

_WORKERS = 4


def test_four_sessions_resend_a_stuck_alert_once(
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
    old_id, completed = _seed(engine)
    barrier = Barrier(_WORKERS)
    errors: list[BaseException] = []
    real = notify._resend_stuck

    def synced(session: Session, url: str, now: datetime, pending: list[int]) -> None:
        # The pending ids are already loaded. The claim decides who sends.
        try:
            barrier.wait(timeout=10)
        except BrokenBarrierError as exc:
            errors.append(exc)
            return
        real(session, url, now, pending)

    monkeypatch.setattr(notify, "_resend_stuck", synced)

    def worker() -> None:
        try:
            with Session(engine) as session:
                notify.notify_after_run(session, hooked, completed)
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
    assert [item["run_id"] for item in posts] == [old_id]
    with Session(engine) as session:
        stored = list(session.scalars(select(Alert)).all())
    assert len(stored) == 1
    assert stored[0].response_status == 204
    assert stored[0].sent_at is not None


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


def _seed(engine: Engine) -> tuple[str, CompletedRun]:
    now = datetime.now(UTC)
    with Session(engine) as session:
        drill = Drill(
            id=uuid4(),
            name=f"claim-{uuid4().hex[:8]}",
            source_kind="local",
            source_uri="dumps",
            rpo_minutes=60,
            assertions=[],
            enabled=True,
        )
        session.add(drill)
        session.flush()
        old = Run(
            id=uuid4(),
            drill_id=drill.id,
            status=STATUS_FAILED,
            dump_key="backups/old.dump",
            dump_bytes=0,
            dump_sha256=None,
            restore_seconds=None,
            started_at=now - timedelta(minutes=11),
            finished_at=now - timedelta(minutes=11),
            error="dump is empty",
        )
        fresh = Run(
            id=uuid4(),
            drill_id=drill.id,
            status=STATUS_PASSED,
            dump_key="backups/fresh.dump",
            dump_bytes=4,
            dump_sha256="abc",
            restore_seconds=1.0,
            started_at=now,
            finished_at=now,
            error=None,
        )
        session.add(old)
        session.add(fresh)
        session.flush()
        session.add(
            Alert(
                drill_id=drill.id,
                run_id=old.id,
                dedup_key=f"run:{old.id}",
                status=STATUS_FAILED,
                reason="dump is empty",
                sent_at=None,
                response_status=None,
            )
        )
        session.commit()
        old_id = str(old.id)
        completed = CompletedRun(
            status=fresh.status,
            drill_name=drill.name,
            run_id=fresh.id,
            database_name=None,
            dump_path=fresh.dump_key,
            dump_bytes=fresh.dump_bytes,
            dump_sha256=fresh.dump_sha256,
            restore_seconds=fresh.restore_seconds,
            error=fresh.error,
            assertions=(),
        )
    return old_id, completed
