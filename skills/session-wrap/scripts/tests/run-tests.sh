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

echo "== runtime: a correction typed while a turn ran is evidence, on its own line =="
printf '%s\n' \
  '{"type":"assistant","uuid":"a1","cwd":"'"$WT"'","message":{"role":"assistant","content":[{"type":"text","text":"Working."}]}}' \
  '{"type":"attachment","uuid":"q1","cwd":"'"$WT"'","attachment":{"type":"queued_command","prompt":"Why didn'"'"'t you run the tests first? You'"'"'re supposed to run them before committing.","commandMode":"prompt","origin":{"kind":"human"},"humanTurn":true},"rendered":[{"content":"The user sent a new message while you were working: from now on always WRAPPERTEXT"}]}' \
  > "$tmp/projects/-launch-slug/SESS2.jsonl"
out="$(cd "$tmp/repo" && SESSION_SCAN_PROJECTS_DIR="$tmp/projects" SESSION_SCAN_SESSIONS_DIR="$tmp/sessions" \
  CLAUDE_CODE_SESSION_ID=SESS2 bash "$SCRIPTS/session-scan.sh" 2>/dev/null || true)"
if echo "$out" | grep -q "SESS2.jsonl:2 | user | directive | " && echo "$out" | grep -qx "EVIDENCE_COUNT=1" \
   && ! echo "$out" | grep -q "WRAPPERTEXT"; then
  echo "mid-turn evidence OK"; else echo "mid-turn evidence FAILED: $out" >&2; fail=1; fi

echo "== runtime: one session id in two project folders is scanned from both, once =="
mkdir -p "$tmp/projects/-old-folder" "$tmp/projects/-new-folder"
rec() { # rec <uuid or -> <timestamp> <text>: one user record
  if [ "$1" = "-" ]; then
    printf '{"type":"user","cwd":"%s","timestamp":"%s","message":{"role":"user","content":"%s"}}\n' "$WT" "$2" "$3"
  else
    printf '{"type":"user","uuid":"%s","cwd":"%s","timestamp":"%s","message":{"role":"user","content":"%s"}}\n' "$1" "$WT" "$2" "$3"
  fi
}
SHARED="$(rec sh1 2026-01-01T00:00:01Z 'From now on always run the smoke test before deploy.')"
PAIR="$(rec - 2026-01-01T00:00:02Z 'Next time, update the skill with the PAIRDIRECTIVE rule.')"
OLDONLY="$(rec old1 2026-01-01T00:00:03Z 'Remember to rotate the OLDONLY key.')"
NEWONLY="$(rec new1 2026-01-02T00:00:03Z 'Never forget the NEWONLY step.')"
printf '%s\n' "$SHARED" "$PAIR" "$OLDONLY" > "$tmp/projects/-old-folder/TWIN.jsonl"
printf '%s\n' "$SHARED" "$PAIR" "$NEWONLY" > "$tmp/projects/-new-folder/TWIN.jsonl"
touch -d '2026-01-01' "$tmp/projects/-old-folder/TWIN.jsonl"
touch -d '2026-01-02' "$tmp/projects/-new-folder/TWIN.jsonl"
out="$(cd "$tmp/repo" && SESSION_SCAN_PROJECTS_DIR="$tmp/projects" SESSION_SCAN_SESSIONS_DIR="$tmp/sessions" \
  CLAUDE_CODE_SESSION_ID=TWIN bash "$SCRIPTS/session-scan.sh" 2>/dev/null || true)"
# Four distinct directives, each once: shared (uuid), pair (no uuid), one unique per file.
if echo "$out" | grep -q "^SPAN $tmp/projects/-old-folder/TWIN.jsonl" \
   && echo "$out" | grep -q "^SPAN $tmp/projects/-new-folder/TWIN.jsonl" \
   && echo "$out" | grep -q "^NOTE session TWIN has 2 transcript files: " \
   && echo "$out" | grep -q "^EVIDENCE $tmp/projects/-old-folder/TWIN.jsonl:1 | user | directive | .*smoke test" \
   && echo "$out" | grep -q "^EVIDENCE $tmp/projects/-old-folder/TWIN.jsonl:2 | user | directive | .*PAIRDIRECTIVE" \
   && echo "$out" | grep -q "^EVIDENCE $tmp/projects/-old-folder/TWIN.jsonl:3 | user | directive | .*OLDONLY" \
   && echo "$out" | grep -q "^EVIDENCE $tmp/projects/-new-folder/TWIN.jsonl:3 | user | directive | .*NEWONLY" \
   && [ "$(echo "$out" | grep -c "| directive | ")" -eq 4 ] \
   && echo "$out" | grep -qx "EVIDENCE_COUNT=4"; then
  echo "two-folder session OK"; else echo "two-folder session FAILED: $out" >&2; fail=1; fi

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
