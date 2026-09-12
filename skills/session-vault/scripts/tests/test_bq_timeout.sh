#!/usr/bin/env bash
# Behavior test for lib/bq-timeout.sh:
#   1. a fast command returns its own exit code (no timeout),
#   2. a wedged command is killed and returns 124 within ~the cap,
#   3. no orphaned child survives the kill.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$DIR/../lib/bq-timeout.sh"

fail=0

if ! run_with_timeout 5 true; then
  echo "FAIL: 'true' should exit 0"
  fail=1
fi

if run_with_timeout 5 false; then
  echo "FAIL: 'false' should exit non-zero"
  fail=1
fi

# Distinctive arg0 (via exec -a) so pgrep does not match unrelated sleeps.
MARKER="__bqtimeout_test_$$"
start=$(date +%s)
run_with_timeout 2 bash -c "exec -a $MARKER sleep 60"
rc=$?
end=$(date +%s)
if [ "$rc" -ne 124 ]; then
  echo "FAIL: wedged command should return 124, got $rc"
  fail=1
fi
elapsed=$((end - start))
if [ "$elapsed" -ge 15 ]; then
  echo "FAIL: kill took ${elapsed}s, expected ~2s"
  fail=1
fi

sleep 1
if pgrep -f "$MARKER" >/dev/null 2>&1; then
  echo "FAIL: orphaned child survived the kill"
  pkill -f "$MARKER" 2>/dev/null || true
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "PASS: bq-timeout"
else
  exit 1
fi
