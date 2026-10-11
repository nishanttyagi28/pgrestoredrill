"""Webhook delivery retries without opening a socket."""

from __future__ import annotations

import urllib.error

import pytest

from pgrestoredrill.alerts.webhook import deliver, post_json

_PAYLOAD = {"drill": "orders", "status": "failed", "reason": "dump is empty", "run_id": "run-1"}


def test_delivery_stops_on_the_first_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []
    sleeps: list[float] = []

    def post(url: str, payload: dict[str, str], timeout: float) -> int:
        assert url == "https://alerts.example/hook"
        assert payload == _PAYLOAD
        calls.append(timeout)
        return 204

    monkeypatch.setattr("pgrestoredrill.alerts.webhook.post_json", post)
    monkeypatch.setattr("pgrestoredrill.alerts.webhook.time.sleep", sleeps.append)
    assert deliver("https://alerts.example/hook", _PAYLOAD) == 204
    assert calls == [5.0]
    assert sleeps == []


def test_delivery_retries_then_returns_the_last_status(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def post(url: str, payload: dict[str, str], timeout: float) -> int:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise urllib.error.URLError("down")
        return 503

    monkeypatch.setattr("pgrestoredrill.alerts.webhook.post_json", post)
    monkeypatch.setattr("pgrestoredrill.alerts.webhook.time.sleep", sleeps.append)
    assert deliver("https://alerts.example/hook", _PAYLOAD) == 503
    assert calls == 3
    assert sleeps == [0.5, 1.0]


def test_post_json_reads_the_response_status(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response:
        status = 202

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    seen: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _Response:
        seen["url"] = request.full_url
        seen["method"] = request.method
        seen["body"] = request.data
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("pgrestoredrill.alerts.webhook.urllib.request.urlopen", fake_urlopen)
    assert post_json("https://alerts.example/hook", _PAYLOAD, 5.0) == 202
    body = seen["body"]
    assert isinstance(body, bytes)
    assert b"dump_key" not in body
    assert b"https://alerts.example" not in body
    assert seen["timeout"] == 5.0
    assert seen["method"] == "POST"


def test_post_json_returns_an_http_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float) -> object:
        raise urllib.error.HTTPError(request.full_url, 502, "bad", hdrs=None, fp=None)

    monkeypatch.setattr("pgrestoredrill.alerts.webhook.urllib.request.urlopen", fake_urlopen)
    assert post_json("https://alerts.example/hook", _PAYLOAD, 5.0) == 502
