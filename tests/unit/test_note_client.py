"""The note client is one HTTP POST and does not follow a redirect."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest
from pydantic import ValidationError

from pgrestoredrill.config import Settings
from pgrestoredrill.notes.client import HttpNoteClient, NoteError, client_for

_DATABASE = "postgresql://localhost/pgrestoredrill"
_TARGET = "postgresql://localhost/postgres"
_KEY = "test-key"


def test_client_for_is_off_until_the_endpoint_and_model_are_set() -> None:
    quiet = _settings(False)
    assert client_for(quiet) is None
    assert "api.x.ai" not in repr(quiet)
    assert _KEY not in repr(quiet)
    missing_model = _settings(True).model_copy(update={"notes_model": "  "})
    assert client_for(missing_model) is None
    hooked = _settings(True)
    client = client_for(hooked)
    assert isinstance(client, HttpNoteClient)


def test_notes_url_rejects_userinfo_without_echoing_the_secret() -> None:
    with pytest.raises(ValidationError) as caught:
        _settings(True, url="http://user:s3cret@notes.example/v1")
    assert caught.value.errors()[0]["msg"] == "Value error, invalid notes url"
    assert "s3cret" not in caught.value.errors()[0]["msg"]


def test_complete_reads_the_message_content() -> None:
    content = json.dumps(
        {
            "category": "unknown",
            "short_reason": "the restore stopped",
            "suggested_next_step": "read the restore error",
        }
    )
    seen: dict[str, object] = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = raw
            body = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server, thread = _serve(_Handler)
    try:
        port = server.server_address[1]
        text = HttpNoteClient(f"http://127.0.0.1:{port}/v1", "grok-4.7", _KEY).complete("classify")
    finally:
        _stop(server, thread)
    assert text == content
    assert seen["path"] == "/v1/chat/completions"
    assert seen["auth"] == f"Bearer {_KEY}"
    body = seen["body"]
    assert isinstance(body, bytes)
    assert b"s3cret" not in body
    assert b'"stream":false' in body


def test_a_redirect_is_one_failed_attempt() -> None:
    paths: list[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            paths.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/secret")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server, thread = _serve(_Handler)
    try:
        port = server.server_address[1]
        with pytest.raises(NoteError) as caught:
            HttpNoteClient(f"http://127.0.0.1:{port}/v1", "grok-4.7", _KEY).complete("classify")
    finally:
        _stop(server, thread)
    assert paths == ["/v1/chat/completions"]
    assert str(caught.value) == "note request failed"
    assert _KEY not in str(caught.value)


def _settings(enabled: bool, url: str = "https://api.x.ai/v1") -> Settings:
    return Settings(
        database_url=_DATABASE,
        target_url=_TARGET,
        log_level="INFO",
        notes_enabled=enabled,
        notes_url=url,
        notes_model="grok-4.7",
        notes_api_key=_KEY,
    )


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[HTTPServer, Thread]:
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    return server, thread


def _stop(server: HTTPServer, thread: Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
