# Changelog

## Unreleased

### Changed

- A drill database is refused when it has an extension other than `plpgsql`, a
  schema other than `public`, a user-defined type, or a function or procedure
  outside the system catalogs.

### Fixed

- `pg_restore` receives `--host`, `--port`, `--username`, and `--dbname` as
  separate arguments. The password is passed only through `PGPASSWORD`.
- URL options such as `sslmode` are passed to `pg_restore` as `PG*` environment
  variables.

### Added

- `compose.yaml` starts Postgres 16 with the example settings from `.env.example`.
- Local custom-format restore drill. The newest `*.dump` in a folder is restored
  into an empty throwaway database, read-only assertions run, and the run is
  stored.
- `pgrestoredrill run --config drill.yaml` prints a summary and exits non-zero
  when the drill does not pass.
- Sample fixture builder (`make fixture`) and a CI workflow that runs ruff,
  mypy, and pytest against Postgres 16.
