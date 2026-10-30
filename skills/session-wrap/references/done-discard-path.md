# Step 7: done, discard path

Use this when the worktree has nothing to merge (`dirty=0 ahead=0 behind=0`).

```bash
BASE_BRANCH=${DEFAULT_BRANCH#origin/}
cd "$MAIN_PATH"

# Guard 1: primary checkout sanity. We do not mutate it on discard, but a non-clean
# primary suggests another session is mid-work in the same repo - pause to confirm
# before destroying anything.
PRIMARY_BRANCH=$(git rev-parse --abbrev-ref HEAD)
PRIMARY_DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$PRIMARY_BRANCH" != "$BASE_BRANCH" ] || [ "$PRIMARY_DIRTY" != "0" ]; then
  echo "WARNING: primary checkout is on '$PRIMARY_BRANCH' with $PRIMARY_DIRTY uncommitted file(s). Confirm explicitly before discarding the worktree."
  return 1 2>/dev/null || exit 1
fi

# Guard 2: worktree itself clean? --force will SILENTLY delete uncommitted work.
WT_DIRTY=$(git -C "$WORKTREE_PATH" status --porcelain | wc -l | tr -d ' ')
if [ "$WT_DIRTY" != "0" ]; then
  echo "BLOCKED: worktree at $WORKTREE_PATH has $WT_DIRTY uncommitted file(s)."
  echo "Discard with --force would silently delete this work. Commit/stash first, or get explicit OK to throw it away."
  return 1 2>/dev/null || exit 1
fi

# Guards passed: no uncommitted work at risk, so a plain (non --force) remove is safe.
git worktree remove "$WORKTREE_PATH"
git branch -D "$WT_BRANCH"
git push origin --delete "$WT_BRANCH" || echo "warning: remote $WT_BRANCH delete failed - local cleanup already done."
```

If your team tracks work in a task tracker, note there that the worktree was closed with nothing left to merge. If the remote branch delete failed, report the delete result in the wrap details.
