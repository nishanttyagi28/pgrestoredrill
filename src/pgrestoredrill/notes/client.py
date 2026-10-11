"""One chat completion over HTTP. No vendor SDK and no retries."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.client import HTTPMessage
from typing import IO, Protocol

from pgrestoredrill.config import Settings

_TIMEOUT_SECONDS = 10.0


class NoteError(Exception):
    """The endpoint did not return usable text. The message has no URL or key."""

    def __init__(self) -> None:
        super().__init__("note request failed")


class NoteClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


_OPENER = urllib.request.build_opener(_RefuseRedirect())


class HttpNoteClient:
    def __init__(self, url: str, model: str, api_key: str) -> None:
        self._url = url.rstrip("/") + "/chat/completions"
        self._model = model
        self._api_key = api_key

    def complete(self, prompt: str) -> str:
        body = json.dumps(
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key != "":
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(self._url, data=body, headers=headers, method="POST")
        try:
            with _OPENER.open(request, timeout=_TIMEOUT_SECONDS) as response:
                raw = response.read()
                code = int(response.status)
        except urllib.error.HTTPError:
            raise NoteError from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise NoteError from None
        if code < 200 or code >= 300:
            raise NoteError
        return _content(raw)


def client_for(settings: Settings) -> NoteClient | None:
    if not settings.notes_enabled:
        return None
    model = settings.notes_model.strip()
    if settings.notes_url == "" or model == "":
        return None
    return HttpNoteClient(settings.notes_url, model, settings.notes_api_key)


def _content(raw: bytes) -> str:
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise NoteError from None
    if not isinstance(loaded, dict):
        raise NoteError
    choices = loaded.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise NoteError
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise NoteError
    content = message.get("content")
    if not isinstance(content, str) or content.strip() == "":
        raise NoteError
    return content
