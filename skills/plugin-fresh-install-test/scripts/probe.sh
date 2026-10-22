#!/usr/bin/env bash
# Headless probe of a (fresh) config dir: which copy of a plugin loads, and did its
# SessionStart hook deliver context? Graded by EVENTS, never by the model's self-report.
#
# Usage: probe.sh <out-dir-or-config-dir> <repo-dir> --plugin <name> [--phrase "<text>"]
#   --plugin   the plugin name to look for in the session init list (required)
#   --phrase   a sentence that exists ONLY in the hook's context (not in any prompt).
#              Optional: without it the hook check is skipped and only the plugin
#              source, cache-miss errors and install records are reported.
set -u
usage() { echo "usage: probe.sh <out-or-config-dir> <repo-dir> --plugin <name> [--phrase text]" >&2; exit 2; }
[ $# -ge 2 ] || usage
C="$1"; [ -d "$C/config" ] && C="$C/config"
REPO="$2"; shift 2
PLUGIN="" PHRASE=""
while [ $# -gt 0 ]; do
  case "$1" in --plugin) PLUGIN="$2"; shift 2 ;; --phrase) PHRASE="$2"; shift 2 ;; *) shift ;; esac
done
[ -n "$PLUGIN" ] || usage
W=$(mktemp -d "${TMPDIR:-/tmp}/probe.XXXXXX")
# The prompt deliberately does NOT contain the phrase, so a grep for it cannot self-match.
P='Reply with the single word OK. Do not use any tools.'
( cd "$REPO" && CLAUDE_CONFIG_DIR="$C" claude -p --no-session-persistence --output-format stream-json \
    --verbose --debug hooks --debug-file "$W/debug.log" <<< "$P" ) > "$W/stream.jsonl" 2>&1
src=$(jq -r --arg p "$PLUGIN" 'select(.type=="system" and .subtype=="init") | .plugins[]? | select(.name==$p) | .source' "$W/stream.jsonl" 2>/dev/null | tr '\n' ',')
errs=$(grep -c -i 'not cached\|plugin-cache-miss' "$W/debug.log" 2>/dev/null)
rec=$(jq -c --arg p "$PLUGIN" '[.plugins | to_entries[] | select(.key|startswith($p+"@")) | .key] // []' "$C/plugins/installed_plugins.json" 2>/dev/null)
echo "plugin in init:      [${src:-none}]"
if [ -n "$PHRASE" ]; then
  hook=$(jq -r 'select(.type=="system" and .subtype=="hook_response") | tostring' "$W/stream.jsonl" 2>/dev/null | grep -c -F "$PHRASE")
  echo "hook context phrase: $hook  (>=1 = delivered)"
else
  echo "hook context phrase: skipped (no --phrase given)"
fi
echo "cache-miss errors:   ${errs:-0}"
echo "install records:     ${rec:-none}"
echo "raw files:           $W"
