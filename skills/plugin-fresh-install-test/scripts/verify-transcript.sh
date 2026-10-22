#!/usr/bin/env bash
# Verify the interactive session that fresh-launch.sh started, from its transcript and any
# stub logs. Checks CONTENT, not keywords the prompt itself contains.
#
# Usage: verify-transcript.sh <out-dir> [--phrase "<text only in the hook context>"]
#                                       [--guard "<guard decision prefix>"]
#                                       [--forbid "<regex>"]
#   --phrase  text that exists only in your SessionStart hook's context
#   --guard   the text your PreToolUse guard prints when it blocks or warns
#   --forbid  extended regex; any line in a stub log (stub-*.log) matching it is a failure
#             (for example 'run deploy' to prove a deploy never reached the stubbed command)
# Each of --phrase/--guard/--forbid is optional; a check you do not pass is skipped.
set -u
[ $# -ge 1 ] || { echo "usage: verify-transcript.sh <out-dir> [--phrase text] [--guard text] [--forbid regex]" >&2; exit 2; }
OUT="$1"; shift
PHRASE="" GUARD="" FORBID=""
while [ $# -gt 0 ]; do
  case "$1" in --phrase) PHRASE="$2"; shift 2 ;; --guard) GUARD="$2"; shift 2 ;; --forbid) FORBID="$2"; shift 2 ;; *) shift ;; esac
done
T=$(ls -t "$OUT"/config/projects/*/*.jsonl 2>/dev/null | head -1)
[ -n "$T" ] || { echo "no transcript under $OUT/config/projects"; exit 1; }
echo "transcript:            $T"
if [ -n "$PHRASE" ]; then
  echo "hook context in it:    $(grep -c -F "$PHRASE" "$T")  (0 = missing; normal for the FIRST session after an in-session sign-in)"
fi
if [ -n "$GUARD" ]; then
  echo "guard decisions:       $(grep -c -F "$GUARD" "$T")"
fi
if [ -n "$FORBID" ]; then
  n=$(cat "$OUT"/stub-*.log 2>/dev/null | grep -c -E "$FORBID")
  echo "forbidden stub lines:  $n  (must be 0)"
fi
echo "claude version seen:   $(grep -o -E '[0-9]+\.[0-9]+\.[0-9]+ \(Claude Code\)' "$T" | sort -u | head -1)"
echo "signed-in org:         $(jq -r 'select(.type=="attachment" and .attachment.type=="credential_org") | .attachment.organizationUuid' "$T" | head -1)"
