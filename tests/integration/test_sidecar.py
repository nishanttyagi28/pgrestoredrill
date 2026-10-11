"""The sidecar uses the same empty-database check as an external target."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from pgrestoredrill.db.session import connect
from pgrestoredrill.db.urls import database_name
from pgrestoredrill.errors import TargetNotEmpty
from pgrestoredrill.targets.external import drop_database, ensure_restore_allowed, is_drill_database
from pgrestoredrill.targets.k8s_sidecar import prepare_sidecar


def test_sidecar_database_must_be_empty(admin_url: str) -> None:
    parts = urlsplit(admin_url)
    assert parts.hostname is not None
    assert parts.username is not None
    assert parts.password is not None
    url = prepare_sidecar(
        user=parts.username,
        password=parts.password,
        host=parts.hostname,
        port=parts.port or 5432,
        attempts=3,
        pause=0.1,
    )
    name = database_name(url)
    try:
        assert is_drill_database(name) is True
        ensure_restore_allowed(url)
        with connect(url, autocommit=True) as connection:
            connection.execute("CREATE TABLE extra (id integer)")
        with pytest.raises(TargetNotEmpty):
            ensure_restore_allowed(url)
    finally:
        drop_database(admin_url, name)
