# Architecture

The vault captures Claude Code (and optionally Codex) sessions into BigQuery in two tiers,
plus an optional backup. Everything is per-person and opt-in.

## Data flow

```
Claude Code turn
  UserPromptSubmit -> bq-log-prompt.sh  --\
  Stop             -> bq-log-response.sh --+-> bq insert -> <project>.<dataset>.messages
scheduler (launchd / cron / systemd)
  daily -> vault-flush-offsets.py   (re-run Stop hook for idle lagging sessions: self-heal)
  daily -> sync-transcripts-to-bq.sh -> messages  (+ sync-subagents-to-bq.py, + sync-codex-transcripts-to-bq.py)
  daily -> backup-transcripts-to-gcs.py -> gs://<bucket>/<machine>/<date>.tgz   (optional)
  15s   -> session-heartbeat.sh -> session_heartbeat   (optional)
```

## Why two tiers

The `Stop` hook only writes when a turn ends, so a long multi-tool turn leaves a gap. The
scheduled sync + offset-flush close gaps from missed or failed hook inserts (the offset file
advances only on a successful insert, so a failure is retried, never silently dropped). The
optional 15s heartbeat gives near-real-time liveness for a monitor, separate from the message log.

## Why an isolated service account

Non-interactive jobs (hooks, launchd, cron) must not run as your interactive Google login: an
org "Google Cloud session control" policy makes a lapsed session fail with
`Reauthentication failed. cannot prompt during non-interactive execution`, and the telemetry
stops silently. The fix is a dedicated **least-privilege** service account
(`bigquery.jobUser` + `bigquery.dataEditor`, plus `storage.objectAdmin` on the backup bucket
when backup is on), activated in an **isolated** `CLOUDSDK_CONFIG` so it never touches or churns
your normal `gcloud` login.

## Reliability details

- **bq timeout wrapper** (`lib/bq-timeout.sh`): `bq` has no client-side timeout and can wedge on
  a dead socket; under a non-overlapping scheduler one hung run blocks all later runs. Each `bq`
  call is capped and its whole process subtree is killed on timeout.
- **Portability**: machine name via `scutil` (macOS) or `hostname -s` (Linux); GNU vs BSD `stat`
  and `date` are probed once; hooks use `jq --arg` for injection-safe row building.
- **Dedup / idempotency**: the bulk sync skips sessions already in BigQuery; the subagent and
  Codex syncers dedup by uuid / session id; re-running any script is safe.
- **Backup**: a tarball of `~/.claude/projects` + `~/.codex` to a GCS bucket in your own project;
  retention is a 35-day object-lifecycle rule (no manual pruning); no domain-wide delegation.

## Scheduling per OS

- **macOS**: launchd agents (`com.itgenius.session-vault.*`) - daily sync/flush/backup and the
  15s heartbeat via `StartInterval`.
- **Linux**: cron for the daily jobs; the 15s heartbeat needs a systemd `--user` timer (cron's
  floor is one minute).

## Known limitations

- **Duplicate rows are possible, loss is not.** `bq insert` streams without an `insert_id`, so a
  retry or two concurrent runs can write the same row twice. Dedup in queries by `uuid` (or
  `session_id` + `timestamp`). The design favours at-least-once (never dropping a row) over
  exactly-once. The offset advances only on a successful insert, and `jq` parse failures do not
  advance it, so rows are retried rather than lost.
- **Offline session growth.** The daily bulk sync skips a session whose id is already in the
  vault, so lines appended to a session while the live hooks were NOT running are not re-scanned
  by the bulk pass. The prompt hook seeds a per-session offset and `vault-flush-offsets.py` then
  sweeps any session the hooks touched, which covers the common case; a session that grew with no
  hook activity at all is the residual gap.
- **Modern bash recommended on macOS.** The scripts avoid bash-4-only features and work under the
  stock `/bin/bash` 3.2, but the launchd/systemd units put Homebrew's `bash` first on PATH; a
  modern bash is the tested configuration.

## Not included (v1)

Historical backfill of pre-existing transcripts is deferred to a later version. The setup does
not import history; it captures from install time forward, plus the daily catch-up.
