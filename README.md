# pgrestoredrill

pgrestoredrill checks that a Postgres backup can be restored. It takes the newest custom-format dump (`pg_dump -Fc`) from a local folder or an S3-compatible bucket, restores it into an empty throwaway database, runs read-only SQL assertions, and stores the run.

## Quickstart

You need Python 3.12, uv, GNU make, and `pg_dump` / `pg_restore` on `PATH`. The restore role needs `CREATEDB`. `template1` must not contain user objects.

### Command line

Copy `.env.example` to `.env`. On PowerShell: `Copy-Item .env.example .env`. Create the metadata database named in `DATABASE_URL`.

```bash
make install
make migrate
make fixture
make drill
```

`make drill` runs `examples/drill.yaml`. A pass prints `status: passed` and exits 0. Each run creates `pgrestoredrill_` plus 32 hex characters and leaves that database in place.

### Compose

`compose.yaml` starts metadata Postgres, a target Postgres, silo, a migration, and the API. Change the example token `replace-me` before you expose the API.

```bash
make up
make fixture
docker compose --profile drill run --rm drill
```

That uploads `tests/fixtures/dumps/sample.dump` and runs `examples/compose-drill.yaml` against `target`. The sample assertions expect rows from the last hour. `TARGET_KIND=docker` starts one local Postgres 16 container and removes it when the drill finishes. Leave that kind unset on Kubernetes.

### Kubernetes

Replace every `replace-me` in `deploy/k8s/base/secret.yaml` and point the ConfigMap drill at your bucket.

```bash
kubectl apply -k deploy/k8s/base
```

The CronJob runs beside a Postgres sidecar. The image is `ghcr.io/nishanttyagi28/pgrestoredrill`. Set `newTag` in `deploy/k8s/base/kustomization.yaml` to the tag or digest you run. This repo still has `0.0.1`. `make kind-smoke` runs one drill on kind cluster `pgrestoredrill-smoke`, prints the passed run id and status, and deletes that cluster.

## Configuration

Settings come from the environment or `.env`.

| Name | Role |
| --- | --- |
| `DATABASE_URL` | Metadata database. Required. |
| `TARGET_URL` | Creates the throwaway database when `TARGET_KIND` is `external`. |
| `TARGET_KIND` | `external` (default), `docker`, or `k8s-sidecar`. |
| `SIDECAR_PASSWORD` | Required for a sidecar drill. Blank refuses that drill. |
| `SIDECAR_HOST` | Default `127.0.0.1`. |
| `SIDECAR_PORT` | Default `5432`. |
| `SIDECAR_USER` | Default `postgres`. |
| `LOG_LEVEL` | Default `INFO`. |
| `S3_ACCESS_KEY` | Optional. Blank uses the AWS default chain. |
| `S3_SECRET_KEY` | Optional pair for the access key. |
| `ADMIN_TOKEN` | Bearer token. Blank refuses drill and run routes. |
| `ALERT_WEBHOOK_URL` | JSON webhook. Blank sends nothing. |
| `NOTES_ENABLED` | Suggestions. Default `false`. |
| `NOTES_URL` | OpenAI-compatible base, such as `https://api.x.ai/v1`. |
| `NOTES_MODEL` | Model name for the note request. |
| `NOTES_API_KEY` | Bearer token for that endpoint. |

The drill file sets the source, `rpo_minutes`, assertions, optional `min_bytes` and `max_age_minutes`, and the two timeouts. Paths are relative to the drill file. An assertion is `rows_gte`, `equals`, or `max_age_minutes`: one read-only statement, one row.

## RPO, alerts, ack, and notes

RPO is computed on read. `unknown` means no finished run. `ok` means the newest pass finished within `rpo_minutes`, including a pass that is exactly that old. `breached` means that pass is older, or every finished run failed or errored.

A failed or errored run posts `drill`, `status`, `reason`, and `run_id` when `ALERT_WEBHOOK_URL` is set. A breach posts once more with status `breached`. The same failure is inserted once. `sent_at` is set only for a 2xx response. A 3xx response is final and is not retried. A row with an empty `sent_at` and an empty `response_status` is claimed with one update and sent once more on a later run, after it is more than 10 minutes old. Delivery does not change the run.

Ack a failed or errored run with `pgrestoredrill ack RUN_ID --by "Ada" --note "checked the restored rows"` or `POST /runs/{id}/ack`. A second ack is rejected. A passed run is rejected. Nothing acks itself. The ack text is stored on `note` and does not change RPO.

Notes stay off until `NOTES_ENABLED` is true. Rules run first: missing extension, missing role, version mismatch, permission denied, disk full, timeout, assertion failed, unknown. A model is called only when notes are on, the URL and model are set, and the rule result is unknown. The call is one plain HTTP POST to `{NOTES_URL}/chat/completions`, with no vendor SDK. A reply is kept only when it is JSON with `category`, `short_reason`, and `suggested_next_step`, each at most 300 characters. Otherwise the rule result is kept. `GET /runs/{id}` and the alert payload include the note with `suggestion` set. It does not ack, retry, or change status. `docs/runbook.md` covers each label.

`GET /healthz` and `GET /readyz` are open. `GET /metrics` is unauthenticated. Drill and run routes need `Authorization: Bearer` with `ADMIN_TOKEN`. The API reads stored runs and does not start a restore.

## Limitations

Postgres custom-format dumps only. The image and the sidecar restore dumps from Postgres 16 or older. A newer server, a newer `pg_dump`, archive format 1.16 or newer, or an unreadable header is refused before restore. One error looks like `dump is from Postgres 17; this image restores 16 or older`, and the run is failed. Alert delivery is at-most-once with one resend.

## Development

`make install`, `make lint` (ruff), `make type` (strict mypy on `src/`), and `make test` are the local gates. Tests need `DATABASE_URL`, `TARGET_URL`, and `pg_restore` on `PATH`. Coverage on `src/` stays at or above 85 percent. The live S3 test skips unless `MINIO_ENDPOINT` is set. `make migrate` applies Alembic. `SECURITY.md` covers secrets and the note request.
