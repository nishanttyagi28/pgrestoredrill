# Changelog

## Unreleased

### Added

- Local custom-format restore drill. The newest `*.dump` in a folder is restored
  into an empty throwaway database, read-only assertions run, and the run is
  stored.
- `pgrestoredrill run --config drill.yaml` prints a summary and exits non-zero
  when the drill does not pass.
- Sample fixture builder (`make fixture`) and a CI workflow that runs ruff,
  mypy, and pytest against Postgres 16.
