.PHONY: install lint type test run drill migrate fixture up down kind-smoke

install:
	uv sync --all-groups

lint:
	uv run ruff check .
	uv run ruff format --check .

type:
	uv run mypy

test:
	uv run pytest

run:
	uv run pgrestoredrill --help

drill:
	uv run pgrestoredrill run --config examples/drill.yaml

migrate:
	uv run alembic upgrade head

fixture:
	uv run python tests/fixtures/build_fixture.py

up:
	docker compose up -d

down:
	docker compose down

kind-smoke:
	uv run python deploy/kind_smoke.py
