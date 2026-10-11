"""Errors the drill can show to an operator without secrets or dump data."""

from __future__ import annotations


class DrillError(Exception):
    """Base error for an expected drill failure."""


class DumpNotFound(DrillError):
    """No custom-format dump was found."""


class DumpSourceError(DrillError):
    """The dump source could not be read."""


class DumpRejected(DrillError):
    """The listed dump failed a size or age check and was not downloaded."""

    def __init__(self, reason: str, key: str, size: int) -> None:
        self.key = key
        self.size = size
        super().__init__(reason)


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


class RunNotFound(DrillError):
    """No run has this id."""

    def __init__(self) -> None:
        super().__init__("run not found")


class DrillNotFound(DrillError):
    """No drill has this id."""

    def __init__(self) -> None:
        super().__init__("drill not found")


class AckNotAllowed(DrillError):
    """Only a failed or errored run can be acked."""

    def __init__(self) -> None:
        super().__init__("only a failed or error run can be acked")


class AlreadyAcked(DrillError):
    """This run was already acked."""

    def __init__(self) -> None:
        super().__init__("run is already acked")


class AckInvalid(DrillError):
    """The ack name or note is empty or too long."""

    def __init__(self) -> None:
        super().__init__("ack needs a name and a short note")


class RestoreTimeout(DrillError):
    """pg_restore did not finish before the timeout."""

    def __init__(self, duration_seconds: float, stderr_tail: str) -> None:
        self.duration_seconds = duration_seconds
        self.stderr_tail = stderr_tail
        super().__init__(f"pg_restore timed out after {duration_seconds:.3f}s")
