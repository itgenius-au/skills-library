#!/usr/bin/env bash
# Dry-run tests for the three hooks: correct config-derived target, correct row
# shape, offset NOT advanced in dry-run, and the enable/disable gating.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SV="$(cd "$DIR/.." && pwd)"
fail=0

SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT

printf '{ "gcp": {"personal_project":"agent-alex"}, "logging": {"enabled":true, "heartbeat_enabled":true, "offset_state_dir":"%s/offsets"} }\n' "$SCRATCH" > "$SCRATCH/cfg.json"
export ITG_CONFIG="$SCRATCH/cfg.json"
export VAULT_DRY_RUN=1

echo "--- prompt hook ---"
out=$(printf '%s' '{"session_id":"aaaa1111","prompt":"hello vault","cwd":"/tmp/proj"}' | bash "$SV/bq-log-prompt.sh")
echo "$out" | grep -q 'agent-alex:claude_memory_vault.messages' || { echo "FAIL: prompt target"; fail=1; }
echo "$out" | grep -q '"content":"hello vault"' || { echo "FAIL: prompt content"; fail=1; }
echo "$out" | grep -q '"role":"user"' || { echo "FAIL: prompt role"; fail=1; }
# The prompt hook seeds a 0 offset so vault-flush can sweep the session even if Stop never runs.
{ [ -f "$SCRATCH/offsets/aaaa1111" ] && [ "$(cat "$SCRATCH/offsets/aaaa1111" 2>/dev/null)" = "0" ]; } \
  || { echo "FAIL: prompt hook did not seed offset=0"; fail=1; }
# A path-traversal session_id must be rejected (no file created outside the offsets dir).
printf '%s' '{"session_id":"../evil","prompt":"x","cwd":"/tmp"}' | bash "$SV/bq-log-prompt.sh" >/dev/null 2>&1
if [ -e "$SCRATCH/evil" ]; then echo "FAIL: session_id path traversal not blocked"; fail=1; fi

echo "--- response hook ---"
TR="$SCRATCH/t.jsonl"
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"hi there"}],"model":"claude-x"},"uuid":"u1","timestamp":"2026-09-10T00:00:00.000000Z"}' > "$TR"
rout=$(printf '{"session_id":"bbbb2222","transcript_path":"%s","cwd":"/tmp/proj"}' "$TR" | bash "$SV/bq-log-response.sh")
echo "$rout" | grep -q 'agent-alex:claude_memory_vault.messages' || { echo "FAIL: response target"; fail=1; }
echo "$rout" | grep -q '"content":"hi there"' || { echo "FAIL: response content"; fail=1; }
echo "$rout" | grep -q '"model":"claude-x"' || { echo "FAIL: response model"; fail=1; }
# The response hook does not seed offsets; dry-run must not create/advance one for this session.
if [ -f "$SCRATCH/offsets/bbbb2222" ]; then echo "FAIL: dry-run advanced the offset"; fail=1; fi

echo "--- heartbeat: disabled -> no-op ---"
printf '{ "gcp": {"personal_project":"agent-alex"}, "logging": {"enabled":true, "heartbeat_enabled":false} }\n' > "$SCRATCH/off.json"
hout=$(ITG_CONFIG="$SCRATCH/off.json" bash "$SV/session-heartbeat.sh")
if [ -n "$hout" ]; then echo "FAIL: heartbeat should be silent when disabled"; fail=1; fi

echo "--- heartbeat: enabled -> emits a row ---"
PROJ="$SCRATCH/projects/proj1"
mkdir -p "$PROJ"
UUID="11111111-1111-1111-1111-111111111111"
printf '%s\n' '{"type":"assistant","cwd":"/tmp/proj","gitBranch":"main"}' > "$PROJ/$UUID.jsonl"
hout2=$(VAULT_PROJECTS_DIR="$SCRATCH/projects" bash "$SV/session-heartbeat.sh")
echo "$hout2" | grep -q 'agent-alex:claude_memory_vault.session_heartbeat' || { echo "FAIL: heartbeat target"; fail=1; }
echo "$hout2" | grep -q "\"session_id\":\"$UUID\"" || { echo "FAIL: heartbeat session_id"; fail=1; }

if [ "$fail" -eq 0 ]; then
  echo "PASS: hooks"
else
  exit 1
fi
