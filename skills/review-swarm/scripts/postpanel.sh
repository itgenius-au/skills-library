#!/usr/bin/env bash
# postpanel.sh - the mandatory post-panel check, as ONE read-only command.
#
# usage: postpanel.sh <repo-root> <slug> <scratch-dir> [leg ...]
#
#   <repo-root>    the same repo root you gave snapshots.sh (the build checkout by default;
#                  set BUILD_WORKTREE=<path> when the build worktree is a different path)
#   <slug>         the same review slug you gave snapshots.sh
#   <scratch-dir>  the same scratch dir (it holds refs-before.txt and panel-start.txt)
#   [leg ...]      default: codex gemini fable
#
# Why a script: in a worktree-bound session the guard refuses the combined check block and
# every `git -C <snapshot>` line, so the check took one tool call per line. A script file run
# with `bash <path> ...` is one plain command.
#
# It prints the build worktree's branch, reflog and status; each snapshot's HEAD, dirty count
# and reflog; the remote-branch changes since the panel started; and your recent PRs (this repo
# and any repo since the panel start). Output lines starting with `REVIEW:` need a look before
# you trust the panel. It never changes anything.
#
# Exit: 0 clean, 1 at least one REVIEW line, 2 usage error or missing baseline.
# Portable on purpose: no `timeout` (macOS has none), no bash 4 features.
set -uo pipefail

usage() {
  echo "usage: postpanel.sh <repo-root> <slug> <scratch-dir> [leg ...]" >&2
  exit 2
}

[ "$#" -ge 3 ] || usage
ROOT=$1
SLUG=$2
SCRATCH=$3
shift 3
if [ "$#" -gt 0 ]; then LEGS=("$@"); else LEGS=(codex gemini fable); fi
BUILD=${BUILD_WORKTREE:-$ROOT}

git -C "$BUILD" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || { echo "postpanel: $BUILD is not a git work tree" >&2; exit 2; }
[ -f "$SCRATCH/refs-before.txt" ] \
  || { echo "postpanel: missing $SCRATCH/refs-before.txt (run snapshots.sh before the legs)" >&2; exit 2; }
PANEL_START=$(cat "$SCRATCH/panel-start.txt" 2>/dev/null || echo "")

FLAGS=0
flag() {
  echo "REVIEW: $1"
  FLAGS=1
}

echo "== build worktree: $BUILD"
echo "branch: $(git -C "$BUILD" branch --show-current)"
[ -n "$(git -C "$BUILD" branch --show-current)" ] || flag "build worktree HEAD is detached"
echo "-- reflog (last 5)"
git -C "$BUILD" reflog -5 | cat
echo "-- status (only your own changes should show)"
git -C "$BUILD" status --short | cat

for leg in "${LEGS[@]}"; do
  SNAP="$ROOT/.claude/worktrees/review-$SLUG-$leg"
  echo "== snapshot $leg: $SNAP"
  if [ ! -d "$SNAP" ]; then
    echo "(missing)"
    continue
  fi
  echo "HEAD $(git -C "$SNAP" rev-parse --short HEAD)"
  DIRTY=$(git -C "$SNAP" status --porcelain | wc -l | tr -d ' ')
  [ "$DIRTY" = "0" ] || flag "snapshot $leg has $DIRTY dirty entries"
  REFLOG=$(git -C "$SNAP" reflog --format='%gs' 2>/dev/null || true)
  printf '%s\n' "$REFLOG" | sed '/^$/d' | head -5
  # snapshots.sh creates (empty subject) and moves (checkout: ...) snapshots; anything else wrote.
  if printf '%s\n' "$REFLOG" | grep -Eq '^(commit|reset|merge|rebase|cherry-pick|pull|am)'; then
    flag "snapshot $leg reflog shows a write (commit, reset, merge or rebase)"
  fi
done

echo "== remote branches changed since the panel started"
CHANGES=$(git -C "$BUILD" ls-remote --heads origin 2>/dev/null | diff "$SCRATCH/refs-before.txt" - | grep '^[<>]' || true)
if [ -n "$CHANGES" ]; then
  printf '%s\n' "$CHANGES"
  flag "remote branches changed since the panel started (attribute each one; another session can move a branch too)"
else
  echo "(none)"
fi

echo "== your recent PRs, this repo (each must be one you opened)"
(cd "$BUILD" && gh pr list --author @me --state all --limit 5) 2>&1 | cat
echo "== your PRs in any repo since the panel started ($PANEL_START)"
if [ -n "$PANEL_START" ]; then
  gh search prs --author @me --created ">=$PANEL_START" 2>&1 | cat
else
  echo "(no panel-start.txt; skipped)"
fi

if [ "$FLAGS" = "0" ]; then
  echo "POST-PANEL: CLEAN"
else
  echo "POST-PANEL: REVIEW the lines above before you trust the panel"
fi
exit "$FLAGS"
