#!/usr/bin/env bash
# Safety gate: with enabled=false, EVERY script must be a silent no-op (exit 0, no
# output, no cloud call). This proves a user who installs the skill uploads nothing
# until they explicitly opt in.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SV="$(cd "$DIR/.." && pwd)"
fail=0

SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT
printf '%s\n' '{ "enabled": false }' > "$SCRATCH/off.json"
export SESSION_VAULT_CONFIG="$SCRATCH/off.json"

check() {
  local name="$1" rc="$2" out="$3"
  if [ "$rc" -ne 0 ]; then
    echo "FAIL: $name exited $rc (expected 0)"
    fail=1
  fi
  if [ -n "$out" ]; then
    echo "FAIL: $name produced output while disabled: $out"
    fail=1
  fi
}

for s in bq-log-prompt.sh bq-log-response.sh session-heartbeat.sh sync-transcripts-to-bq.sh; do
  out="$(printf '%s' '{}' | bash "$SV/$s" 2>&1)"
  check "$s" "$?" "$out"
done

for p in vault-flush-offsets.py sync-subagents-to-bq.py sync-codex-transcripts-to-bq.py backup-transcripts-to-gcs.py; do
  out="$(python3 "$SV/$p" 2>&1)"
  check "$p" "$?" "$out"
done

if [ "$fail" -eq 0 ]; then
  echo "PASS: disabled no-op (all scripts silent when enabled=false)"
else
  exit 1
fi
