# Changelog

## Unreleased

### Changed

- A drill database is refused when it has an extension other than `plpgsql`, a
  schema other than `public`, a user-defined type, a function, procedure, or
  aggregate outside the system catalogs, a large object, a collation, an
  operator, a text search configuration, a publication, or a foreign data wrapper.

### Fixed

- An interrupted S3 download deletes its temporary dump file, including when
  the interruption is `KeyboardInterrupt`.
- `pg_restore` receives `--host`, `--port`, `--username`, and `--dbname` as
  separate arguments. The password is passed only through `PGPASSWORD`.
- URL options such as `sslmode` are passed to `pg_restore` as `PG*` environment
  variables.

### Added

- Run history API. `GET /healthz` and `GET /readyz` are open. Drill and run
  routes require a bearer token compared in constant time with `ADMIN_TOKEN`.
  The API reads runs the CLI records and does not start a restore.
- A dump is refused before restore when it is empty, smaller than optional
  `min_bytes`, or older than optional `max_age_minutes`. The run is stored as
  failed and the restore is skipped.
- S3-compatible source. The newest object whose key ends in `.dump` is streamed
  to a temporary file, checksummed, restored, and the file is deleted afterwards.
  Credentials come from the environment or settings and are not logged.
- CI runs that S3 test against `pgsty/silo:RELEASE.2026-09-16T00-00-00Z`.
  The test skips when `MINIO_ENDPOINT` is unset and fails in GitHub Actions
  when the variable is missing.
- `compose.yaml` starts Postgres 16 with the example settings from `.env.example`.
- Local custom-format restore drill. The newest `*.dump` in a folder is restored
  into an empty throwaway database, read-only assertions run, and the run is
  stored.
- `pgrestoredrill run --config drill.yaml` prints a summary and exits non-zero
  when the drill does not pass.
- Sample fixture builder (`make fixture`) and a CI workflow that runs ruff,
  mypy, and pytest against Postgres 16.
