# BigQuery schema

The vault uses one dataset (default `claude_memory_vault`) with two tables. `setup-vault.sh`
creates them from the machine-readable schemas in `scripts/schema/`:

- `scripts/schema/messages.schema.json`
- `scripts/schema/session_heartbeat.schema.json`

## `messages`

One row per user prompt, assistant message, or tool event. The table is a **superset**: the
hooks populate the common columns; the rest are nullable and stay empty unless a richer
producer fills them, so the schema is stable as capture grows.

Core columns the shipped hooks write:

| Column | Type | Notes |
|---|---|---|
| `session_id` | STRING | Claude Code session id |
| `timestamp` | TIMESTAMP | Per-line time, else batch ingest time |
| `uuid` / `parent_uuid` | STRING | Row id + parent, for tree reconstruction |
| `role` | STRING | user / assistant / tool |
| `content` | STRING | Text content |
| `tool_calls` | STRING | Stringified tool_use blocks (STRING, not repeated) |
| `project_dir` | STRING | cwd at row time (follows EnterWorktree) |
| `model` | STRING | e.g. the assistant model id |
| `client` | STRING | vscode / cursor / terminal |
| `machine` | STRING | Host tag (config override, else scutil/hostname) |
| `git_branch` | STRING | Branch at row time |
| `input_tokens` / `output_tokens` | INTEGER | From usage |
| `cache_creation_input_tokens` / `cache_read_input_tokens` | INTEGER | From usage |
| `stop_reason`, `cc_version`, `attribution_skill`, `effort` | STRING | Turn metadata |
| `is_sidechain` | BOOLEAN | True for subagent rows |
| `event_type` | STRING | Top-level type / backfill marker |

Additional nullable columns exist for future enrichment (`cost_usd`, `organization_uuid`,
`subscription_type`, `permission_mode`, `entrypoint`, `message_id`, `request_id`, `prompt_id`,
`service_tier`, `user_type`, `level`, `subtype`, `iterations_json`, `is_rate_limit`,
`tool_results`). See `scripts/schema/messages.schema.json` for the full list.

## `session_heartbeat` (only when `heartbeat_enabled`)

One row per active session per heartbeat tick.

| Column | Type |
|---|---|
| `session_id` | STRING |
| `machine` | STRING |
| `project_dir` | STRING |
| `git_branch` | STRING |
| `last_active` | TIMESTAMP |
| `ingested_at` | TIMESTAMP |

A liveness monitor takes `MAX(last assistant row timestamp, heartbeat.last_active)` as a
session's effective activity, and prefers the heartbeat's `project_dir`/`git_branch` because
they refresh every ~15s (immune to a stale Stop-event launch dir).
