# When a drill fails

Read the run. `GET /runs/{id}` returns `status`, `error`, and the assertion results. When failure notes are enabled, it also returns `suggestion`. That object is a suggestion. It does not ack the run, retry the restore, or change the status. The human ack stays on `note`.

Match the error text below. When a suggestion is stored, `suggestion.category` is one of these sections. Fix the cause, then run the drill again. Ack the old run only after you have looked at it.

## Missing extension

The dump uses an extension that is not installed on the restore server. The error mentions an extension that does not exist, is not available, or could not be opened.

Install that extension on the restore server, in the image you restore with, or in the sidecar. Run the drill again. A throwaway database is created from `template1`, so the extension has to be available to a new database.

## Missing role

The dump names a role that does not exist on the restore server. The error says a role does not exist.

Create that role on the restore server, or take the dump again with `--no-owner` and `--no-acl` if those privileges are not part of the check. Run the drill again.

## Version mismatch

The dump is newer than this `pg_restore`, or the restore client sent SQL this server rejects. A dump newer than the client is refused before restore. The error looks like `dump is from Postgres 17; this image restores 16 or older`. `pg_restore` 17 also sends `SET transaction_timeout`, which Postgres 16 rejects.

Take the dump again with `pg_dump` 16 or older, or restore with a client at least as new as the dump. The image and the sidecar install `postgresql-client-16`. A header that cannot be read does not block the restore. The run is failed, and the category is version mismatch when notes are enabled.

## Permission denied

The restore role is not allowed to create an object in the dump. The error says permission denied, or that the role must be owner.

Grant the missing privilege on the restore server, or dump without ownership and ACLs when the drill does not need them. Run the drill again. The role in `TARGET_URL` still needs `CREATEDB` for an external target.

## Disk full

The restore server ran out of disk. The error says there is no space left, or the disk is full.

Free space on the volume that holds the throwaway database. On the sidecar, that is the pod's emptyDir. Run the drill again. A failed run may leave a database behind on an external target. Drop it after you have inspected it.

## Timeout

The restore or a statement did not finish before its limit. The error mentions a timeout. `transaction_timeout` belongs under version mismatch.

Raise `restore_timeout_seconds` or `statement_timeout_ms` in the drill file when the dump and the checks are legitimate and only slow. If the statement is waiting on a lock or scanning an unexpected table, fix that before you raise the limit. Run the drill again.

## Assertion failed

A read-only assertion did not match the restored data. The run status is failed. The assertion result has the name, the observed value, and the expected value.

Compare that assertion with the restored database. An external target leaves the `pgrestoredrill_<id>` database in place for this. Fix the dump, the source data, or the check. Run the drill again. An assertion failure is not a restore crash. `pg_restore` already finished.

## Unknown

The error did not match a rule above. Read `error` on the run, and the restore stderr stored with it.

When notes are enabled and the rule result is unknown, the service may attach a model suggestion. Keep it as a hint. Confirm it against the error text before you act on it. If the reply was not the required JSON, the stored category stays unknown and the fixed rule text is kept. Compare the dump with this server, fix the cause, and run the drill again.
