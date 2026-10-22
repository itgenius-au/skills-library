#!/usr/bin/env bash
# run-tests.sh - gate for the session-wrap deep-scan scripts.
#
# Runs the Python core's --self-test (positive control + per-vector negative
# controls + resumed-union + middle-only + bridge-stub + detached-HEAD + inferred).
# Exits non-zero on any failure. This is the hard gate the build must pass.

set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SCRIPTS="$(dirname "$DIR")"

fail=0

echo "== py_compile =="
if command -v python3 >/dev/null 2>&1; then
  python3 -m py_compile "$SCRIPTS/session_scan.py" && echo "compile OK" || fail=1
else
  echo "python3 missing" >&2; exit 1
fi

echo "== self-test (controls) =="
bash "$SCRIPTS/session-scan.sh" --self-test || fail=1

echo "== runtime degrade: empty projects dir =="
tmp="$(mktemp -d)"
out="$(SESSION_SCAN_PROJECTS_DIR="$tmp/none" bash "$SCRIPTS/session-scan.sh" 2>/dev/null || true)"
echo "$out" | grep -q "DEEP_CANDIDATES=0" && echo "degrade OK" || { echo "degrade FAILED" >&2; fail=1; }
rm -rf "$tmp"

echo "== runtime: CLAUDE_CODE_SESSION_ID finds the transcript under another folder =="
tmp="$(mktemp -d)"
mkdir -p "$tmp/projects/-launch-slug" "$tmp/sessions" "$tmp/repo"
git -C "$tmp/repo" init -q 2>/dev/null
WT="$(cd "$tmp/repo" && pwd -P)"
printf '{"type":"user","uuid":"u1","cwd":"%s","message":{"role":"user","content":"Update the skill so it reads the id first."}}\n' "$WT" \
  > "$tmp/projects/-launch-slug/SESS1.jsonl"
out="$(cd "$tmp/repo" && SESSION_SCAN_PROJECTS_DIR="$tmp/projects" SESSION_SCAN_SESSIONS_DIR="$tmp/sessions" \
  CLAUDE_CODE_SESSION_ID=SESS1 bash "$SCRIPTS/session-scan.sh" 2>/dev/null || true)"
echo "$out" | grep -q "^SPAN $tmp/projects/-launch-slug/SESS1.jsonl" && echo "env resolve OK" || { echo "env resolve FAILED: $out" >&2; fail=1; }
out="$(cd "$tmp/repo" && SESSION_SCAN_PROJECTS_DIR="$tmp/projects" SESSION_SCAN_SESSIONS_DIR="$tmp/sessions" \
  CLAUDE_CODE_SESSION_ID=NOPE bash "$SCRIPTS/session-scan.sh" 2>/dev/null || true)"
if echo "$out" | grep -q "matched no transcript" && ! echo "$out" | grep -q "^SPAN "; then echo "env missing OK"; else echo "env missing FAILED: $out" >&2; fail=1; fi

echo "== runtime: outside a git tree, CLAUDE_CODE_SESSION_ID still runs the core =="
mkdir -p "$tmp/nogit"
out="$(cd "$tmp/nogit" && GIT_CEILING_DIRECTORIES="$tmp" SESSION_SCAN_PROJECTS_DIR="$tmp/projects" \
  SESSION_SCAN_SESSIONS_DIR="$tmp/sessions" CLAUDE_CODE_SESSION_ID=SESS1 bash "$SCRIPTS/session-scan.sh" 2>/dev/null || true)"
if echo "$out" | grep -q "^SPAN $tmp/projects/-launch-slug/SESS1.jsonl" && echo "$out" | grep -q "| directive |"; then
  echo "no-git session-id OK"; else echo "no-git session-id FAILED: $out" >&2; fail=1; fi
out="$(cd "$tmp/nogit" && GIT_CEILING_DIRECTORIES="$tmp" SESSION_SCAN_PROJECTS_DIR="$tmp/projects" \
  SESSION_SCAN_SESSIONS_DIR="$tmp/sessions" CLAUDE_CODE_SESSION_ID='' bash "$SCRIPTS/session-scan.sh" 2>/dev/null || true)"
if echo "$out" | grep -q "not in a git work tree; deep scan skipped" && echo "$out" | grep -q "^DEEP_CANDIDATES=0"; then
  echo "no-git no-id OK"; else echo "no-git no-id FAILED: $out" >&2; fail=1; fi
rm -rf "$tmp"

if [ "$fail" -ne 0 ]; then
  echo "TESTS FAILED" >&2
  exit 1
fi
echo "ALL TESTS PASSED"
