# pgrestoredrill

pgrestoredrill proves a Postgres backup can be restored. It takes the newest
custom-format dump (`pg_dump -Fc`) from a local folder or an S3-compatible
bucket, restores it into a throwaway database, runs read-only SQL assertions,
and records the run.

This release is the local-file and S3 drill. It is for small teams and indie
developers who run Postgres and have never tested a restore.

## Quickstart

You need Python 3.12, [uv](https://docs.astral.sh/uv/), GNU make, a Postgres 16
or 17 server, and `pg_dump` / `pg_restore` on `PATH`. The role in `TARGET_URL`
needs `CREATEDB`. `template1` must not contain user objects: tables, extensions
other than `plpgsql`, schemas other than `public`, types, functions, aggregates,
operators, collations, large objects, text search configurations, publications,
or foreign data wrappers.

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

`examples/s3-drill.yaml` is the same drill for an S3-compatible bucket.
`source_uri` is the key prefix, and `bucket`, `endpoint_url`, and `region`
describe the bucket. The newest object whose key ends in `.dump` is streamed
to a temporary file, restored, and then the file is deleted. Credentials are
`S3_ACCESS_KEY` and `S3_SECRET_KEY`. When both are empty, boto3 uses its
default environment chain. They are never written to the drill file or the logs.

`min_bytes` and `max_age_minutes` are optional. An empty dump is refused, then
a dump smaller than `min_bytes`, then a dump older than `max_age_minutes`.
A local dump uses the file size and modification time. An S3 object is checked
from its listed `Size` and `LastModified` before it is downloaded, and the same
checks run again on the streamed bytes. A refused dump is stored as a failed
run and is not restored. A listing that fails is not downloaded. That run
records the object key and the listed size and has no checksum.

Assertions are a YAML list. Each item is one statement, run in its own
`READ ONLY` transaction with `statement_timeout`.

| type | pass when |
| --- | --- |
| `rows_gte` | the first column is a number greater than or equal to `expected` |
| `equals` | the first column equals `expected` |
| `max_age_minutes` | the first column is a timestamp no older than `expected` minutes |

The statement must return one row. Writes are rejected by the read-only
transaction.

## RPO

`rpo_minutes` in the drill file is the recovery point objective. The status is
computed from finished runs each time it is read:

- `unknown` when the drill has never finished a run
- `ok` when the newest passed run finished within `rpo_minutes`
- `breached` when that pass is older than `rpo_minutes`, or when every finished
  run failed or errored

A pass that is exactly `rpo_minutes` old is still `ok`. The status is not stored.

## Alerts

`ALERT_WEBHOOK_URL` is optional. When it is empty, nothing is sent. When it is
set, a failed or errored run sends one JSON POST:

```json
{"drill": "orders", "status": "failed", "reason": "dump is empty", "run_id": "..."}
```

A drill that is `breached` sends one more post with `"status": "breached"`.
The body has only those four fields. The same failure is not sent again. The
request times out after 5 seconds and is tried at most 3 times, with a short
pause between tries. A redirect is not followed. The attempt is stored before
the request is sent, so a second sender skips it. `sent_at` is set only when a
response is 2xx. A delivery failure does not change the run result.

## Metrics

`GET /metrics` is unauthenticated. Each scrape reads stored runs and writes
Prometheus text. Nothing is kept in memory between scrapes.

| metric | meaning |
| --- | --- |
| `pgrestoredrill_restore_duration_seconds` | histogram of restore durations, buckets up to 3600 seconds |
| `pgrestoredrill_runs_total` | runs, labeled by drill and status |
| `pgrestoredrill_last_success_timestamp_seconds` | unix time of the newest passed run |
| `pgrestoredrill_rpo_breached` | 1 when the drill is breached, otherwise 0 |

Watch `pgrestoredrill_rpo_breached` to catch a drill that stopped running. It
becomes 1 when the newest passed run ages past `rpo_minutes`. A drill that has
never finished a run is 0. The only labels are the drill name and, on
`runs_total`, the status. Dump keys, URLs, and secrets are not labels.

## Commands

- `make install` installs the package and dev tools with uv
- `make lint` runs `ruff check` and `ruff format --check`
- `make type` runs mypy in strict mode on `src/`
- `make test` runs pytest and requires at least 85% coverage on `src/`
- `make migrate` applies Alembic migrations
- `make fixture` writes `tests/fixtures/dumps/sample.dump`
- `make drill` runs the sample drill
- `make run` prints CLI help
- `make up` / `make down` start and stop the local compose stack
- `make kind-smoke` builds the image, runs one drill on a kind cluster, and deletes the cluster

The run-history API reads the same database. It does not start a restore.

```bash
uv run uvicorn pgrestoredrill.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

`GET /healthz` and `GET /readyz` do not need a token. `GET /metrics` is
unauthenticated. `/readyz` checks that the metadata database answers `SELECT 1`.
`GET /drills`,
`GET /drills/{id}`, `GET /drills/{id}/runs`, `GET /runs/{id}`, and
`POST /runs/{id}/ack` require `Authorization: Bearer` with the value of
`ADMIN_TOKEN`. The token is compared
in constant time. `/runs/{id}` includes the assertion results for that run.
`runs` accepts `limit` from 1 to 100 and returns the newest runs first.

`GET /drills/{id}` returns the drill's RPO status and the failed or errored
runs that have not been acked. Ack a run with:

```bash
pgrestoredrill ack RUN_ID --by "Ada" --note "checked the restored rows"
```

The JSON body is `{"by": "Ada", "note": "checked the restored rows"}`. Only a
failed or errored run can be acked. A second ack returns 409, including when
two acks arrive together. A passed run returns 400. No process acks a run on
its own. An ack does not change the RPO
status.

`make test` needs the same Postgres server and client tools. It creates and
drops its own databases. The live S3 test runs when `MINIO_ENDPOINT` is set
and skips otherwise. CI sets that variable and starts
`pgsty/silo:RELEASE.2026-09-16T00-00-00Z@sha256:635197cb9f36d01bee221d34d1c7d7960f6a95c48b0b6c01d99cd13bdae51a46`
with example root credentials.
`make up` uses the example user, password, and port from `.env.example`. The
metadata server creates the `pgrestoredrill` database.

## Local compose

`compose.yaml` starts a metadata Postgres, a throwaway target Postgres, silo
as S3, a migration job, and the API. Example values are `postgres` / `postgres`
for Postgres and `minioadmin` / `minioadmin` for silo. The API token is
`replace-me`. Change it before you expose the API.

```bash
make up
```

The one-shot drill is a separate profile. Build a fresh fixture first, because
the sample assertions expect rows from the last hour.

```bash
make fixture
docker compose --profile drill run --rm drill
```

That command starts the migration, the target Postgres, silo, and the fixture
upload, then runs the drill. It uploads `tests/fixtures/dumps/sample.dump` and
runs `examples/compose-drill.yaml`. The drill restores into the `target`
service. `TARGET_KIND=docker` is only for a drill on your machine: it starts a
throwaway Postgres 16 container and removes it when the drill finishes, including
when the drill fails. Do not set it in Kubernetes.

The image installs `postgresql-client-17`. `pg_restore` 17 restores
custom-format dumps written by `pg_dump` 16 or 17. The compose target and the
sidecar are Postgres 16, so the dump has to come from Postgres 16 or older.
Do not build the fixture with a `pg_dump` newer than 17.

## Kubernetes

The manifests under `deploy/k8s/base` are a kustomize app. They create a
namespace, the API, a migration job, and a CronJob. The CronJob runs the drill
beside a Postgres sidecar. An init container writes a random password into an
emptyDir, and both containers read it. The sidecar listens on localhost and
stops when the drill container exits. Nothing mounts the docker socket or a
host path, and nothing is given cluster-wide permissions.

```bash
kubectl apply -k deploy/k8s/base
```

Replace every `replace-me` value in the Secret before you rely on it. The
ConfigMap drill file points at `http://s3.example.invalid`; point it at your
bucket. The image name is `ghcr.io/nishanttyagi28/pgrestoredrill`. Set `newTag`
in `deploy/k8s/base/kustomization.yaml` to a released tag, or to a digest,
before you apply the base. The repo sets that tag to `0.0.1`.

`deploy/k8s/overlays/smoke` is only for `make kind-smoke`. It adds a metadata
Postgres and silo, loads the sample fixture, runs the CronJob once, and checks
the API for a passed run. It needs Docker, kind 0.33.0, and kubectl.

## Limits

Postgres custom-format dumps from a local folder or an S3-compatible bucket
are supported. The API lists past runs. Compose can run the stack locally, and
the Kubernetes CronJob can run a drill next to a Postgres sidecar. Failure
notes are not in this release.
