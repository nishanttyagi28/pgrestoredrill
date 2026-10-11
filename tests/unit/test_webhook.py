"""Webhook delivery retries and does not follow redirects."""

from __future__ import annotations

import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

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

    monkeypatch.setattr("pgrestoredrill.alerts.webhook._OPENER.open", fake_urlopen)
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

    monkeypatch.setattr("pgrestoredrill.alerts.webhook._OPENER.open", fake_urlopen)
    assert post_json("https://alerts.example/hook", _PAYLOAD, 5.0) == 502


def test_a_server_error_is_retried_until_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def post(url: str, payload: dict[str, str], timeout: float) -> int:
        nonlocal calls
        calls += 1
        assert url == "https://alerts.example/hook"
        assert payload == _PAYLOAD
        assert timeout == 5.0
        if calls == 1:
            return 503
        return 204

    monkeypatch.setattr("pgrestoredrill.alerts.webhook.post_json", post)
    monkeypatch.setattr("pgrestoredrill.alerts.webhook.time.sleep", sleeps.append)
    assert deliver("https://alerts.example/hook", _PAYLOAD) == 204
    assert calls == 2
    assert sleeps == [0.5]


def test_a_redirect_is_not_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    paths: list[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            paths.append(self.path)
            if self.path == "/hook":
                self.send_response(302)
                self.send_header("Location", "/gone")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever)
    thread.start()
    monkeypatch.setattr("pgrestoredrill.alerts.webhook.time.sleep", lambda seconds: None)
    try:
        code = deliver(f"http://127.0.0.1:{port}/hook", _PAYLOAD)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert code == 302
    assert paths == ["/hook", "/hook", "/hook"]
