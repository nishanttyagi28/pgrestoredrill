"""Errors the drill can show to an operator without secrets or dump data."""

from __future__ import annotations


class DrillError(Exception):
    """Base error for an expected drill failure."""


class DumpNotFound(DrillError):
    """No custom-format dump was found."""


class DumpSourceError(DrillError):
    """The dump source could not be read."""


class TargetNotDrillDatabase(DrillError):
    """The database name is not one created for a drill."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"refusing database {name} that was not created for the drill")


class TargetNotEmpty(DrillError):
    """The drill database already has user objects."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"target database {name} is not empty")


class TargetError(DrillError):
    """The target server could not be prepared."""


class RestoreFailed(DrillError):
    """pg_restore exited with an error."""

    def __init__(self, returncode: int, stderr_tail: str, duration_seconds: float) -> None:
        self.returncode = returncode
        self.stderr_tail = stderr_tail
        self.duration_seconds = duration_seconds
        detail = f": {stderr_tail}" if stderr_tail else ""
        super().__init__(f"pg_restore exited {returncode}{detail}")


class RestoreTimeout(DrillError):
    """pg_restore did not finish before the timeout."""

    def __init__(self, duration_seconds: float, stderr_tail: str) -> None:
        self.duration_seconds = duration_seconds
        self.stderr_tail = stderr_tail
        super().__init__(f"pg_restore timed out after {duration_seconds:.3f}s")
