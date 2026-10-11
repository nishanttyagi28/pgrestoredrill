"""Kind smoke checks."""

from __future__ import annotations

import pytest

from pgrestoredrill.smoke import require_passed, require_smoke_cluster


def test_only_the_smoke_cluster_can_be_removed() -> None:
    assert require_smoke_cluster("pgrestoredrill-smoke") == "pgrestoredrill-smoke"
    with pytest.raises(RuntimeError, match="refusing"):
        require_smoke_cluster("prod")


def test_newest_run_must_have_passed() -> None:
    require_passed([{"status": "passed"}, {"status": "failed"}])
    with pytest.raises(RuntimeError, match="did not pass"):
        require_passed([{"status": "failed"}])
    with pytest.raises(RuntimeError, match="did not pass"):
        require_passed([])
    with pytest.raises(RuntimeError, match="did not pass"):
        require_passed({"status": "passed"})
