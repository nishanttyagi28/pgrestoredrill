"""Quiet logs for every test."""

from __future__ import annotations

import pytest

from pgrestoredrill.logging import configure_logging


@pytest.fixture(autouse=True)
def _quiet_logs() -> None:
    configure_logging("ERROR")
