"""Build the only text a failure note may send to a model."""

from __future__ import annotations

import re
from collections.abc import Sequence

from pgrestoredrill.notes.schema import CATEGORIES
from pgrestoredrill.redact import redact

_TAIL_LIMIT = 2000
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\b")
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
_SECRET = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api_key)\s*=\s*('[^']*'|\"[^\"]*\"|\S+)"
)
_HOST_ASSIGN = re.compile(r"(?i)\b(host|hostname|hostaddr)\s*=\s*('[^']*'|\"[^\"]*\"|\S+)")
_ROW = re.compile(r"(?i)\b(observed|expected)\s*=\s*('[^']*'|\"[^\"]*\"|\S+)")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_HOSTNAME = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.IGNORECASE)
_LOCALHOST = re.compile(r"\blocalhost\b", re.IGNORECASE)


def mask_secrets(text: str) -> str:
    hidden = redact(text)
    hidden = _EMAIL.sub("[redacted]", hidden)
    hidden = _URL.sub("[redacted]", hidden)
    hidden = _SECRET.sub(r"\1=***", hidden)
    hidden = _HOST_ASSIGN.sub(r"\1=***", hidden)
    hidden = _ROW.sub(r"\1=***", hidden)
    hidden = _IPV4.sub("[redacted]", hidden)
    hidden = _HOSTNAME.sub("[redacted]", hidden)
    return _LOCALHOST.sub("[redacted]", hidden)


def build_prompt(stderr_tail: str, assertion_names: Sequence[str]) -> str:
    masked = mask_secrets(stderr_tail)[-_TAIL_LIMIT:]
    names = ", ".join(assertion_names) if assertion_names else "none"
    labels = ", ".join(CATEGORIES)
    return (
        "Classify this restore failure. Reply with one JSON object and nothing else. "
        "Keys are category, short_reason, and suggested_next_step. "
        f"category is one of: {labels}. "
        "Each value is at most 300 characters. "
        f"Assertion names: {names}. "
        f"Restore stderr: {masked}"
    )
