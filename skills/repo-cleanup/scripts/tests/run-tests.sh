#!/usr/bin/env bash
# repo-cleanup local gate: shellcheck (when present) + the stale-work script tests.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SCRIPTS="$(dirname "$DIR")"
rc=0

echo "== shellcheck =="
if command -v shellcheck >/dev/null 2>&1; then
  if shellcheck "$SCRIPTS/stale-inventory.sh" "$SCRIPTS/stale-archive.sh" "$SCRIPTS/stale-archive-verify.sh" \
       "$SCRIPTS/added-lines-check.sh" "$DIR/test_stale_inventory.sh" "$DIR/test_stale_archive.sh" \
       "$DIR/test_added_lines_check.sh" "$DIR/run-tests.sh"; then echo "shellcheck OK"; else rc=1; fi
else
  echo "shellcheck not installed; skipped"
fi

echo "== stale-inventory =="
if bash "$DIR/test_stale_inventory.sh"; then :; else rc=1; fi

echo "== stale-archive =="
if bash "$DIR/test_stale_archive.sh"; then :; else rc=1; fi

echo "== added-lines-check =="
if bash "$DIR/test_added_lines_check.sh"; then :; else rc=1; fi

echo "== tag_trigger_check =="
# The script needs PyYAML; a machine without it skips (CI installs it) rather than fails here.
if python3 -c 'import yaml' 2>/dev/null; then
  if python3 -I "$DIR/test_tag_trigger_check.py"; then :; else rc=1; fi
else
  echo "PyYAML not installed; skipped (pip install pyyaml)"
fi

if [ "$rc" -ne 0 ]; then echo "TESTS FAILED" >&2; exit 1; fi
echo "ALL TESTS PASSED"
