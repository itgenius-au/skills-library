#!/usr/bin/env bash
# Install this plugin the way a customer does, in a throwaway Claude config folder, and
# prove it loads. Needs no Claude login.
#
# Usage: install_test.sh <repo-root>
# Exit codes: 0 installed, enabled, and validated. 1 any of that failed. 2 usage error.
set -uo pipefail

if [ "$#" -ne 1 ] || [ ! -f "${1}/.claude-plugin/marketplace.json" ]; then
  echo "usage: install_test.sh <repo-root>" >&2; exit 2
fi
SRC="$(cd "${1}" && pwd)"
CFG="$(mktemp -d)"
trap 'rm -rf "$CFG"' EXIT
export CLAUDE_CONFIG_DIR="$CFG"

claude plugin marketplace add "$SRC" || { echo "FAIL: marketplace add"; exit 1; }
claude plugin install skills-library@skills-library || { echo "FAIL: plugin install"; exit 1; }

list=$(claude plugin list 2>&1); lrc=$?
echo "$list"
[ "$lrc" -eq 0 ] || { echo "FAIL: claude plugin list exited $lrc"; exit 1; }
if printf '%s\n' "$list" | grep -qiE '(^|[[:space:]])(✘|error)'; then
  echo "FAIL: plugin list reports an error"; exit 1
fi
printf '%s\n' "$list" | grep -q 'Status: .*enabled' || { echo "FAIL: plugin is not enabled"; exit 1; }

claude plugin validate --strict "$SRC" || { echo "FAIL: claude plugin validate --strict"; exit 1; }
echo "PASS: skills-library installs and loads"
