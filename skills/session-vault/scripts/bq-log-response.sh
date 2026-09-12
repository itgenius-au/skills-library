#!/usr/bin/env bash
# session-vault: BigQuery logger for Claude Code Stop events.
# Reads the JSONL transcript, finds new lines since the last log via a per-session
# offset file, and batch-inserts them to BigQuery in one call. The offset advances
# ONLY on a successful insert, so a failed insert is retried on the next Stop event.
# All targets come from ~/.claude/itg.config.json via _vault.py. No-op unless enabled.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
PROJECT_DIR=$(echo "$INPUT" | jq -r '.cwd // empty')

# Session ids are UUIDs. Validate before using in the offset file path or a BQ row.
case "$SESSION_ID" in
  ""|*[!0-9A-Fa-f-]*) exit 0 ;;
esac

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

# Machine identifier: config override, else scutil (macOS), else hostname -s (Linux).
MACHINE="${VAULT_MACHINE_NAME:-}"
if [ -z "$MACHINE" ] && [ -x /usr/sbin/scutil ]; then
  MACHINE=$(/usr/sbin/scutil --get LocalHostName 2>/dev/null || true)
fi
[ -n "$MACHINE" ] || MACHINE=$(hostname -s)

# Per-session reasoning effort. CLAUDE_EFFORT is set per session and the hook inherits it.
EFFORT="${CLAUDE_EFFORT:-}"

# Skip if no transcript.
[ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ] && exit 0

# Track last-logged line per session.
OFFSET_DIR="${VAULT_OFFSET_DIR:-$HOME/.claude/hooks/.offsets}"
mkdir -p "$OFFSET_DIR"
OFFSET_FILE="${OFFSET_DIR}/${SESSION_ID}"
LAST_LINE=0
[ -f "$OFFSET_FILE" ] && LAST_LINE=$(cat "$OFFSET_FILE")
# The offset feeds an arithmetic context ($((LAST_LINE + 1))); force it to a plain base-10
# integer so a tampered/garbage offset can never inject an expression, and a value like "010"
# is not misread as octal.
case "$LAST_LINE" in ''|*[!0-9]*) LAST_LINE=0 ;; esac
LAST_LINE=$((10#$LAST_LINE))

TOTAL_LINES=$(wc -l < "$TRANSCRIPT_PATH" | tr -d ' ')
[ "$TOTAL_LINES" -le "$LAST_LINE" ] && exit 0

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000000Z")

# Capture jq's exit code: if jq cannot parse a line, we must NOT advance the offset (that would
# drop the unparsed rows forever). set +e around the pipeline so pipefail's code reaches jq_rc.
set +e
NDJSON=$(tail -n +"$((LAST_LINE + 1))" "$TRANSCRIPT_PATH" | jq -c --arg sid "$SESSION_ID" --arg ts "$TIMESTAMP" --arg pdir "$PROJECT_DIR" --arg client "$CLIENT" --arg machine "$MACHINE" --arg effort "$EFFORT" '
    # ROW-BUILDER-BEGIN
    (.role // .type // "unknown") as $role |
    (if .message.content then
        (.message.content | if type == "array" then
            [.[] | select(.type == "text") | .text] | join("\n")
        else . end)
    elif .content then
        (if .content | type == "array" then
            [.content[] | select(.type == "text") | .text] | join("\n")
        elif .content | type == "string" then .content
        else "" end)
    else "" end) as $content |
    (if (.message.content | type) == "array" then
        [.message.content[] | select(.type == "tool_use")] | if length > 0 then . else null end
    elif (.content | type) == "array" then
        [.content[] | select(.type == "tool_use")] | if length > 0 then . else null end
    else null end) as $tool_calls |
    # model lives at .message.model in current Claude Code (.model is legacy/empty)
    (.message.model // .model // "") as $model |
    (.gitBranch // "") as $git_branch |
    (.message.usage // {}) as $usage |
    (.message.stop_reason // "") as $stop_reason |
    (.version // "") as $cc_version |
    (.uuid // "") as $uuid |
    (.attributionSkill // "") as $attr_skill |
    # Prefer the per-line transcript timestamp so multiple rows from one batch keep
    # distinct, correctly-ordered times ($ts is a single batch-wide ingestion fallback).
    ((.timestamp // "") | tostring) as $line_ts |
    (if ($line_ts | test("^[0-9]{4}")) then $line_ts else $ts end) as $ts_final |
    select($content != "" or $tool_calls != null) |
    {
        "session_id": $sid,
        "timestamp": $ts_final,
        "uuid": (if $uuid != "" then $uuid else null end),
        "role": $role,
        "content": $content,
        "tool_calls": (if $tool_calls then ($tool_calls | tostring) else null end),
        "tool_results": null,
        # per-line cwd follows worktree moves (EnterWorktree); $pdir is the Stop-event launch dir (fallback)
        "project_dir": (.cwd // $pdir),
        "model": (if $model != "" then $model else null end),
        "client": $client,
        "machine": $machine,
        "git_branch": (if $git_branch != "" then $git_branch else null end),
        "input_tokens": ($usage.input_tokens // null),
        "output_tokens": ($usage.output_tokens // null),
        "cache_creation_input_tokens": ($usage.cache_creation_input_tokens // null),
        "cache_read_input_tokens": ($usage.cache_read_input_tokens // null),
        "stop_reason": (if $stop_reason != "" then $stop_reason else null end),
        "cc_version": (if $cc_version != "" then $cc_version else null end),
        "attribution_skill": (if $attr_skill != "" then $attr_skill else null end),
        "effort": (if $effort != "" then $effort else null end)
    }
    # ROW-BUILDER-END
' 2>/dev/null)
jq_rc=$?
set -e

# jq could not parse a line: do NOT advance the offset - retry on the next Stop event so no
# rows are silently lost. (The row-builder is type-guarded, so this fires only on genuinely
# malformed transcript JSON, e.g. a partially-written last line, which heals next turn.)
if [ "$jq_rc" -ne 0 ]; then
  exit 0
fi

# jq succeeded with zero matching rows: safe to advance (unless dry-run) and stop.
if [ -z "$NDJSON" ]; then
  [ "${VAULT_DRY_RUN:-0}" = "1" ] || echo "$TOTAL_LINES" > "$OFFSET_FILE"
  exit 0
fi

if [ "${VAULT_DRY_RUN:-0}" = "1" ]; then
  echo "[dry-run] batch insert into ${VAULT_BQ_PROJECT}:${VAULT_MESSAGES_TABLE}"
  echo "$NDJSON"
  exit 0
fi

# Single batch insert from a temp FILE (not a pipe): piping through the timeout fallback loses
# stdin under macOS bash 3.2. Advance the offset only on a successful insert.
export CLOUDSDK_CONFIG="$VAULT_GCLOUD_CONFIG"
NDFILE=$(mktemp -t session-vault-resp.XXXXXX) || exit 0
printf '%s\n' "$NDJSON" > "$NDFILE"
if run_with_timeout 30 bq insert --project_id="$VAULT_BQ_PROJECT" "$VAULT_MESSAGES_TABLE" "$NDFILE" >/dev/null 2>&1; then
    echo "$TOTAL_LINES" > "$OFFSET_FILE"
fi
rm -f "$NDFILE"
