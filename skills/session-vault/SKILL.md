---
name: session-vault
description: "Set up and manage the session-vault: log your Claude Code (and Codex) sessions to your OWN agent-{firstname} BigQuery vault, with an optional liveness heartbeat and an optional GCS transcript backup. Opt-in and per-person; nothing uploads until you enable it. Use when someone wants to enable or install session logging, set up the memory/BigQuery vault, capture transcripts to BigQuery, back up transcripts, or manage/uninstall the vault. Triggers on: session vault, session-vault, log my sessions, session logging, memory vault, bigquery vault, upload sessions to bigquery, transcript vault, set up vault, enable session logging, heartbeat logging, uninstall vault."
---

> **Config:** all values come from `~/.claude/itg.config.json` (agent-allteam `docs/config-convention.md`). The `logging.*` block plus `gcp.personal_project`, `person.email`, `person.name` drive everything - nothing is hardcoded. Copy `templates/itg.config.example.json` if you have not already.

> **Where this skill lives / how to update it.** This skill ships in the **itg plugin**, so at runtime it loads from the plugin cache (`~/.claude/plugins/**/itg/skills/session-vault/`), NOT from a project repo. The **canonical source to edit is this file**, in `agent-allteam` under `plugins/itg/skills/session-vault/`. To change it: edit here on a branch, open a PR (this repo's `main` needs a code-owner approval), then refresh the cache: `claude plugin marketplace update itgenius && claude plugin update itg` (takes effect next session).

# Session Vault - log your Claude sessions to BigQuery

Streams every Claude Code turn (and, optionally, your Codex Desktop sessions) into a
BigQuery dataset in **your own** `agent-{firstname}` project. You then query your full
work history, and skills like `claude-vault` can search it.

**Opt-in and private.** The plugin ships inert. Nothing is written until you set
`logging.enabled: true` and run setup. Your data lands only in your own project.

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

- Your own `agent-{firstname}` GCP project, and `gcloud` logged in interactively with rights
  to create a service account + IAM in it (you own your project, so you have this).
- `gcloud` (with `bq`), `jq`, and `python3` on PATH.
- macOS (launchd) or Linux (cron; plus systemd for the optional 15s heartbeat).

## Set it up

1. Edit `~/.claude/itg.config.json`: set `logging.enabled: true` and confirm
   `gcp.personal_project` is your `agent-{firstname}` project. (Optional: set
   `logging.heartbeat_enabled` / `logging.backup_enabled`.)
2. Preview the plan (no changes, no credentials needed):
   `scripts/setup-vault.sh --dry-run`
3. Apply it (creates the dataset, tables, service account, IAM, isolated config, installs the
   hooks and the OS scheduler; confirm-gated):
   `scripts/setup-vault.sh`
4. Start a new Claude Code session. Rows appear in
   `<project>.claude_memory_vault.messages`.

Re-run `setup-vault.sh` any time (it is idempotent) after flipping a flag, e.g. to turn the
heartbeat or backup on.

## Config keys (in the `logging` block)

| Key | Default | Purpose |
|---|---|---|
| `enabled` | `false` | Master opt-in for the hooks |
| `bq_project` | `gcp.personal_project` | Project holding the vault |
| `bq_dataset` | `claude_memory_vault` | Vault dataset |
| `sa_secret_name` | `local-session-sync-sa-key` | GSM secret holding the SA key |
| `gcloud_config_dir` | `~/.config/gcloud-vault` | Isolated gcloud config |
| `offset_state_dir` | `~/.claude/hooks/.offsets` | Per-session line cursors |
| `heartbeat_enabled` | `false` | 15s liveness heartbeat |
| `backup_enabled` | `false` | Nightly GCS tarball backup |
| `gcs_backup_bucket` | `<project>-claude-vault-backup` | Backup bucket |
| `person.machine_name` | runtime host name | Override the machine tag |

## Verify and query

- Confirm resolution: `scripts/_vault.py --check`
- Recent rows, content search, per-machine activity: see [references/queries.md](references/queries.md).
- Table shapes: see [references/bq-schema.md](references/bq-schema.md).
- Design and rationale: see [references/architecture.md](references/architecture.md).

## Uninstall

`scripts/uninstall-vault.sh` removes the hooks, scheduler, installed scripts, and isolated
config. Your logged data stays in BigQuery. Add `--purge-cloud` to also delete the service
account and its key secret (data is still kept).

## Troubleshooting

- **`Reauthentication failed. cannot prompt during non-interactive execution`** - the isolated
  SA is the fix for exactly this. Re-run `setup-vault.sh`; confirm `gcloud_config_dir` holds the
  activated SA (`CLOUDSDK_CONFIG=<dir> gcloud auth list`).
- **Probe query fails right after setup** - IAM can take a minute to propagate. Re-run setup.
- **No rows appear** - check `logging.enabled` is true and that `~/.claude/settings.json` has the
  two hooks pointing at `~/.claude/session-vault/`. Hook logs are best-effort and silent by design.
- **Linux 15s heartbeat** - cron cannot fire every 15s. The heartbeat uses a systemd `--user`
  timer; on a host without systemd the heartbeat is unavailable (the rest of the vault still works).
- **IAM-admin missing** - you need rights to create a service account + bindings in your own
  project. Ask whoever owns your `agent-{firstname}` project if setup fails at the SA step.
