"""Build the only text a failure note may send to a model."""

from __future__ import annotations

import re
from collections.abc import Sequence

from pgrestoredrill.notes.schema import CATEGORIES
from pgrestoredrill.redact import redact

_TAIL_LIMIT = 2000
_DIAGNOSTIC = re.compile(r"(?i)\b(?:DETAIL|CONTEXT)\s*:")
_KEY_VALUE = re.compile(r"(?i)(Key\s*\([^)]*\)\s*=\s*)(?:\([^)\n]*\)|\S+)")
_COPY_ROW = re.compile(r"(?i)(COPY\s+\S+,\s*line\s+\d+\s*:).*")
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\b")
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
_SECRET = re.compile(
    r"(?i)\b(password|passwd|pwd|pgpassword|secret|token|api_key)"
    r"\s*=\s*('[^']*'|\"[^\"]*\"|\S+)"
)
_HOST_ASSIGN = re.compile(r"(?i)\b(host|hostname|hostaddr)\s*=\s*('[^']*'|\"[^\"]*\"|\S+)")
_ROW = re.compile(r"(?i)\b(observed|expected)\s*=\s*('[^']*'|\"[^\"]*\"|\S+)")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6 = re.compile(
    r"(?i)(?<![0-9a-f:])(?:"
    r"(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}|"
    r"(?:[0-9a-f]{1,4}:){1,7}:|"
    r"(?:[0-9a-f]{1,4}:){1,6}:[0-9a-f]{1,4}|"
    r"(?:[0-9a-f]{1,4}:){1,5}(?::[0-9a-f]{1,4}){1,2}|"
    r"(?:[0-9a-f]{1,4}:){1,4}(?::[0-9a-f]{1,4}){1,3}|"
    r"(?:[0-9a-f]{1,4}:){1,3}(?::[0-9a-f]{1,4}){1,4}|"
    r"(?:[0-9a-f]{1,4}:){1,2}(?::[0-9a-f]{1,4}){1,5}|"
    r"[0-9a-f]{1,4}:(?:(?::[0-9a-f]{1,4}){1,6})|"
    r":(?:(?::[0-9a-f]{1,4}){1,7}|:)"
    r")(?![0-9a-f:])"
)
_HOST_QUOTE = re.compile(r'(?i)(\bhost(?:\s+name)?\s+")([^"]*)(")')
_SK = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
_LONG_TOKEN = re.compile(r"\b(?:[A-Za-z0-9+/]{24,}={0,2}|[0-9a-fA-F]{24,})\b")
_HOSTNAME = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.IGNORECASE)
_LOCALHOST = re.compile(r"\blocalhost\b", re.IGNORECASE)


def mask_secrets(text: str) -> str:
    hidden = redact(text)
    hidden = _without_diagnostics(hidden)
    hidden = _KEY_VALUE.sub(r"\1***", hidden)
    hidden = _COPY_ROW.sub(r"\1 [redacted]", hidden)
    hidden = _EMAIL.sub("[redacted]", hidden)
    hidden = _URL.sub("[redacted]", hidden)
    hidden = _SECRET.sub(r"\1=***", hidden)
    hidden = _HOST_ASSIGN.sub(r"\1=***", hidden)
    hidden = _ROW.sub(r"\1=***", hidden)
    hidden = _IPV4.sub("[redacted]", hidden)
    hidden = _IPV6.sub("[redacted]", hidden)
    hidden = _HOST_QUOTE.sub(r"\1[redacted]\3", hidden)
    hidden = _SK.sub("[redacted]", hidden)
    hidden = _LONG_TOKEN.sub("[redacted]", hidden)
    hidden = _HOSTNAME.sub("[redacted]", hidden)
    return _LOCALHOST.sub("[redacted]", hidden)


def _without_diagnostics(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        match = _DIAGNOSTIC.search(line)
        if match is None:
            kept.append(line)
            continue
        prefix = line[: match.start()].rstrip(" ,")
        if prefix:
            kept.append(prefix)
    return "\n".join(kept)


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
