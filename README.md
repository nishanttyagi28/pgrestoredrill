# pgrestoredrill

pgrestoredrill proves a Postgres backup can be restored. It takes the newest
custom-format dump (`pg_dump -Fc`) in a folder, restores it into a throwaway
database, runs read-only SQL assertions, and records the run.

This release is the local-file drill. It is for small teams and indie developers
who run Postgres and have never tested a restore.

## Quickstart

You need Python 3.12, [uv](https://docs.astral.sh/uv/), GNU make, a Postgres 16
or 17 server, and `pg_dump` / `pg_restore` on `PATH`. The role in `TARGET_URL`
needs `CREATEDB`. `template1` must not contain user objects: tables, extensions
other than `plpgsql`, schemas other than `public`, types, or functions.

```bash
cp .env.example .env
```

On PowerShell: `Copy-Item .env.example .env`

Create the metadata database named in `DATABASE_URL` (the default name is
`pgrestoredrill`), then:

```bash
make install
make migrate
make fixture
make drill
```

`make drill` runs `examples/drill.yaml`. A passing drill prints `status: passed`
and exits 0. A failed assertion or a restore error exits non-zero.

Each run creates a new database named `pgrestoredrill_` plus 32 hex characters
and leaves it in place so you can inspect it. Drop it when you are done. The
database in `TARGET_URL` is only used to create that database. It is never the
restore target.

## Drill file

`examples/drill.yaml` points at a folder of `*.dump` files and an assertions
file. Paths are relative to the drill file. The newest `*.dump` in that folder
is the one that is restored.

Assertions are a YAML list. Each item is one statement, run in its own
`READ ONLY` transaction with `statement_timeout`.

| type | pass when |
| --- | --- |
| `rows_gte` | the first column is a number greater than or equal to `expected` |
| `equals` | the first column equals `expected` |
| `max_age_minutes` | the first column is a timestamp no older than `expected` minutes |

The statement must return one row. Writes are rejected by the read-only
transaction.

## Commands

- `make install` installs the package and dev tools with uv
- `make lint` runs `ruff check` and `ruff format --check`
- `make type` runs mypy in strict mode on `src/`
- `make test` runs pytest and requires at least 85% coverage on `src/`
- `make migrate` applies Alembic migrations
- `make fixture` writes `tests/fixtures/dumps/sample.dump`
- `make drill` runs the sample drill
- `make run` prints CLI help

`make test` needs the same Postgres server and client tools. It creates and
drops its own databases.

## Limits

Only Postgres custom-format dumps from a local folder are supported here.
S3 sources, the run-history API, RPO alerts, Docker, and Kubernetes come later.
