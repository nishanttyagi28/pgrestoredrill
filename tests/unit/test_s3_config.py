"""S3 drill settings. These tests do not open a network connection."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from pgrestoredrill.config import Settings
from pgrestoredrill.errors import DumpSourceError
from pgrestoredrill.runner.spec import load_drill
from pgrestoredrill.sources.s3 import open_s3_store


def test_open_store_passes_settings_and_quiets_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    botocore_logger = logging.getLogger("botocore")
    previous = botocore_logger.level
    botocore_logger.setLevel(logging.DEBUG)

    def client(service_name: str, **kwargs: object) -> object:
        captured["service"] = service_name
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("pgrestoredrill.sources.s3.boto3.client", client)
    try:
        open_s3_store(
            endpoint_url="http://127.0.0.1:9",
            region="us-east-1",
            access_key="test-key",
            secret_key="test-secret",
        )
        assert botocore_logger.level == logging.WARNING
        empty: dict[str, object] = {}

        def client_again(service_name: str, **kwargs: object) -> object:
            empty["kwargs"] = kwargs
            return object()

        monkeypatch.setattr("pgrestoredrill.sources.s3.boto3.client", client_again)
        open_s3_store(endpoint_url="", region="", access_key="", secret_key="")
    finally:
        botocore_logger.setLevel(previous)
    assert captured["service"] == "s3"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["endpoint_url"] == "http://127.0.0.1:9"
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["aws_access_key_id"] == "test-key"
    assert kwargs["aws_secret_access_key"] == "test-secret"
    assert empty["kwargs"] == {
        "region_name": None,
        "endpoint_url": None,
        "aws_access_key_id": None,
        "aws_secret_access_key": None,
    }


def test_incomplete_credentials_do_not_open_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def client(service_name: str, **kwargs: object) -> object:
        raise AssertionError("client should not be created")

    monkeypatch.setattr("pgrestoredrill.sources.s3.boto3.client", client)
    with pytest.raises(DumpSourceError, match="s3 credentials are incomplete"):
        open_s3_store(
            endpoint_url="http://127.0.0.1:9",
            region=None,
            access_key="test-key",
            secret_key=None,
        )


def test_s3_drill_file_and_rejected_endpoint(tmp_path: Path) -> None:
    good = tmp_path / "good.yaml"
    good.write_text(_drill(endpoint="http://127.0.0.1:9000"), encoding="utf-8")
    drill = load_drill(good)
    assert drill.source_kind == "s3"
    assert drill.bucket == "drills"
    assert drill.source_uri == "backups/"
    assert drill.endpoint_url == "http://127.0.0.1:9000"
    assert drill.region == "us-east-1"
    bad = tmp_path / "bad.yaml"
    bad.write_text(_drill(endpoint="http://user:test-secret@127.0.0.1:9000"), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid drill config") as caught:
        load_drill(bad)
    assert "test-secret" not in str(caught.value)
    missing = tmp_path / "missing.yaml"
    text = _drill(endpoint="http://127.0.0.1:9000").replace("bucket: drills\n", "")
    missing.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="invalid drill config"):
        load_drill(missing)


def test_s3_credentials_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    monkeypatch.setenv("TARGET_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    monkeypatch.setenv("S3_ACCESS_KEY", "test-key")
    monkeypatch.setenv("S3_SECRET_KEY", "test-secret")
    settings = Settings()
    assert settings.s3_access_key == "test-key"
    assert settings.s3_secret_key == "test-secret"
    assert "test-secret" not in repr(settings)


def test_example_s3_drill_loads() -> None:
    drill = load_drill(Path("examples/s3-drill.yaml"))
    assert drill.source_kind == "s3"
    assert drill.bucket == "pgrestoredrill"
    assert drill.endpoint_url == "http://127.0.0.1:9000"


def _drill(*, endpoint: str) -> str:
    return "\n".join(
        [
            "name: sample-s3",
            "source_kind: s3",
            "source_uri: backups/",
            "bucket: drills",
            f"endpoint_url: {endpoint}",
            "region: us-east-1",
            "rpo_minutes: 60",
            "assertions_file: assertions.yaml",
            "",
        ]
    )
