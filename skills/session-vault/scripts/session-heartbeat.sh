#!/usr/bin/env bash
# session-vault: write a per-session "last active" heartbeat to BigQuery from transcript
# file mtimes. OPTIONAL - runs only when heartbeat_enabled is true.
#
# Why: the Stop hook only writes a row when a TURN ENDS, so a session in a long multi-tool
# turn has no fresh row for many minutes and a liveness monitor wrongly marks it stale. The
# transcript .jsonl is appended on every tool call / thinking block, so its mtime tracks real
# activity continuously. Run every ~15s (launchd) or by a systemd timer, this captures that
# mtime plus the session's current cwd + branch, read from the transcript tail.
#
# All targets come from ~/.claude/session-vault.config.json via _vault.py - nothing is hardcoded.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VAULT_ENV="$(python3 "$DIR/_vault.py" --shell-env 2>/dev/null || true)"
eval "$VAULT_ENV"
[ "${VAULT_ENABLED:-0}" = "1" ] || exit 0
[ "${VAULT_HEARTBEAT_ENABLED:-0}" = "1" ] || exit 0
[ -n "${VAULT_BQ_PROJECT:-}" ] || exit 0

# shellcheck disable=SC1091
. "$DIR/lib/bq-timeout.sh" 2>/dev/null || true
if ! command -v run_with_timeout >/dev/null 2>&1; then
  run_with_timeout() { shift; "$@"; }  # no cap available - run directly
fi

# Authenticate as the isolated least-privilege vault SA (see setup-vault.sh). Defaulting it
# here means a manual run, and the Linux systemd unit, hit the same SA the launchd agent uses.
export CLOUDSDK_CONFIG="$VAULT_GCLOUD_CONFIG"

# Machine identifier: config override, else scutil (macOS), else hostname -s (Linux).
MACHINE="${VAULT_MACHINE_NAME:-}"
if [ -z "$MACHINE" ] && [ -x /usr/sbin/scutil ]; then
  MACHINE=$(/usr/sbin/scutil --get LocalHostName 2>/dev/null || true)
fi
[ -n "$MACHINE" ] || MACHINE=$(hostname -s)

# File mtime and epoch->ISO differ between GNU (Linux) and BSD (macOS). Probe ONCE and bind
# the right implementations, rather than trying the GNU form per file and falling back on error.
if stat -c %Y . >/dev/null 2>&1; then
  _mtime()     { stat -c %Y "$1"; }                                        # GNU
  _epoch_iso() { date -u -d "@$1" +"%Y-%m-%dT%H:%M:%S.000000Z"; }
else
  _mtime()     { stat -f %m "$1"; }                                        # BSD
  _epoch_iso() { date -u -r "$1" +"%Y-%m-%dT%H:%M:%S.000000Z"; }
fi

NOW_TS=$(date -u +"%Y-%m-%dT%H:%M:%S.000000Z")
# VAULT_PROJECTS_DIR overrides the scan root (used by tests); else the standard transcripts dir.
PROJECTS="${VAULT_PROJECTS_DIR:-$HOME/.claude/projects}"
TMP=$(mktemp -t session-heartbeat.XXXXXX) || exit 0
trap 'rm -f "$TMP"' EXIT

# Main-session transcripts touched in the last hour (skip subagent sidechains). A wide window
# keeps recently-idle sessions refreshing their real cwd/branch so worktree detection heals;
# last_active stays the true file mtime, so it does not fake activity.
while IFS= read -r f; do
  sid=$(basename "$f" .jsonl)
  [[ "$sid" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || continue
  # Skip metadata-only stubs (queue-operation / last-prompt / custom-title sidecars that never
  # hold a conversation). A real session passes as soon as its first assistant message lands.
  grep -q -m1 '"type":"assistant"' "$f" 2>/dev/null || continue
  epoch=$(_mtime "$f" 2>/dev/null) || continue
  [ -n "$epoch" ] || continue
  last_active=$(_epoch_iso "$epoch" 2>/dev/null) || continue
  # Current cwd from the transcript tail (last line carrying a cwd) tracks EnterWorktree moves.
  # The transcript .gitBranch is captured at LAUNCH and goes stale after a move, so read the
  # authoritative branch from git at that cwd; fall back to the transcript value only if git cannot.
  IFS=$'\t' read -r cwd tbranch < <(tail -n 40 "$f" 2>/dev/null \
    | jq -rs 'map(select(.cwd)) | last | "\(.cwd // "")\t\(.gitBranch // "")"' 2>/dev/null)
  branch=""
  [ -n "$cwd" ] && [ -d "$cwd" ] && branch=$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null)
  [ -z "$branch" ] && branch="$tbranch"
  jq -nc --arg sid "$sid" --arg machine "$MACHINE" --arg la "$last_active" --arg ing "$NOW_TS" \
     --arg pdir "${cwd:-}" --arg br "${branch:-}" \
     '{session_id:$sid, machine:$machine, last_active:$la, ingested_at:$ing,
       project_dir:(if $pdir=="" then null else $pdir end),
       git_branch:(if $br=="" then null else $br end)}' >> "$TMP"
done < <(find "$PROJECTS" -maxdepth 2 -name "*.jsonl" -not -path "*/subagents/*" -mmin -60 2>/dev/null)

[ -s "$TMP" ] || exit 0

if [ "${VAULT_DRY_RUN:-0}" = "1" ]; then
  echo "[dry-run] insert into ${VAULT_BQ_PROJECT}:${VAULT_HEARTBEAT_TABLE}"
  cat "$TMP"
  exit 0
fi

# 30s cap: a normal insert is <5s and the agent fires every ~15s, so a wedged insert dies and
# the next interval starts clean. stderr is NOT suppressed, so a real bq error lands in the log.
run_with_timeout 30 bq insert --project_id="$VAULT_BQ_PROJECT" "$VAULT_HEARTBEAT_TABLE" "$TMP" || true
