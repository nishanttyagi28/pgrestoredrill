# AGENTS.md

## Project

pgrestoredrill proves Postgres backups actually restore. It takes the latest custom-format dump (`pg_dump -Fc`) from a local path or S3-compatible storage, restores it into a throwaway Postgres, runs user-written read-only SQL assertions, records run history and restore duration, alerts when the last good restore is older than the RPO, and keeps failures open until a person acks them. It is for small teams and indie developers who run Postgres and have never tested a restore.

Scope: Postgres custom-format dumps only.

## Stack

- Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Postgres 16/17, psycopg 3, boto3, pydantic-settings, structlog, prometheus-client, PyYAML.
- Tooling: uv, ruff (lint + format), mypy (strict on `src/`), pytest, pytest-cov.
- Docker, docker-compose, kubernetes manifests under `deploy/k8s` (kustomize), kind for smoke tests.
- Restore targets: external (given URL), docker (local only), k8s-sidecar (postgres container in the CronJob pod). Never mount the docker socket in kubernetes.
- GitHub Actions for CI.

## Layout

- `src/pgrestoredrill/` (`api/`, `runner/`, `sources/`, `targets/`, `assertions/`, `db/`, `alerts/`, `notes/`, `config.py`, `metrics.py`, `logging.py`, `cli.py`)
- `migrations/`, `tests/unit/`, `tests/integration/`, `tests/fixtures/`, `deploy/k8s/`, `docs/`, `.github/workflows/`
- `Makefile`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md`, `CHANGELOG.md`, `SECURITY.md`

## Commands

- `make install`
- `make lint` (ruff check + ruff format --check)
- `make type` (mypy)
- `make test` (pytest with coverage)
- `make run`
- `make drill`
- `make migrate`
- `make fixture`
- `make up` / `make down` (docker compose)
- `make kind-smoke`

Every milestone must end with `make lint`, `make type`, and `make test` passing.

## Testing rules

- Every feature ships with tests in the same change.
- Unit tests never hit the network. LLM calls use a fake client.
- Integration tests restore a real fixture dump into the Postgres service in CI, with one passing drill and one deliberately failing drill.
- Coverage on `src/` must not drop below 85%.

## Always

- Keep each file under 300 lines. Split modules instead of suppressing formatter or linter rules.
- Use type hints everywhere and pydantic models at API boundaries.
- Run assertions in read-only transactions with a statement timeout.
- Never log secrets, connection strings with passwords, or dump contents.
- Write plain lowercase commit messages, one logical change per commit, for example: `add pg_restore wrapper with timeout`.
- Use git identity: Nishant Tyagi <253968642+nishanttyagi28@users.noreply.github.com>.
- Update README and CHANGELOG when behaviour changes.
- Stop after each milestone, summarize what changed and how to verify it, and wait for approval.
- Do not push unless asked.

## Ask first

- Before installing or adding any dependency, tool, container image, or GitHub Action.
- Before changing the database schema outside the current milestone.
- Before changing CI workflows, Dockerfile, or k8s manifests outside the current milestone.
- Before deleting or renaming files.

## Never

- Never force-push, rebase pushed commits, or rewrite history.
- Never weaken, skip, delete, or loosen tests or assertions to make them pass.
- Never add `noqa`, `type: ignore`, `fmt: off`, or config changes that hide linter or type errors.
- Never put AI or tool wording, generator notes, or `Co-authored-by` trailers in files or commits.
- Never commit secrets, real dumps, or `.env` files.
- Never restore into a database that was not created for the drill.
- Never let the LLM ack, retry, or change anything. It only writes a suggested failure note.

## Milestones

- M1 core drill on local files.
- M2 S3 source + run history API.
- M3 RPO, metrics, alerts, ack.
- M4 docker, compose, k8s CronJob with sidecar, image CI.
- M5 failure notes + docs + v0.1.0.

Work on one milestone at a time and only on its listed scope.
