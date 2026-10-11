"""Label a failure from stderr and assertion results. The first match wins."""

from __future__ import annotations

from collections.abc import Sequence

from pgrestoredrill.assertions.models import AssertionOutcome
from pgrestoredrill.notes.schema import (
    ASSERTION_FAILED,
    DISK_FULL,
    MISSING_EXTENSION,
    MISSING_ROLE,
    PERMISSION_DENIED,
    TIMEOUT,
    UNKNOWN,
    VERSION_MISMATCH,
    Category,
    FailureNote,
)

_TEXT: dict[Category, tuple[str, str]] = {
    ASSERTION_FAILED: (
        "a read-only assertion did not match the restored data",
        "compare that assertion with the restored data and fix the dump or the check",
    ),
    VERSION_MISMATCH: (
        "the dump was made by a newer postgres than this restore client",
        "restore with a client at least as new as the dump, or take the dump again",
    ),
    DISK_FULL: (
        "the restore server ran out of disk space",
        "free disk space on the restore server and run the drill again",
    ),
    PERMISSION_DENIED: (
        "the restore role is not allowed to create an object in the dump",
        "grant the restore role the missing privilege and run the drill again",
    ),
    TIMEOUT: (
        "the restore or a statement did not finish before its timeout",
        "raise the restore timeout or the statement timeout and run the drill again",
    ),
    MISSING_EXTENSION: (
        "the dump needs an extension that is not installed on the restore server",
        "install the missing extension and run the drill again",
    ),
    MISSING_ROLE: (
        "the dump refers to a role that does not exist on the restore server",
        "create the missing role and run the drill again",
    ),
    UNKNOWN: (
        "the failure did not match a known restore error",
        "read the restore error and compare the dump with this server",
    ),
}


def classify(stderr_tail: str, assertions: Sequence[AssertionOutcome]) -> FailureNote:
    category = _category(stderr_tail.lower(), assertions)
    reason, step = _TEXT[category]
    return FailureNote(category=category, short_reason=reason, suggested_next_step=step)


def _category(text: str, assertions: Sequence[AssertionOutcome]) -> Category:
    if any(not item.passed for item in assertions):
        return ASSERTION_FAILED
    if _version(text):
        return VERSION_MISMATCH
    if "no space left" in text or "disk full" in text:
        return DISK_FULL
    if "permission denied" in text or "must be owner" in text:
        return PERMISSION_DENIED
    if "timeout" in text or "timed out" in text:
        return TIMEOUT
    if _extension(text):
        return MISSING_EXTENSION
    if "role" in text and "does not exist" in text:
        return MISSING_ROLE
    return UNKNOWN


def _version(text: str) -> bool:
    return (
        "unsupported version" in text
        or "transaction_timeout" in text
        or "dump is from postgres" in text
        or "server version mismatch" in text
    )


def _extension(text: str) -> bool:
    if "extension" not in text:
        return False
    return "does not exist" in text or "not available" in text or "could not open" in text
