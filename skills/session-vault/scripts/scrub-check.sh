#!/usr/bin/env bash
# scrub-check.sh - fail if any personal identifier from the source (Peter's live vault) survives
# anywhere in the shippable session-vault tree. Run as a gate before the PR.
set -uo pipefail

# Skill root = two levels up from scripts/ (session-vault/), then scan it + sibling staged dirs.
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPTS_DIR/.." && pwd)"

# Forbidden literals (personal to the source install; none may ship).
PATTERNS='agent-peter|petermoriarty|peter@|moriarty\.co|claude_transcripts|19m-iZi5|/Users/petermoriarty|/home/peter'

# Exclude this script (it necessarily contains the patterns) and editor backups.
hits="$(grep -rInE "$PATTERNS" "$SKILL_DIR" \
          --exclude='scrub-check.sh' \
          --exclude='*.bak' \
          --exclude-dir='__pycache__' 2>/dev/null || true)"

if [ -n "$hits" ]; then
  echo "SCRUB FAIL - personal identifiers found in the shippable tree:"
  echo "$hits"
  exit 1
fi
echo "PASS: scrub (no personal identifiers in $SKILL_DIR)"
