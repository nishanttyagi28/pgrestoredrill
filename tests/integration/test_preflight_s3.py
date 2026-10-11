"""Empty and stale S3 listings are stored as failed runs and are not downloaded."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine

from pgrestoredrill.config import Settings
from tests.integration.preflight_helpers import refuse_s3_listing


def test_empty_s3_listing_is_refused_without_a_download(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refuse_s3_listing(
        settings,
        engine,
        tmp_path,
        monkeypatch,
        name="empty-s3",
        key="backups/empty.dump",
        modified=datetime.now(UTC),
        size=0,
        min_bytes=100,
        reason="dump is empty",
    )


def test_stale_s3_listing_is_refused_without_a_download(
    settings: Settings,
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refuse_s3_listing(
        settings,
        engine,
        tmp_path,
        monkeypatch,
        name="stale-s3",
        key="backups/old.dump",
        modified=datetime.now(UTC) - timedelta(days=2),
        size=3,
        max_age_minutes=60,
        reason="dump is older than max_age_minutes",
    )
