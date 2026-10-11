"""A dump newer than pg_restore is stored as failed and is not restored."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_FAILED, Run
from pgrestoredrill.runner.service import execute_drill
from tests.integration.preflight_helpers import local_config

_REFUSAL = "dump is from Postgres 17; this image restores 16 or older"
_REASON = "the dump was made by a newer postgres than this restore client"


def test_a_postgres_17_dump_is_refused(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "dumps"
    folder.mkdir()
    (folder / "seventeen.dump").write_bytes(_header_17())
    calls: list[str] = []

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("should not restore")

    def complete(self: object, prompt: str) -> str:
        calls.append(prompt)
        raise AssertionError("should not call")

    monkeypatch.setattr("pgrestoredrill.runner.header.pg_restore_major", lambda: 16)
    monkeypatch.setattr("pgrestoredrill.runner.service.restore_dump", explode)
    monkeypatch.setattr("pgrestoredrill.targets.opening.create_drill_database", explode)
    monkeypatch.setattr("pgrestoredrill.notes.client.HttpNoteClient.complete", complete)
    hooked = settings.model_copy(
        update={
            "notes_enabled": True,
            "notes_url": "https://api.x.ai/v1",
            "notes_model": "test-model",
            "notes_api_key": "test-key",
        }
    )
    completed = execute_drill(hooked, local_config(tmp_path, "newer-dump", folder))
    assert completed.status == STATUS_FAILED
    assert completed.error == _REFUSAL
    assert completed.database_name is None
    assert completed.restore_seconds is None
    assert completed.assertions == ()
    assert calls == []
    assert completed.run_id is not None
    with Session(engine) as session:
        stored = session.get(Run, completed.run_id)
    assert stored is not None
    assert stored.status == STATUS_FAILED
    assert stored.error == _REFUSAL
    assert stored.failure_category == "version mismatch"
    assert stored.failure_reason == _REASON
    assert stored.note is None
    assert stored.acked_at is None


def _header_17() -> bytes:
    out = bytearray(b"PGDMP")
    out.extend(bytes((1, 16, 0, 4, 8, 1, 0)))
    for _ in range(7):
        out.extend(bytes((0, 1, 0, 0, 0)))
    for text in (b"app", b"17.2", b"17.2"):
        out.extend(bytes((0, len(text), 0, 0, 0)))
        out.extend(text)
    return bytes(out)
