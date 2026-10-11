"""POST one JSON alert. The webhook URL is never logged."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from http.client import HTTPMessage
from typing import IO

_ATTEMPTS = 3
_TIMEOUT_SECONDS = 5.0
_BACKOFF_SECONDS = (0.5, 1.0)


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx response is a failed attempt. The Location is not requested."""

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


def deliver(url: str, payload: Mapping[str, str]) -> int | None:
    last: int | None = None
    for attempt in range(_ATTEMPTS):
        if attempt:
            time.sleep(_BACKOFF_SECONDS[attempt - 1])
        try:
            last = post_json(url, payload, _TIMEOUT_SECONDS)
        except (urllib.error.URLError, TimeoutError, OSError):
            last = None
            continue
        if 200 <= last < 300:
            return last
    return last


def post_json(url: str, payload: Mapping[str, str], timeout: float) -> int:
    body = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
