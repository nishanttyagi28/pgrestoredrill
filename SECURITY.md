# Security

## Secrets

`pg_restore` receives `--host`, `--port`, `--username`, and `--dbname` as separate arguments. The database password is passed only through `PGPASSWORD`. It is not placed in the argument list.

`ADMIN_TOKEN`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `ALERT_WEBHOOK_URL`, `NOTES_URL`, `NOTES_API_KEY`, and `SIDECAR_PASSWORD` are omitted from the settings representation. Logs record the drill name, the source kind, the status, and short failure messages. They do not record connection URLs, the webhook URL, or the notes key.

Text stored from an exception is passed through a redaction step first. That step masks the password in a URL userinfo (`scheme://user:password@`) and a `password=` query value. The restore stderr tail is masked the same way before it is stored. The container image copies the project sources, the lockfile, and migrations. It does not copy `.env`, and it does not bake a credential into the image.

Put real tokens in the environment or in the Kubernetes Secret. Leave the examples blank or set to the published placeholders.

## What a failure note sends

Notes are off unless `NOTES_ENABLED` is true. A model is called only when notes are on, `NOTES_URL` and `NOTES_MODEL` are both set, and the rule classifier returned `unknown`. A rule hit does not call the model. A disabled installation does not call the model and does not store a note.

The call is one HTTP POST to `{NOTES_URL}/chat/completions`. The body is JSON with `model` set to `NOTES_MODEL`, one user message, and `stream` set to false. When `NOTES_API_KEY` is non-empty, the request sends it as an `Authorization: Bearer` header to that endpoint. The key is not part of the prompt and is not logged. The client waits 10 seconds, tries once, and does not follow a redirect. A failed call raises `note request failed` with no URL and no key in the message. The rule result is kept.

The user message is the only prompt. It contains:

- instructions to reply with one JSON object and nothing else
- the allowed categories
- the assertion names, joined by commas, or `none` when the run has no assertion results
- the last 2000 characters of the stderr tail after masking

It does not include assertion SQL, observed values, or expected values as their own fields. Before the tail is added, the mask:

- drops `DETAIL:` and `CONTEXT:` lines, and on a mixed line drops from that field through the end of the line
- masks the value after `Key (...)=` and the row after `COPY <table>, line N:`
- replaces URL userinfo passwords and `password=` query values with `***`
- replaces email addresses, full URLs, IPv4 addresses, IPv6 addresses, dotted hostnames, and `localhost` with `[redacted]`
- replaces assignments to `password`, `passwd`, `pwd`, `PGPASSWORD`, `secret`, `token`, and `api_key` with `name=***`
- replaces assignments to `host`, `hostname`, and `hostaddr` with `name=***`
- replaces assignments to `observed` and `expected` with `name=***`
- replaces the quoted name in `host name "..."` and `host "..."` with `[redacted]`
- replaces `sk-` tokens and base64 or hex runs of 24 or more characters with `[redacted]`

A value that appears in the stderr tail without one of those shapes can remain in the prompt. Do not enable notes on stderr you are not willing to send to the configured endpoint.

A reply is stored only when it is one JSON object with `category`, `short_reason`, and `suggested_next_step`. `category` has to be one of the eight labels. Each text field has to be 1 to 300 characters after stripping. Any other reply is discarded. The stored note is marked as a suggestion. It does not ack the run, retry delivery, or change the run status.

## Reporting

Report a vulnerability through a private security advisory on [nishanttyagi28/pgrestoredrill](https://github.com/nishanttyagi28/pgrestoredrill/security/advisories/new). Do not open a public issue for a credential, a connection string, or a dump that contains private data. Bugs that do not expose a secret can use the public issue tracker.
