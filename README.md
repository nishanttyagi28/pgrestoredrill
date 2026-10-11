# pgrestoredrill

pgrestoredrill checks that a Postgres backup can be restored. It takes the newest custom-format dump (`pg_dump -Fc`) from a local folder or an S3-compatible bucket, restores it into an empty throwaway database, runs read-only SQL assertions, and stores the run.

Nightly dumps exit 0, and checksums only prove the file is intact. Most small teams never restore a backup until an outage. This tool restores it on a schedule and checks real rows.

## Quickstart

You need Python 3.12, uv, GNU make, and `pg_dump` / `pg_restore` on `PATH`. The restore role needs `CREATEDB`, and `template1` must not contain user objects.

### Command line

Copy `.env.example` to `.env` (on PowerShell, `Copy-Item .env.example .env`) and create the metadata database named in `DATABASE_URL`.

```bash
make install
make migrate
make fixture
make drill
```

`make drill` runs `examples/drill.yaml`, prints `status: passed`, and exits 0 on a pass. Each run creates `pgrestoredrill_` plus 32 hex characters and leaves that database in place:

```text
uv run pgrestoredrill run --config examples/drill.yaml
status: passed
drill: sample
run_id: f9fb8ff6-af22-4e43-a45b-7e8bffa9cad8
database: pgrestoredrill_61ffff2d2fff41efbeb0269cc6ef21cb
dump: C:\Users\nishant\pgrestoredrill\tests\fixtures\dumps\sample.dump
bytes: 3067
sha256: 3d49340a164ff624f1da67500c59cb84fa87d1578f14a9879f0eda6468533eac
restore_seconds: 0.114
assertions:
  customers_present passed observed=2 expected=2 1ms
  first_email passed observed=a@example.com expected=a@example.com 0ms
  orders_are_fresh passed observed=2026-10-11T08:09:34.499366+00:00 expected=60 5ms
```

### Compose

`compose.yaml` starts metadata Postgres, a target Postgres, silo, a migration, and the API. Change the example token `replace-me` before you expose the API.

```bash
make up
make fixture
docker compose --profile drill run --rm drill
```

That uploads `tests/fixtures/dumps/sample.dump` and runs `examples/compose-drill.yaml` against `target`. Sample assertions expect rows from the last hour. `TARGET_KIND=docker` starts one local Postgres 16 container and removes it when the drill finishes. Leave that kind unset on Kubernetes.

### Kubernetes

Replace every `replace-me` in `deploy/k8s/base/secret.yaml` and point the ConfigMap drill at your bucket.

```bash
kubectl apply -k deploy/k8s/base
```

The CronJob runs beside a Postgres sidecar, using `ghcr.io/nishanttyagi28/pgrestoredrill`. Set `newTag` in `deploy/k8s/base/kustomization.yaml` to `v0.1.0` (or a digest); this repo uses `v0.1.0`. `make kind-smoke` runs one drill on kind cluster `pgrestoredrill-smoke`, prints the passed run id and status, and deletes that cluster.

## Configuration

Settings come from the environment or `.env`.

- `DATABASE_URL`: metadata database, required.
- `TARGET_URL`: creates the throwaway database when `TARGET_KIND` is `external`.
- `TARGET_KIND`: `external` (default), `docker`, or `k8s-sidecar`.
- `SIDECAR_PASSWORD`: required for a sidecar drill; blank refuses it.
- `SIDECAR_HOST`: default `127.0.0.1`.
- `SIDECAR_PORT`: default `5432`.
- `SIDECAR_USER`: default `postgres`.
- `LOG_LEVEL`: default `INFO`.
- `S3_ACCESS_KEY`: optional; blank uses the AWS default chain.
- `S3_SECRET_KEY`: optional pair for the access key.
- `ADMIN_TOKEN`: bearer token; blank refuses drill and run routes.
- `ALERT_WEBHOOK_URL`: JSON webhook; blank sends nothing.
- `NOTES_ENABLED`: suggestions, default `false`.
- `NOTES_URL`: OpenAI-compatible base, such as `https://api.x.ai/v1`.
- `NOTES_MODEL`: model name.
- `NOTES_API_KEY`: bearer token for that endpoint.

The drill file sets the source, `rpo_minutes`, assertions, optional `min_bytes` and `max_age_minutes`, and both timeouts. Paths are relative to that file. An assertion is `rows_gte`, `equals`, or `max_age_minutes`: one read-only statement, one row.

## RPO, alerts, ack, and notes

RPO is computed on read. `unknown` means no finished run, `ok` means the newest pass finished within `rpo_minutes`, including one exactly that old, and `breached` means that pass is older or every finished run failed or errored.

A failed or errored run posts `drill`, `status`, `reason`, and `run_id` when `ALERT_WEBHOOK_URL` is set, and a breach posts once more with status `breached`. The same failure is inserted once. `sent_at` is set only on 2xx, a 3xx is final and is not retried, and a row with empty `sent_at` and empty `response_status` is claimed with one update and sent once more on a later run after it is more than 10 minutes old. Delivery does not change the run.

Ack a failed or errored run with `pgrestoredrill ack RUN_ID --by "Ada" --note "checked the restored rows"` or `POST /runs/{id}/ack`. A second ack and a passed run are rejected, and nothing acks itself, and the ack text stored on `note` does not change RPO.

Notes stay off until `NOTES_ENABLED` is true. Rules run first: missing extension, missing role, version mismatch, permission denied, disk full, timeout, assertion failed, unknown. A model is called only when notes are on, URL and model are set, and the rule result is unknown, via one plain HTTP POST to `{NOTES_URL}/chat/completions`, with no vendor SDK. Only a JSON reply with `category`, `short_reason`, and `suggested_next_step`, each at most 300 characters, is kept; otherwise the rule result is kept. `GET /runs/{id}` and the alert payload include the note with `suggestion` set. It does not ack, retry, or change status. `docs/runbook.md` covers each label.

`GET /healthz` and `GET /readyz` are open, `GET /metrics` is unauthenticated, and drill and run routes need `Authorization: Bearer` with `ADMIN_TOKEN`. The API reads stored runs and does not start a restore.

## Limitations

Postgres custom-format dumps only. The image and sidecar restore dumps from Postgres 16 or older, and refuse a newer server, a newer `pg_dump`, archive format 1.16 or newer, or an unreadable header before restore. One failed run reports `dump is from Postgres 17; this image restores 16 or older`. Alert delivery is at-most-once with one resend.

## Development

`make install`, `make lint` (ruff), `make type` (strict mypy on `src/`), and `make test` are the local gates. Tests need `DATABASE_URL`, `TARGET_URL`, and `pg_restore` on `PATH`, and coverage on `src/` stays at or above 85 percent. The live S3 test skips unless `MINIO_ENDPOINT` is set, `make migrate` applies Alembic, and `SECURITY.md` covers secrets and the note request.
