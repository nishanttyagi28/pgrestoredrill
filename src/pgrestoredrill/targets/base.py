"""Restore target interface."""

from __future__ import annotations

from typing import Protocol


class TargetProvider(Protocol):
    """A database created for one drill run."""

    def assert_empty(self) -> None:
        """Raise when this database must not be restored into."""

    def restore_url(self) -> str:
        """Libpq URL for pg_restore. Callers must not log it."""
