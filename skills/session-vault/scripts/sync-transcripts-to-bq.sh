#!/usr/bin/env bash
# session-vault: bulk-sync local Claude Code JSONL transcripts to BigQuery.
# Finds main-session transcripts not yet in BQ, parses them into NDJSON, and batch-loads via
# bq load, then fans out to the subagent and Codex python syncers. Safe to re-run (idempotent):
# sessions already in BQ are skipped. All targets come from ~/.claude/session-vault.config.json via
# _vault.py - nothing is hardcoded. No-op unless enabled.
#
# Usage: ./sync-transcripts-to-bq.sh [--dry-run]   (or set VAULT_DRY_RUN=1)
#
# Run before machine moves, periodically, or whenever you want a full vault backup.
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

# Authenticate as the isolated least-privilege vault gcloud config (see setup). Exporting it here
# means a manual run and the scheduled unit hit the same credentials.
export CLOUDSDK_CONFIG="$VAULT_GCLOUD_CONFIG"

# bq needs an explicit project. gcloud's default project is often unset (notably on a fresh
# machine right after a move), and the bq calls below without --project_id would die with
# "Cannot start a job without a project id". Export the resolved project so every bq invocation
# inherits it. (See memory: "bq cp Needs --project_id".)
export CLOUDSDK_CORE_PROJECT="${CLOUDSDK_CORE_PROJECT:-$VAULT_BQ_PROJECT}"

CLAUDE_PROJECTS="$HOME/.claude/projects"

# Machine identifier: config override, else scutil (macOS), else hostname -s (Linux).
# Absolute /usr/sbin/scutil: a scheduler (launchd/systemd) may not put /usr/sbin on PATH, so a
# bare `scutil` silently falls through to `hostname -s` - which would stamp rows into the SAME
# messages table under a second hostname for the same box.
MACHINE="${VAULT_MACHINE_NAME:-}"
if [ -z "$MACHINE" ] && [ -x /usr/sbin/scutil ]; then
  MACHINE=$(/usr/sbin/scutil --get LocalHostName 2>/dev/null || true)
fi
[ -n "$MACHINE" ] || MACHINE=$(hostname -s)

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true
[ "${VAULT_DRY_RUN:-0}" = "1" ] && DRY_RUN=true

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}+${NC} $1"; }
skip() { echo -e "  ${YELLOW}-${NC} $1"; }
fail() { echo -e "  ${RED}x${NC} $1"; }

FQ_TABLE="${VAULT_BQ_PROJECT}.${VAULT_MESSAGES_TABLE}"

if [[ "$DRY_RUN" == true ]]; then
  echo -e "${YELLOW}DRY RUN${NC} - resolved target: ${VAULT_BQ_PROJECT}:${VAULT_MESSAGES_TABLE} (no bq/gcs writes)"
fi

# ─────────────────────────────────────────────
# 1. Get sessions already in BQ
# ─────────────────────────────────────────────
echo "=== Fetching existing BQ sessions ==="

# 300s cap: a wedged query (no bq client timeout) would otherwise hang this daily job forever
# under its non-overlapping scheduler. On timeout run_with_timeout returns 124, pipefail
# propagates it, and set -e aborts the run cleanly - the next day's run retries.
BQ_SESSIONS=$(run_with_timeout 300 bq query --nouse_legacy_sql --format=csv --max_rows=10000 \
  "SELECT DISTINCT session_id FROM \`${FQ_TABLE}\`" \
  | tail -n +2)  # skip header

BQ_COUNT=$(echo "$BQ_SESSIONS" | grep -c . || true)
echo "  Found $BQ_COUNT sessions already in BQ"

# ─────────────────────────────────────────────
# 2. Find local JSONL files not yet in BQ
# ─────────────────────────────────────────────
echo ""
echo "=== Scanning local transcripts ==="

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Build the lookup set as a sorted file (portable: macOS /bin/bash is 3.2 and has no associative
# arrays). Membership is tested with `grep -qxF` below.
EXISTING_FILE="$TMPDIR/existing_sessions.txt"
printf '%s\n' "$BQ_SESSIONS" | grep -v '^$' | sort -u > "$EXISTING_FILE" || true

NEW_COUNT=0
SKIP_COUNT=0
TOTAL_COUNT=0

# Find all main session JSONL files (skip subagent transcripts)
while IFS= read -r jsonl_file; do
  TOTAL_COUNT=$((TOTAL_COUNT + 1))

  # Extract session ID from filename (UUID.jsonl)
  filename=$(basename "$jsonl_file" .jsonl)

  # Skip non-UUID filenames
  if ! [[ "$filename" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    continue
  fi

  # Skip if already in BQ
  if grep -qxF "$filename" "$EXISTING_FILE"; then
    SKIP_COUNT=$((SKIP_COUNT + 1))
    continue
  fi

  # Derive project dir from path
  # Path: ~/.claude/projects/{cache-key}/{session-id}.jsonl
  project_cache_key=$(basename "$(dirname "$jsonl_file")")
  # Convert cache key back to path: -Users-foo-bar -> /Users/foo/bar
  project_dir="${project_cache_key//-//}"

  # Parse JSONL into BQ-compatible NDJSON
  jq -c --arg sid "$filename" --arg pdir "$project_dir" --arg machine "$MACHINE" '
    # Extract role/type
    (.role // .type // "unknown") as $role |

    # Extract timestamp (use message timestamp if available, else empty)
    (.timestamp // "" | tostring) as $ts |

    # Extract text content
    (if .message.content then
        (.message.content | if type == "array" then
            [.[] | select(.type == "text") | .text] | join("\n")
        else . end)
    elif .content then
        (if .content | type == "array" then
            [.content[] | select(.type == "text") | .text] | join("\n")
        elif .content | type == "string" then .content
        else "" end)
    elif .snapshot then
        (.snapshot | tostring | .[0:1000])
    else "" end) as $content |

    # Extract tool calls (guard on array type: iterating a string .content throws and would
    # drop the whole row via the 2>/dev/null on the jq call)
    (if (.message.content | type) == "array" then
        [.message.content[] | select(.type == "tool_use")] | if length > 0 then . else null end
    elif (.content | type) == "array" then
        [.content[] | select(.type == "tool_use")] | if length > 0 then . else null end
    else null end) as $tool_calls |

    # Extract model
    (.model // "") as $model |

    # Skip progress events and empty content (too noisy for vault)
    select($role != "progress" and ($content != "" or $tool_calls != null)) |

    # Build the row
    {
      "session_id": $sid,
      "timestamp": (if $ts != "" and ($ts | test("^[0-9]{4}")) then $ts else now | strftime("%Y-%m-%dT%H:%M:%S.000000Z") end),
      "role": $role,
      "content": $content,
      "tool_calls": (if $tool_calls then ($tool_calls | tostring) else null end),
      "tool_results": null,
      "project_dir": $pdir,
      "model": $model,
      "client": null,
      "machine": $machine
    }
  ' "$jsonl_file" 2>/dev/null >> "$TMPDIR/batch.ndjson" || true

  NEW_COUNT=$((NEW_COUNT + 1))

done < <(find "$CLAUDE_PROJECTS" -maxdepth 2 -name "*.jsonl" -not -path "*/subagents/*" 2>/dev/null)

echo "  Total local: $TOTAL_COUNT | Already in BQ: $SKIP_COUNT | New: $NEW_COUNT"

# ─────────────────────────────────────────────
# 3. Upload to BQ
# ─────────────────────────────────────────────
echo ""

if [[ $NEW_COUNT -eq 0 ]]; then
  echo -e "${GREEN}All main sessions already in BQ.${NC}"
else
  ROW_COUNT=$(wc -l < "$TMPDIR/batch.ndjson" | tr -d ' ')
  FILE_SIZE=$(du -h "$TMPDIR/batch.ndjson" | cut -f1)
  echo "=== Uploading $ROW_COUNT rows ($FILE_SIZE) from $NEW_COUNT sessions ==="

  if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}DRY RUN - skipping upload${NC}"
    echo "  Would load: $TMPDIR/batch.ndjson"
    echo "  Into:       ${VAULT_BQ_PROJECT}:${VAULT_MESSAGES_TABLE}"
  elif run_with_timeout 300 bq load --source_format=NEWLINE_DELIMITED_JSON \
    --max_bad_records=100 \
    --project_id="$VAULT_BQ_PROJECT" \
    "$VAULT_MESSAGES_TABLE" \
    "$TMPDIR/batch.ndjson"; then
    echo -e "${GREEN}Done!${NC} Uploaded $ROW_COUNT rows from $NEW_COUNT new sessions."
  else
    fail "bq load failed"
    echo "  Batch file preserved at: $TMPDIR/batch.ndjson"
    trap '' EXIT  # don't clean up on failure
    exit 1
  fi
fi

# ─────────────────────────────────────────────
# 4. Subagent (sidechain) sync
# ─────────────────────────────────────────────
# Real-time hooks never capture subagent transcripts, and the main sync above
# explicitly skips them. Run the dedicated Python helper for sidechain content.
echo ""
echo "=== Subagent (sidechain) sync ==="
if [[ -x "$DIR/sync-subagents-to-bq.py" ]]; then
  # Explicit branches, not "${ARR[@]}" - an empty indexed array under `set -u` is an "unbound
  # variable" error on macOS bash 3.2. 1800s cap: these helpers make their own bq calls.
  if [[ "$DRY_RUN" == true ]]; then
    run_with_timeout 1800 "$DIR/sync-subagents-to-bq.py" --dry-run || fail "subagent sync failed"
  else
    run_with_timeout 1800 "$DIR/sync-subagents-to-bq.py" || fail "subagent sync failed"
  fi
else
  skip "sync-subagents-to-bq.py not found or not executable - skipping sidechain sync"
fi

# ─────────────────────────────────────────────
# 5. Codex sync
# ─────────────────────────────────────────────
# Codex stores transcripts under ~/.codex/sessions and ~/.codex/archived_sessions, not
# ~/.claude/projects, so neither Claude Code hooks nor the main Claude JSONL scan can see them.
echo ""
echo "=== Codex sync ==="
if [[ -x "$DIR/sync-codex-transcripts-to-bq.py" ]]; then
  if [[ "$DRY_RUN" == true ]]; then
    run_with_timeout 1800 "$DIR/sync-codex-transcripts-to-bq.py" --dry-run || fail "Codex sync failed"
  else
    run_with_timeout 1800 "$DIR/sync-codex-transcripts-to-bq.py" || fail "Codex sync failed"
  fi
else
  skip "sync-codex-transcripts-to-bq.py not found or not executable - skipping Codex sync"
fi
