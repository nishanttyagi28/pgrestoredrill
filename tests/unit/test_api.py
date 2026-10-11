"""API auth without a database connection."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pgrestoredrill.api.app import create_app
from pgrestoredrill.api.auth import tokens_match
from pgrestoredrill.api.state import get_state
from pgrestoredrill.config import Settings

_TOKEN = "test-token"
_URL = "postgresql://postgres:postgres@127.0.0.1:1/postgres"


def test_tokens_match_only_when_both_sides_are_equal() -> None:
    assert tokens_match(_TOKEN, _TOKEN) is True
    assert tokens_match("other-token", _TOKEN) is False
    assert tokens_match("short", _TOKEN) is False
    assert tokens_match("", _TOKEN) is False
    assert tokens_match(_TOKEN, "") is False
    assert tokens_match("a" * 513, "a" * 513) is False


def test_health_and_missing_routes_do_not_require_a_token() -> None:
    with TestClient(_app()) as client:
        health = client.get("/healthz")
        missing = client.post("/drills")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert missing.status_code == 405


def test_history_routes_reject_a_missing_or_wrong_token() -> None:
    with TestClient(_app()) as client:
        missing = client.get("/drills")
        wrong = client.get("/drills", headers={"Authorization": "Bearer wrong-token"})
        basic = client.get("/drills", headers={"Authorization": "Basic test-token"})
        zero = client.get(f"/drills/{uuid4()}/runs?limit=0", headers=_auth())
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert basic.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert "test-token" not in missing.text
    assert "wrong-token" not in wrong.text
    assert zero.status_code == 422


def test_empty_admin_token_rejects_every_bearer_token() -> None:
    with TestClient(_app("")) as client:
        response = client.get("/drills", headers=_auth())
    assert response.status_code == 401
    assert "test-token" not in response.text


def test_metrics_without_an_engine_is_unavailable() -> None:
    app = _app()
    with TestClient(app) as client:
        get_state(app).engine = None
        response = client.get("/metrics")
    assert response.status_code == 503
    assert response.json()["detail"] == "metadata database is unavailable"
    assert "postgresql" not in response.text
    assert "127.0.0.1" not in response.text


def test_create_app_reads_the_admin_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", _URL)
    monkeypatch.setenv("TARGET_URL", _URL)
    monkeypatch.setenv("ADMIN_TOKEN", _TOKEN)
    app = create_app()
    assert get_state(app).settings.admin_token == _TOKEN
    assert _TOKEN not in repr(get_state(app).settings)


def _app(token: str = _TOKEN) -> FastAPI:
    return create_app(
        Settings(
            database_url=_URL,
            target_url=_URL,
            log_level="INFO",
            admin_token=token,
        )
    )


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_TOKEN}"}
