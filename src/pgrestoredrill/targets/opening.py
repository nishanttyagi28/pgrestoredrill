"""Choose the restore target. Docker is refused inside Kubernetes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from pgrestoredrill.config import Settings
from pgrestoredrill.errors import TargetError
from pgrestoredrill.targets.docker import docker_database
from pgrestoredrill.targets.external import create_drill_database
from pgrestoredrill.targets.k8s_sidecar import prepare_sidecar


@contextmanager
def open_restore_url(settings: Settings) -> Iterator[str]:
    """Yield a libpq URL for one empty drill database."""
    if settings.target_kind == "external":
        yield create_drill_database(settings.target_url)
        return
    if settings.target_kind == "docker":
        with docker_database() as url:
            yield url
        return
    if settings.target_kind == "k8s-sidecar":
        yield prepare_sidecar(
            user=settings.sidecar_user,
            password=settings.sidecar_password,
            host=settings.sidecar_host,
            port=settings.sidecar_port,
        )
        return
    raise TargetError("unknown target")
