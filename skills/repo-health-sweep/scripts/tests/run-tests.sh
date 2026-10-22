#!/usr/bin/env bash

set +e

TEST_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
SCRIPT_DIR=$(CDPATH='' cd -- "$TEST_DIR/.." && pwd)
rc=0

echo "===== shellcheck ====="
if command -v shellcheck >/dev/null 2>&1; then
  if shellcheck "$SCRIPT_DIR/discover-targets.sh" "$SCRIPT_DIR/run-gates.sh" "$TEST_DIR/discover-targets.test.sh"; then
    echo "shellcheck clean"
  else
    rc=1
  fi
else
  echo "shellcheck not installed, skipping"
fi

echo "===== behavior tests ====="
bash "$TEST_DIR/discover-targets.test.sh" || rc=1

exit "$rc"
