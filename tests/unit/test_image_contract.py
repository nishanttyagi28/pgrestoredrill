"""The image and compose file stay pinned and do not bake a secret."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_is_pinned_and_checks_health() -> None:
    text = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    digest = "sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1"
    assert f"python:3.12-slim@{digest}" in text
    uv = "sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a"
    assert f"ghcr.io/astral-sh/uv:0.12.24@{uv}" in text
    assert "COPY --from=ghcr.io/astral-sh/uv:0.12.24@" in text
    assert "/uv /usr/local/bin/uv" in text
    assert "install.sh" not in text
    assert "chown" not in text
    assert "postgresql-client-17" in text
    assert "postgresql-client-16" not in text
    assert "HEALTHCHECK" in text
    assert "/healthz" in text
    assert "USER 10001" in text
    assert "ADMIN_TOKEN" not in text
    assert "POSTGRES_PASSWORD=" not in text
    ignored = (_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert ".env" in ignored.splitlines()


def test_compose_adds_silo_target_api_and_a_one_shot_drill() -> None:
    text = (_ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "pgsty/silo:RELEASE.2026-09-16T00-00-00Z@" in text
    assert "sha256:635197cb9f36d01bee221d34d1c7d7960f6a95c48b0b6c01d99cd13bdae51a46" in text
    assert "\n  target:\n" in text
    assert '["pgrestoredrill", "run", "--config", "/drill/drill.yaml"]' in text
    assert 'profiles: ["drill"]' in text
    postgres = "postgres:16@sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d"
    assert text.count(postgres) == 2
