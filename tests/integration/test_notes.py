"""A failure suggestion is stored and sent, and it never changes the run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from pgrestoredrill.api.app import create_app
from pgrestoredrill.config import Settings
from pgrestoredrill.db.models import STATUS_ERROR, Run
from pgrestoredrill.db.urls import swap_database
from pgrestoredrill.errors import RestoreFailed
from pgrestoredrill.runner.service import execute_drill
from tests.integration.preflight_helpers import local_config

_HOOK = "https://alerts.example/hook"
_TOKEN = "test-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_STDERR = (
    "mystery failure postgresql://postgres:s3cret@db.internal:5432/app "
    "password=s3cret observed=secret-row"
)
_VALID = {
    "category": "timeout",
    "short_reason": "the restore stopped",
    "suggested_next_step": "raise the timeout and run the drill again",
}
_UNKNOWN = "the failure did not match a known restore error"


class _Fake:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.text


def test_a_valid_note_is_stored_and_marked_as_a_suggestion(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Fake(json.dumps(_VALID))
    completed, posts = _drill(
        settings,
        tmp_path,
        monkeypatch,
        name="note-valid",
        stderr=_STDERR,
        enabled=True,
        client=fake,
    )
    assert completed.status == STATUS_ERROR
    assert completed.restore_seconds == 0.2
    assert fake.prompts
    for hidden in ("s3cret", "db.internal", "postgresql://", "secret-row"):
        assert hidden not in fake.prompts[0]
    stored = _run(engine, completed.run_id)
    assert stored.status == STATUS_ERROR
    assert stored.note is None
    assert stored.acked_at is None
    assert stored.failure_category == "timeout"
    assert stored.failure_reason == _VALID["short_reason"]
    assert stored.failure_step == _VALID["suggested_next_step"]
    detail = _detail(settings, completed.run_id)
    assert detail["status"] == "error"
    assert detail["note"] is None
    assert detail["suggestion"] == {
        "suggestion": True,
        "category": "timeout",
        "short_reason": _VALID["short_reason"],
        "suggested_next_step": _VALID["suggested_next_step"],
    }
    assert posts[0]["suggestion"] == "true"
    assert posts[0]["suggestion_category"] == "timeout"
    assert posts[0]["suggestion_reason"] == _VALID["short_reason"]
    assert posts[0]["suggestion_step"] == _VALID["suggested_next_step"]
    assert "s3cret" not in posts[0]["suggestion_reason"]


def test_an_invalid_note_keeps_the_rule(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Fake("not json")
    completed, _posts = _drill(
        settings,
        tmp_path,
        monkeypatch,
        name="note-invalid",
        stderr=_STDERR,
        enabled=True,
        client=fake,
    )
    stored = _run(engine, completed.run_id)
    assert stored.status == STATUS_ERROR
    assert stored.failure_category == "unknown"
    assert stored.failure_reason == _UNKNOWN
    assert "not json" not in (stored.failure_reason or "")
    assert stored.note is None
    assert fake.prompts


def test_disabled_notes_make_no_call(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pgrestoredrill.notes.client.HttpNoteClient.complete",
        _forbid,
    )
    completed, posts = _drill(
        settings,
        tmp_path,
        monkeypatch,
        name="note-off",
        stderr=_STDERR,
        enabled=False,
        client=None,
    )
    stored = _run(engine, completed.run_id)
    assert stored.failure_category is None
    assert stored.failure_reason is None
    assert stored.failure_step is None
    assert stored.note is None
    assert set(posts[0]) == {"drill", "status", "reason", "run_id"}
    assert _detail(settings, completed.run_id)["suggestion"] is None


def test_a_rule_hit_makes_no_call(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pgrestoredrill.notes.client.HttpNoteClient.complete",
        _forbid,
    )
    completed, posts = _drill(
        settings,
        tmp_path,
        monkeypatch,
        name="note-rule",
        stderr="permission denied for schema public",
        enabled=True,
        client=None,
    )
    stored = _run(engine, completed.run_id)
    assert stored.status == STATUS_ERROR
    assert stored.failure_category == "permission denied"
    assert stored.note is None
    assert stored.acked_by is None
    assert posts[0]["suggestion"] == "true"
    assert posts[0]["suggestion_category"] == "permission denied"
    assert posts[0]["status"] == "error"


def _forbid(self: object, prompt: str) -> str:
    raise AssertionError("should not call")


def _drill(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    stderr: str,
    enabled: bool,
    client: _Fake | None,
) -> tuple[object, list[dict[str, str]]]:
    folder = tmp_path / "dumps"
    folder.mkdir()
    (folder / "fresh.dump").write_bytes(b"abcd")

    def fake_create(url: str) -> str:
        return swap_database(url, "pgrestoredrill_" + "cd" * 16)

    def fake_restore(path: Path, target: object, timeout: float) -> None:
        raise RestoreFailed(1, stderr, 0.2)

    monkeypatch.setattr("pgrestoredrill.targets.opening.create_drill_database", fake_create)
    monkeypatch.setattr("pgrestoredrill.runner.service.restore_dump", fake_restore)
    if client is not None:
        monkeypatch.setattr("pgrestoredrill.runner.service.client_for", lambda _settings: client)
    posts = _capture(monkeypatch)
    hooked = settings.model_copy(
        update={
            "notes_enabled": enabled,
            "notes_url": "https://api.x.ai/v1",
            "notes_model": "grok-4.7",
            "notes_api_key": "test-key",
            "alert_webhook_url": _HOOK,
        }
    )
    completed = execute_drill(hooked, local_config(tmp_path, name, folder))
    return completed, posts


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    posts: list[dict[str, str]] = []

    def post(url: str, payload: dict[str, str], timeout: float) -> int:
        assert url == _HOOK
        posts.append(dict(payload))
        return 204

    monkeypatch.setattr("pgrestoredrill.alerts.webhook.post_json", post)
    monkeypatch.setattr("pgrestoredrill.alerts.webhook.time.sleep", lambda seconds: None)
    return posts


def _run(engine: Engine, run_id: object) -> Run:
    assert run_id is not None
    with Session(engine) as session:
        stored = session.get(Run, run_id)
    assert stored is not None
    return stored


def _detail(settings: Settings, run_id: object) -> dict[str, object]:
    assert run_id is not None
    app = create_app(settings.model_copy(update={"admin_token": _TOKEN}))
    with TestClient(app) as client:
        response = client.get(f"/runs/{run_id}", headers=_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    return body
