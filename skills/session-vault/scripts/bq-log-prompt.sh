#!/usr/bin/env bash
# session-vault: BigQuery logger for Claude Code UserPromptSubmit events.
# Reads the hook JSON from stdin and logs the user prompt to BigQuery.
# Best-effort: failures never block Claude. All targets come from
# ~/.claude/itg.config.json via _vault.py - nothing is hardcoded.
# No-op unless logging.enabled is true.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve config (always succeeds; stays best-effort even if python/_vault is absent).
VAULT_ENV="$(python3 "$DIR/_vault.py" --shell-env 2>/dev/null || true)"
eval "$VAULT_ENV"
[ "${VAULT_ENABLED:-0}" = "1" ] || exit 0
[ -n "${VAULT_BQ_PROJECT:-}" ] || exit 0

# shellcheck disable=SC1091
. "$DIR/lib/bq-timeout.sh" 2>/dev/null || true
if ! command -v run_with_timeout >/dev/null 2>&1; then
  run_with_timeout() { shift; "$@"; }  # no cap available - run directly
fi

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
# Current Claude Code sends `.prompt`; older builds used `.user_prompt`. Accept either.
USER_PROMPT=$(echo "$INPUT" | jq -r '.prompt // .user_prompt // empty')
PROJECT_DIR=$(echo "$INPUT" | jq -r '.cwd // empty')
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000000Z")

# Session ids are UUIDs. Validate before using in a file path or a BQ row: a crafted value
# must never traverse paths or reach an arithmetic/eval context downstream.
case "$SESSION_ID" in
  ""|*[!0-9A-Fa-f-]*) exit 0 ;;
esac

# Seed a per-session offset at 0 the first time we see a session, so the daily offset-flush
# sweep (vault-flush-offsets.py) can heal it even if the Stop hook never runs for this session.
OFFSET_DIR="${VAULT_OFFSET_DIR:-$HOME/.claude/hooks/.offsets}"
mkdir -p "$OFFSET_DIR" 2>/dev/null || true
[ -f "$OFFSET_DIR/$SESSION_ID" ] || printf '0' > "$OFFSET_DIR/$SESSION_ID" 2>/dev/null || true

# Detect client app (CLAUDE_CODE_ENTRYPOINT is the primary signal).
case "${CLAUDE_CODE_ENTRYPOINT:-}" in
    claude-vscode)    CLIENT="vscode" ;;
    claude-cursor)    CLIENT="cursor" ;;
    claude-windsurf)  CLIENT="windsurf" ;;
    claude-jetbrains) CLIENT="jetbrains" ;;
    *)
        if [ -n "${VSCODE_PID:-}" ] || [ "${TERM_PROGRAM:-}" = "vscode" ]; then
            CLIENT="vscode"
        elif [ -n "${CURSOR_CHANNEL:-}" ]; then
            CLIENT="cursor"
        else
            CLIENT="terminal"
        fi
        ;;
esac

# Machine identifier: config override, else scutil (macOS, preserves the case set in
# System Settings), else `hostname -s` (Linux yields the instance name). The absolute
# scutil path matters: it lives in /usr/sbin, which some callers do not carry on PATH,
# and a bare `scutil` would silently fall through and split one machine across identities.
MACHINE="${VAULT_MACHINE_NAME:-}"
if [ -z "$MACHINE" ] && [ -x /usr/sbin/scutil ]; then
  MACHINE=$(/usr/sbin/scutil --get LocalHostName 2>/dev/null || true)
fi
[ -n "$MACHINE" ] || MACHINE=$(hostname -s)

# Skip if no prompt.
[ -z "$USER_PROMPT" ] && exit 0

# Build one NDJSON row with jq --arg for injection-safe escaping.
ROW=$(jq -n -c \
    --arg sid "$SESSION_ID" \
    --arg ts "$TIMESTAMP" \
    --arg content "$USER_PROMPT" \
    --arg pdir "$PROJECT_DIR" \
    --arg client "$CLIENT" \
    --arg machine "$MACHINE" \
    '{session_id: $sid, timestamp: $ts, role: "user", content: $content, tool_calls: null, tool_results: null, project_dir: $pdir, model: "", client: $client, machine: $machine}')

if [ "${VAULT_DRY_RUN:-0}" = "1" ]; then
  echo "[dry-run] insert into ${VAULT_BQ_PROJECT}:${VAULT_MESSAGES_TABLE}"
  echo "$ROW"
  exit 0
fi

# Best-effort insert with a hard cap; failures are swallowed so Claude never blocks.
# Insert from a temp FILE (bq insert's file-arg form), not a pipe: piping through the timeout
# fallback loses stdin under macOS's bash 3.2, silently inserting zero rows.
export CLOUDSDK_CONFIG="$VAULT_GCLOUD_CONFIG"
ROWFILE=$(mktemp -t session-vault-prompt.XXXXXX) || exit 0
printf '%s\n' "$ROW" > "$ROWFILE"
run_with_timeout 10 bq insert --project_id="$VAULT_BQ_PROJECT" "$VAULT_MESSAGES_TABLE" "$ROWFILE" >/dev/null 2>&1 || true
rm -f "$ROWFILE"
