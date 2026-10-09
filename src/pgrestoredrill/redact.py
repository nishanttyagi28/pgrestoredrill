"""Remove passwords from text before it is stored or printed."""

from __future__ import annotations

import re

_URL_PASSWORD = re.compile(
    r"([a-z][a-z0-9+.-]*://[^/\s:]+:)([^@\s]+)@",
    re.IGNORECASE,
)
_QUERY_PASSWORD = re.compile(r"(?i)(password=)([^&\s]+)")


def redact(text: str) -> str:
    hidden = _URL_PASSWORD.sub(r"\1***@", text)
    return _QUERY_PASSWORD.sub(r"\1***", hidden)
