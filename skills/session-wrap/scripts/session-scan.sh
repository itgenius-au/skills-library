#!/usr/bin/env bash
# session-scan.sh - deterministic deep-scan entrypoint for session-wrap done mode.
#
# Resolves worktree identity + the recency window from git and settings, then calls
# the stdlib Python core (session_scan.py) which does the discovery, stitch, noise
# filtering, and digest. Prints a bounded evidence digest and a DEEP_CANDIDATES line.
#
# Degrades cleanly at runtime (missing python3 / projects dir -> one NOTE + an empty
# digest, exit 0) so it can never break a wrap. `--self-test` is the exception: it is
# a hard gate and exits non-zero on any control failure or a missing dependency.
#
# Invoke from SKILL.md as:  bash "$SKILL_DIR/scripts/session-scan.sh"
# (`bash` explicitly, so a lost +x bit in the plugin cache does not break it.)

set -uo pipefail

# Self-locate, robust to symlinks and a lost +x bit.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
CORE="$DIR/session_scan.py"

# --- self-test: hard gate ---------------------------------------------------
if [ "${1:-}" = "--self-test" ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "SELF-TEST FAILED: python3 not found" >&2
    exit 1
  fi
  python3 "$CORE" --self-test
  exit $?
fi

# --- runtime: degrade, never break the wrap --------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "NOTE python3 unavailable; deep scan skipped"
  echo "DEEP_CANDIDATES=0"
  exit 0
fi

PROJECTS_DIR="${SESSION_SCAN_PROJECTS_DIR:-$HOME/.claude/projects}"
SESSIONS_DIR="${SESSION_SCAN_SESSIONS_DIR:-$HOME/.claude/sessions}"
if [ ! -d "$PROJECTS_DIR" ]; then
  echo "NOTE no projects dir at $PROJECTS_DIR; deep scan skipped"
  echo "DEEP_CANDIDATES=0"
  exit 0
fi

# Worktree identity. Empty branch = detached HEAD (the core handles it).
WT_PATH="$(git rev-parse --show-toplevel 2>/dev/null || true)"
WT_BRANCH="$(git branch --show-current 2>/dev/null || true)"
# Not in a git work tree: WT_PATH stays empty and the core runs in session-id mode
# (only the CLAUDE_CODE_SESSION_ID transcript), or prints a skip NOTE without an id.

# Main checkout of THIS repo (a worktree resolves to its primary checkout).
COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null || true)"
MAIN_PATH=""
if [ -n "$COMMON_DIR" ]; then
  MAIN_PATH="$(cd "$(dirname "$COMMON_DIR")" 2>/dev/null && pwd -P || true)"
fi

# Optional parent root. A session may start in a parent folder and enter a nested repo's
# worktree. Set SESSION_SCAN_PARENT_PATH to that parent folder to also read its transcript
# folder. Empty is always safe (the parent folder is simply not added).
PARENT_PATH="${SESSION_SCAN_PARENT_PATH:-}"

# Recency window from the live cleanupPeriodDays (fallback >= 365).
RECENCY=365
if command -v jq >/dev/null 2>&1 && [ -f "$HOME/.claude/settings.json" ]; then
  v="$(jq -r '.cleanupPeriodDays // empty' "$HOME/.claude/settings.json" 2>/dev/null || true)"
  case "$v" in
    ''|*[!0-9]*) : ;;                       # unset / non-numeric -> keep 365
    *) [ "$v" -gt "$RECENCY" ] && RECENCY="$v" ;;
  esac
fi

python3 "$CORE" \
  --wt-path "$WT_PATH" \
  --wt-branch "$WT_BRANCH" \
  --main-path "$MAIN_PATH" \
  --parent-path "$PARENT_PATH" \
  --projects-dir "$PROJECTS_DIR" \
  --sessions-dir "$SESSIONS_DIR" \
  --recency-days "$RECENCY" \
  || { echo "NOTE deep scan core errored; skipped"; echo "DEEP_CANDIDATES=0"; }
