"""Failure notes stay on the rule unless a valid model reply replaces an unknown one."""

from __future__ import annotations

import json

from pgrestoredrill.assertions.models import AssertionOutcome
from pgrestoredrill.notes.classify import classify
from pgrestoredrill.notes.compose import resolve_note
from pgrestoredrill.notes.prompt import build_prompt
from pgrestoredrill.notes.schema import FailureNote, parse_note

_VALID = {
    "category": "timeout",
    "short_reason": "the restore stopped",
    "suggested_next_step": "raise the timeout and run the drill again",
}


class _Fake:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.text == "boom":
            raise RuntimeError("boom")
        return self.text


def test_rules_match_stderr_in_order() -> None:
    cases = (
        ("unrecognized configuration parameter transaction_timeout", "version mismatch"),
        ("unsupported version in header", "version mismatch"),
        ("server version mismatch", "version mismatch"),
        ("dump is from Postgres 17", "version mismatch"),
        ("no space left on device", "disk full"),
        ("disk full", "disk full"),
        ("permission denied for table customers", "permission denied"),
        ("must be owner of relation customers", "permission denied"),
        ("canceling statement due to statement timeout", "timeout"),
        ("pg_restore timed out after 1.000s", "timeout"),
        ('extension "postgis" does not exist', "missing extension"),
        ("extension not available", "missing extension"),
        ("could not open extension control file", "missing extension"),
        ('role "app" does not exist', "missing role"),
        ("dump is empty", "unknown"),
        ("extension control file", "unknown"),
        ("role lookup failed", "unknown"),
    )
    for stderr, category in cases:
        assert classify(stderr, ()).category == category


def test_a_failed_assertion_wins_over_stderr() -> None:
    note = classify("permission denied", (_outcome("customers_present", passed=False),))
    assert note.category == "assertion failed"
    assert "customers_present" not in note.short_reason


def test_parse_keeps_only_the_strict_object() -> None:
    parsed = parse_note(json.dumps(_VALID))
    assert parsed == FailureNote.model_validate(_VALID)
    padded = dict(_VALID)
    padded["short_reason"] = "  the restore stopped  "
    assert parse_note(json.dumps(padded)) == parsed
    too_long = dict(_VALID)
    too_long["short_reason"] = "x" * 301
    extra = dict(_VALID)
    extra["confidence"] = "high"
    blank = dict(_VALID)
    blank["suggested_next_step"] = "   "
    wrong = dict(_VALID)
    wrong["category"] = "network"
    rejected = (
        "not-json",
        "[]",
        json.dumps(too_long),
        json.dumps(extra),
        json.dumps(blank),
        json.dumps(wrong),
    )
    for raw in rejected:
        assert parse_note(raw) is None


def test_the_prompt_keeps_names_and_drops_secrets() -> None:
    stderr = (
        "postgresql://postgres:s3cret@db.internal:5432/app "
        "password=s3cret host=db.internal localhost "
        "observed=secret-row alice@example.com 10.1.2.3"
    )
    prompt = build_prompt(stderr, ["customers_present"])
    for hidden in (
        "s3cret",
        "db.internal",
        "postgresql://",
        "localhost",
        "secret-row",
        "alice",
        "example.com",
        "10.1.2.3",
    ):
        assert hidden not in prompt
    assert "customers_present" in prompt
    assert "observed=***" in prompt


def test_disabled_and_a_rule_hit_do_not_call() -> None:
    client = _Fake(json.dumps(_VALID))
    assert resolve_note(False, "mystery failure", (), client) is None
    rule = resolve_note(True, "permission denied", (), client)
    assert rule is not None
    assert rule.category == "permission denied"
    assert client.prompts == []


def test_unknown_keeps_a_valid_reply_and_drops_anything_else() -> None:
    valid = _Fake(json.dumps(_VALID))
    stored = resolve_note(True, "mystery failure", (_outcome("present", passed=True),), valid)
    assert stored == FailureNote.model_validate(_VALID)
    assert valid.prompts
    assert "present" in valid.prompts[0]
    assert "secret-row" not in valid.prompts[0]
    for reply in ("nope", json.dumps({"category": "nope"}), "boom"):
        client = _Fake(reply)
        kept = resolve_note(True, "mystery failure", (), client)
        assert kept is not None
        assert kept.category == "unknown"
        assert len(client.prompts) == 1


def test_a_missing_client_keeps_the_unknown_rule() -> None:
    note = resolve_note(True, "mystery failure", (), None)
    assert note is not None
    assert note.category == "unknown"


def _outcome(name: str, *, passed: bool) -> AssertionOutcome:
    return AssertionOutcome(
        name=name,
        passed=passed,
        observed="secret-row",
        expected="2",
        duration_ms=1,
    )
