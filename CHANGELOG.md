# Changelog

## Unreleased

### Fixed

- A failure-note prompt drops `DETAIL:` and `CONTEXT:` lines, masks IPv6
  addresses, quoted host names, `PGPASSWORD` assignments, `sk-` tokens, and
  base64 or hex runs of 24 or more characters.
- A note response larger than 64 KiB is discarded. The rule result is kept.

## [0.1.0] - 2026-10-11

### Changed

- `make kind-smoke` prints the passed run id and status. CI pins the Postgres
  16 service image by digest.
- The restore duration histogram includes buckets up to 3600 seconds.
  `GET /metrics` is unauthenticated. `pgrestoredrill_rpo_breached` is how to
  catch a drill that has stopped running.
- An alert row is inserted before the webhook is called. A duplicate dedup key
  is not sent again. `sent_at` stays empty unless a response is 2xx.
- S3 size and age checks run on the listed object (`Size` and `LastModified`)
  before the download, and again on the streamed bytes. A listing that fails
  is stored as failed with the key and listed size, no checksum, and the
  object is not downloaded.
- A drill database is refused when it has an extension other than `plpgsql`, a
  schema other than `public`, a user-defined type, a function, procedure, or
  aggregate outside the system catalogs, a large object, a collation, an
  operator, a text search configuration, a publication, or a foreign data wrapper.

### Fixed

- Acking a run is one conditional update. A concurrent second ack is rejected.
- The alert webhook does not follow redirects. A 3xx response is a final
  failure and is not retried.
- An alert with an empty `sent_at` and an empty `response_status` is sent
  again on a later run when the alert's run finished more than 10 minutes
  ago. The resend happens once. A resend that gets no HTTP status is marked
  so it is not selected again. `sent_at` stays empty unless the response is 2xx.
- An interrupted S3 download deletes its temporary dump file, including when
  the interruption is `KeyboardInterrupt`.
- `pg_restore` receives `--host`, `--port`, `--username`, and `--dbname` as
  separate arguments. The password is passed only through `PGPASSWORD`.
- URL options such as `sslmode` are passed to `pg_restore` as `PG*` environment
  variables.

### Added

- A custom-format dump newer than this `pg_restore` is refused before restore.
  The run is stored as failed. The error names both majors, for example
  `dump is from Postgres 17; this image restores 16 or older`. A header that
  cannot be read does not block the restore.
- Optional failure suggestions. `NOTES_ENABLED` defaults to false. Rules label
  the restore stderr and assertion results first. A model is called only when
  notes are enabled and the rule result is unknown, through an OpenAI-compatible
  HTTP endpoint (`NOTES_URL`, `NOTES_MODEL`, `NOTES_API_KEY`). The prompt is the
  masked stderr tail and the assertion names. A reply is stored only when it
  matches the note schema. `GET /runs/{id}` and the alert payload include it,
  marked as a suggestion. It does not ack, retry, or change the run.
- Container image based on `python:3.12-slim` pinned by digest. uv 0.12.24 is
  copied from its pinned image. The image installs `postgresql-client-16` so
  `pg_restore` matches the Postgres 16 target. A newer `pg_restore` sends
  `SET transaction_timeout`, which Postgres 16 rejects. The fixture builder
  refuses a `pg_dump` newer than the server it dumps. The process is non-root,
  `/app` stays owned by root, and `/healthz` is the healthcheck. No secret is
  baked into the image.
- `compose.yaml` also starts a throwaway target Postgres, silo, the API, and a
  one-shot drill. `TARGET_KIND=docker` starts a local Postgres container for
  one drill and removes it afterwards. It is not used in Kubernetes.
- `TARGET_KIND=k8s-sidecar` restores into a Postgres sidecar on localhost. The
  password comes from the pod environment. The empty-database check is the
  same one an external target uses.
- Kubernetes manifests under `deploy/k8s`. The API uses `/readyz` and
  `/healthz`. The image tag is `newTag` in the base kustomization; set it to a
  released tag or a digest. The CronJob runs the drill beside a Postgres
  sidecar, forbids overlapping runs, and deletes the finished job. `make
  kind-smoke` runs one drill on a kind cluster. The image workflow checks the
  process imports, runs the compose drill, runs kind, and pushes to
  `ghcr.io/nishanttyagi28/pgrestoredrill` on main and tags.
- `GET /metrics` exposes restore duration, run counts, the time of the last
  successful run, and whether the RPO is breached. Labels are drill names.
- `GET /drills/{id}` reports the computed RPO status and open unacked failures.
  `POST /runs/{id}/ack` and `pgrestoredrill ack` record who acked a failed or
  errored run and a short note. A second ack is rejected. Nothing acks itself.
- A failed or errored run sends one JSON alert to `ALERT_WEBHOOK_URL` when it
  is set. A drill that is outside its RPO sends one more. Delivery is tried at
  most three times. The same failure is not sent again, and a delivery failure
  does not change the run.
- Run history API. `GET /healthz` and `GET /readyz` are open. Drill and run
  routes require a bearer token compared in constant time with `ADMIN_TOKEN`.
  The API reads runs the CLI records and does not start a restore.
- A dump is refused before restore when it is empty, smaller than optional
  `min_bytes`, or older than optional `max_age_minutes`. The run is stored as
  failed and the restore is skipped.
- S3-compatible source. The newest object whose key ends in `.dump` is streamed
  to a temporary file, checksummed, restored, and the file is deleted afterwards.
  Credentials come from the environment or settings and are not logged.
- CI runs that S3 test against `pgsty/silo:RELEASE.2026-09-16T00-00-00Z`
  pinned to `sha256:635197cb9f36d01bee221d34d1c7d7960f6a95c48b0b6c01d99cd13bdae51a46`.
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
