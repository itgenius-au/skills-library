---
name: session-vault
description: "Set up and manage session-vault: log your Claude Code (and Codex) sessions to your OWN BigQuery project, with an optional liveness heartbeat and an optional GCS transcript backup. Opt-in and private; nothing uploads until you enable it. Use when someone wants to enable or install session logging, set up the memory/BigQuery vault, capture transcripts to BigQuery, back up transcripts, or manage/uninstall the vault. Triggers on: session vault, session-vault, log my sessions, session logging, memory vault, bigquery vault, upload sessions to bigquery, transcript vault, set up vault, enable session logging, heartbeat logging, uninstall vault."
---

# Session Vault - log your Claude sessions to BigQuery

Streams every Claude Code turn (and, optionally, your Codex Desktop sessions) into a
BigQuery dataset in **your own** Google Cloud project. You then query your full work
history with plain BigQuery SQL.

**Opt-in and private.** This skill ships inert. Nothing is written until you create a
config file with `enabled: true` and run setup. Your data lands only in your own project;
nothing is sent anywhere else.

## How it works (two tiers)

- **Live (per turn):** a `UserPromptSubmit` hook logs each prompt; a `Stop` hook logs the
  new transcript lines at the end of every turn. Both are best-effort and never block Claude.
- **Scheduled (daily):** a bulk sync catches anything the hooks missed, an offset-flush sweep
  heals gaps, and subagent + Codex transcripts are pulled in. Two extras are **off by default**:
  a 15s liveness **heartbeat** and a nightly **GCS backup** of your raw transcripts.

All BigQuery jobs run as a dedicated **least-privilege service account** in an **isolated
gcloud config**, so non-interactive jobs never hit Google's session-control reauth wall and
never disturb your normal `gcloud` login.

## Prerequisites

- A Google Cloud project, and `gcloud` logged in interactively with rights to create a
  service account + IAM in it (your own project, so you have this).
- `gcloud` (with `bq`), `jq`, and `python3` on PATH.
- macOS (launchd) or Linux (cron; plus systemd for the optional 15s heartbeat).

## Config

Everything is read from one flat, skill-owned JSON file: `~/.claude/session-vault.config.json`
(override the path with the `SESSION_VAULT_CONFIG` env var, mainly useful for tests or a
scratch-dataset dry-run). Copy `templates/session-vault.config.example.json` to get started,
or let `setup-vault.sh` write it for you interactively (see below).

| Key | Default | Purpose |
|---|---|---|
| `enabled` | `false` | Master opt-in for the hooks |
| `bq_project` | _(required)_ | Google Cloud project holding the vault |
| `bq_dataset` | `claude_memory_vault` | Vault dataset |
| `heartbeat_enabled` | `false` | 15s liveness heartbeat |
| `backup_enabled` | `false` | Nightly GCS tarball backup |
| `gcs_backup_bucket` | `<project>-claude-vault-backup` | Backup bucket |
| `sa_secret_name` | `local-session-sync-sa-key` | Secret Manager secret holding the SA key |
| `gcloud_config_dir` | `~/.config/gcloud-vault` | Isolated gcloud config |
| `offset_state_dir` | `~/.claude/hooks/.offsets` | Per-session line cursors |
| `machine_name` | runtime host name | Override the machine tag on each row |

Only `bq_project` is required once `enabled` is `true`; every other key has a working
default.

## Set it up

1. Run `scripts/setup-vault.sh --dry-run` first (no changes, no credentials needed). If
   `~/.claude/session-vault.config.json` does not exist yet, the real (non-dry-run) run
   prompts you for your Google Cloud project and writes it; a dry-run just reports what it
   would ask. You can also copy `templates/session-vault.config.example.json` yourself,
   fill in `bq_project`, and set `enabled: true`.
2. Preview the plan again once the config is in place:
   `scripts/setup-vault.sh --dry-run`
3. Apply it (creates the dataset, tables, service account, IAM, isolated config, installs
   the hooks and the OS scheduler; confirm-gated):
   `scripts/setup-vault.sh`
4. Start a new Claude Code session. Rows appear in `<project>.claude_memory_vault.messages`.

Re-run `setup-vault.sh` any time (it is idempotent) after editing the config, e.g. to turn
the heartbeat or backup on.

## Verify and query

- Confirm resolution: `scripts/_vault.py --check`
- Recent rows, content search, per-machine activity: see [references/queries.md](references/queries.md).
- Table shapes: see [references/bq-schema.md](references/bq-schema.md).
- Design and rationale: see [references/architecture.md](references/architecture.md).

## Uninstall

`scripts/uninstall-vault.sh` removes the hooks, scheduler, installed scripts, and isolated
config. Your logged data stays in BigQuery. Add `--purge-cloud` to also delete the service
account and its key secret (data is still kept). Your config file is left alone.

## Troubleshooting

- **`Reauthentication failed. cannot prompt during non-interactive execution`** - the isolated
  SA is the fix for exactly this. Re-run `setup-vault.sh`; confirm `gcloud_config_dir` holds the
  activated SA (`CLOUDSDK_CONFIG=<dir> gcloud auth list`).
- **Probe query fails right after setup** - IAM can take a minute to propagate. Re-run setup.
- **No rows appear** - check `enabled` is `true` in `~/.claude/session-vault.config.json` and that
  `~/.claude/settings.json` has the two hooks pointing at `~/.claude/session-vault/`. Hook logs are
  best-effort and silent by design.
- **Linux 15s heartbeat** - cron cannot fire every 15s. The heartbeat uses a systemd `--user`
  timer; on a host without systemd the heartbeat is unavailable (the rest of the vault still works).
- **IAM-admin missing** - you need rights to create a service account + bindings in your own
  project. Ask whoever owns the project if setup fails at the SA step.
