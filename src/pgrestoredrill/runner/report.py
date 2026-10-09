"""Human summary of one drill run."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pgrestoredrill.assertions.models import AssertionOutcome


@dataclass(frozen=True)
class CompletedRun:
    status: str
    drill_name: str
    run_id: UUID | None
    database_name: str | None
    dump_path: str | None
    dump_bytes: int | None
    dump_sha256: str | None
    restore_seconds: float | None
    error: str | None
    assertions: tuple[AssertionOutcome, ...]


def format_summary(run: CompletedRun) -> str:
    lines = [f"status: {run.status}", f"drill: {run.drill_name}"]
    if run.run_id is not None:
        lines.append(f"run_id: {run.run_id}")
    if run.database_name:
        lines.append(f"database: {run.database_name}")
    if run.dump_path:
        lines.append(f"dump: {run.dump_path}")
    if run.dump_bytes is not None:
        lines.append(f"bytes: {run.dump_bytes}")
    if run.dump_sha256:
        lines.append(f"sha256: {run.dump_sha256}")
    if run.restore_seconds is not None:
        lines.append(f"restore_seconds: {run.restore_seconds:.3f}")
    if run.error:
        lines.append(f"error: {' '.join(run.error.split())}")
    if run.assertions:
        lines.append("assertions:")
        for item in run.assertions:
            state = "passed" if item.passed else "failed"
            observed = "null" if item.observed is None else item.observed
            lines.append(
                f"  {item.name} {state} observed={observed} "
                f"expected={item.expected} {item.duration_ms}ms"
            )
    return "\n".join(lines)
