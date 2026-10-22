#!/usr/bin/env bash
# snapshots.sh - create or move one detached review snapshot per review-swarm leg.
#
# usage: snapshots.sh <repo-root> <slug> <sha> <scratch-dir> [leg ...]
#
#   <repo-root>    the repo checkout to add the snapshot worktrees to
#   <slug>         short name for this review (letters, digits, . _ -)
#   <sha>          the checkpoint commit every leg must read (any commit-ish)
#   <scratch-dir>  where the baseline files are written (created if missing)
#   [leg ...]      default: codex gemini fable
#
# For each leg it uses <repo-root>/.claude/worktrees/review-<slug>-<leg>:
#   - missing: `git worktree add --detach` at <sha>
#   - present: `git checkout -q --detach <sha>` (this is how the snapshots move
#     between review cycles; run the script again with the next checkpoint sha)
# and prints one line per leg: short sha and the count of dirty entries. A dirty
# snapshot means something wrote to it; look before you trust that leg's read.
#
# It also re-records the post-panel baseline in <scratch-dir>, every run:
#   refs-before.txt   `git ls-remote --heads origin`
#   panel-start.txt   `date -u +%Y-%m-%dT%H:%M:%SZ`
# Run it before each cycle's legs launch, so the post-panel check compares
# against THAT cycle's start, not the first cycle's.
#
# Portable on purpose: no `timeout` (macOS has none), no bash 4 features.
# Remove the snapshots after the last cycle:
#   git worktree remove --force <repo-root>/.claude/worktrees/review-<slug>-<leg>
set -euo pipefail

usage() {
  echo "usage: $(basename "$0") <repo-root> <slug> <sha> <scratch-dir> [leg ...]" >&2
  exit 2
}

[ "$#" -ge 4 ] || usage
REPO=$1
SLUG=$2
REV=$3
SCRATCH=$4
shift 4
if [ "$#" -gt 0 ]; then
  LEGS=("$@")
else
  LEGS=(codex gemini fable)
fi

name_ok() {
  case "$1" in
    "" | *[!A-Za-z0-9._-]*) return 1 ;;
  esac
}

# Absolute git-common-dir of a checkout, so two worktrees of one repo compare equal.
common_dir() {
  local d
  d=$(git -C "$1" rev-parse --git-common-dir)
  case "$d" in
    /*) ;;
    *) d="$1/$d" ;;
  esac
  (cd "$d" && pwd -P)
}

name_ok "$SLUG" || { echo "bad slug '$SLUG': use letters, digits, . _ -" >&2; exit 2; }
for leg in "${LEGS[@]}"; do
  name_ok "$leg" || { echo "bad leg name '$leg': use letters, digits, . _ -" >&2; exit 2; }
done

git -C "$REPO" rev-parse --git-dir > /dev/null 2>&1 || { echo "not a git repo: $REPO" >&2; exit 2; }
SHA=$(git -C "$REPO" rev-parse --verify --quiet "${REV}^{commit}") || {
  echo "not a commit in $REPO: $REV" >&2
  exit 2
}
REPO_COMMON=$(common_dir "$REPO")

# Fail before touching any snapshot when the baseline cannot be taken: a panel
# without a baseline cannot run the post-panel check.
mkdir -p "$SCRATCH"
REFS_TMP=$(mktemp "$SCRATCH/refs-before.XXXXXX")
trap 'rm -f "$REFS_TMP"' EXIT
if ! git -C "$REPO" ls-remote --heads origin > "$REFS_TMP"; then
  echo "cannot read remote refs (git ls-remote --heads origin failed in $REPO)" >&2
  exit 1
fi

for leg in "${LEGS[@]}"; do
  SNAP="$REPO/.claude/worktrees/review-$SLUG-$leg"
  if [ -e "$SNAP" ]; then
    # A plain directory under the repo also passes `--is-inside-work-tree` (it is
    # inside the MAIN checkout), so require that the snapshot is its own worktree
    # root; otherwise the checkout below would move the main checkout's HEAD.
    if ! SNAP_TOP=$(git -C "$SNAP" rev-parse --show-toplevel 2> /dev/null) \
      || [ "$(cd "$SNAP_TOP" && pwd -P)" != "$(cd "$SNAP" && pwd -P)" ] \
      || [ "$(common_dir "$SNAP")" != "$REPO_COMMON" ]; then
      echo "$SNAP exists but is not a worktree of $REPO; move it aside" >&2
      exit 1
    fi
    git -C "$SNAP" checkout -q --detach "$SHA"
  else
    git -C "$REPO" worktree add -q --detach "$SNAP" "$SHA"
  fi
  DIRTY=$(git -C "$SNAP" status --short | wc -l | tr -d ' ')
  echo "$leg: $(git -C "$SNAP" rev-parse --short HEAD) dirty=$DIRTY"
  if [ "$DIRTY" != "0" ]; then
    echo "WARNING: $SNAP is dirty; something wrote to it. Inspect it before this leg reads it." >&2
  fi
done

mv "$REFS_TMP" "$SCRATCH/refs-before.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$SCRATCH/panel-start.txt"
echo "refs-before.txt: $(wc -l < "$SCRATCH/refs-before.txt" | tr -d ' ') refs"
echo "panel-start.txt: $(cat "$SCRATCH/panel-start.txt")"
