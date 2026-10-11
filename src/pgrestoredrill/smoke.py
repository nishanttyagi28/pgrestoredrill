"""Checks used by the kind smoke test."""

from __future__ import annotations

CLUSTER = "pgrestoredrill-smoke"


def require_smoke_cluster(name: str) -> str:
    """Refuse to delete or create any cluster except the smoke cluster."""
    if name != CLUSTER:
        raise RuntimeError("refusing to touch this cluster")
    return name


def require_passed(runs: object) -> None:
    """Raise unless the newest run passed. The API returns newest first."""
    if not isinstance(runs, list) or not runs:
        raise RuntimeError("drill did not pass")
    newest = runs[0]
    if not isinstance(newest, dict) or newest.get("status") != "passed":
        raise RuntimeError("drill did not pass")
