#!/usr/bin/env bash
# auto-commit.sh - Wip-commit all dirty repos after each Claude response.
#
# Wire this as a Stop hook in ~/.claude/settings.json (see the session-dsp SKILL.md).
# Commits in $CLAUDE_PROJECT_DIR first (falling back to the current directory), then
# iterates immediate subdirectories that have their own .git (nested repos). Works
# whether Claude is launched from a parent folder of several repos or inside a single repo.
#
# All commits are local-only ("wip"), never pushed. The `session-dsp` skill squashes
# them into one clean commit before pushing.
#
# Protected-branch guard: never auto-wip onto main/master/trunk (or a detached
# HEAD). Work is meant to live on a worktree/feature branch; if an edit is
# accidentally addressed to a main checkout instead of the session's worktree,
# it should stay as VISIBLE uncommitted changes (easy to move onto the right
# branch), not become silent "wip" commits on main that have to be unwound.

set -o pipefail

wip_commit() {
  local dir="$1"
  cd "$dir" 2>/dev/null || return 0
  local branch
  branch=$(git symbolic-ref --short -q HEAD 2>/dev/null)
  case "$branch" in
    ''|main|master|trunk) return 0 ;;
  esac
  git add -A 2>/dev/null || return 0
  git diff-index --quiet HEAD 2>/dev/null && return 0
  git commit -m "wip" 2>/dev/null || true
}

# 1. Commit in the current project directory
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
wip_commit "$PROJECT_DIR"

# 2. Commit in any nested repos (immediate subdirs with their own .git)
for child in "$PROJECT_DIR"/*/; do
  [ -d "$child/.git" ] && wip_commit "$child"
done

exit 0
