"""Use the rules first. Call a model only for an unknown failure, and only when enabled."""

from __future__ import annotations

from collections.abc import Sequence

from pgrestoredrill.assertions.models import AssertionOutcome
from pgrestoredrill.notes.classify import classify
from pgrestoredrill.notes.client import NoteClient
from pgrestoredrill.notes.prompt import build_prompt
from pgrestoredrill.notes.schema import UNKNOWN, FailureNote, parse_note


def resolve_note(
    enabled: bool,
    stderr_tail: str,
    assertions: Sequence[AssertionOutcome],
    client: NoteClient | None,
) -> FailureNote | None:
    if not enabled:
        return None
    rule = classify(stderr_tail, assertions)
    if rule.category != UNKNOWN or client is None:
        return rule
    try:
        raw = client.complete(build_prompt(stderr_tail, [item.name for item in assertions]))
    except Exception:
        return rule
    parsed = parse_note(raw)
    if parsed is None:
        return rule
    return parsed
