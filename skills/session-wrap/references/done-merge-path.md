# Step 7: done, merge path (direct merge into the default branch)

```bash
BASE_BRANCH=${DEFAULT_BRANCH#origin/}   # "main", "master", whatever origin/HEAD points at
cd "$MAIN_PATH"

# Guard 0 (HARD clean-tree + real branch): never integrate a dirty tree or a
# detached HEAD. Step 6 should have committed everything, so either state means
# work would be dropped or misattributed by the merge. Stop and resolve first.
# Fail CLOSED: verify the path is a real work tree first. A failed `git status`
# would pipe empty to `wc` (count 0) and falsely read as clean.
git -C "$WORKTREE_PATH" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "BLOCKED: '$WORKTREE_PATH' is not a valid git work tree; cannot verify clean state."; return 1 2>/dev/null || exit 1; }
WT_DIRTY=$(git -C "$WORKTREE_PATH" status --porcelain | wc -l | tr -d ' ')
if [ "$WT_DIRTY" != "0" ]; then
  echo "BLOCKED: worktree has $WT_DIRTY uncommitted file(s). Commit or discard before integrating - never merge a dirty tree."
  return 1 2>/dev/null || exit 1
fi
if ! git -C "$WORKTREE_PATH" symbolic-ref -q HEAD >/dev/null; then
  echo "BLOCKED: worktree HEAD is DETACHED (not on a branch). 'git switch -c <branch>' before integrating - a detached HEAD has no branch to merge, and cleanup would strand the commits."
  return 1 2>/dev/null || exit 1
fi

# Guard 1: primary checkout safe to mutate?
# Switching its branch or polluting it with the merge would silently break another
# session working in the same checkout. If it is mid-work, refuse - let the user resolve.
PRIMARY_BRANCH=$(git rev-parse --abbrev-ref HEAD)
PRIMARY_DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$PRIMARY_BRANCH" != "$BASE_BRANCH" ] || [ "$PRIMARY_DIRTY" != "0" ]; then
  echo "BLOCKED: primary checkout is on '$PRIMARY_BRANCH' with $PRIMARY_DIRTY uncommitted file(s)."
  echo "Switch primary to '$BASE_BRANCH' (clean) before closeout, or close out manually."
  return 1 2>/dev/null || exit 1
fi

# Guard 2: worktree branch in sync with origin?
# Another session (or an auto-commit hook) may have pushed extra commits to the
# branch. If we merge only the local tip and then delete the remote, we lose those
# remote-only commits.
git fetch --quiet origin "$BASE_BRANCH" "$WT_BRANCH" || { echo "BLOCKED: fetch failed."; return 1 2>/dev/null || exit 1; }
LOCAL_TIP=$(git rev-parse "$WT_BRANCH")
REMOTE_TIP=$(git rev-parse "origin/$WT_BRANCH" 2>/dev/null || echo "")
if [ -n "$REMOTE_TIP" ] && [ "$LOCAL_TIP" != "$REMOTE_TIP" ]; then
  echo "BLOCKED: $WT_BRANCH local ($LOCAL_TIP) diverged from origin/$WT_BRANCH ($REMOTE_TIP)."
  echo "Resolve manually before closeout - otherwise remote-only commits are lost when the branch is deleted."
  return 1 2>/dev/null || exit 1
fi

# Gate 3 (test before integrating) - EXECUTABLE, not a note. A branch never merges to
# the default branch RED. Set TEST_GATE to the repo's OWN test command (the same gate
# its build process runs, e.g. `npm test && npm run build`, or `pytest`), discovered from
# the repo and its CLAUDE.md - or to the literal DOCS_ONLY to waive it for a genuinely
# test-less repo. Unset = you have not decided = BLOCK (never silently skip the gate).
if [ -z "${TEST_GATE:-}" ]; then
  echo "BLOCKED: TEST_GATE not set. Set it to the repo's test command, or DOCS_ONLY to waive (docs-only repo)."; return 1 2>/dev/null || exit 1
fi
if [ "$TEST_GATE" != "DOCS_ONLY" ]; then
  bash -c "$TEST_GATE" || { echo "BLOCKED: $WT_BRANCH is RED - not integrating a failing branch."; return 1 2>/dev/null || exit 1; }
fi

# Atomic integration - any failure aborts before destructive ops.
git pull --ff-only || { echo "BLOCKED: pull --ff-only failed; '$BASE_BRANCH' moved unexpectedly."; return 1 2>/dev/null || exit 1; }
if git merge --ff-only "$WT_BRANCH"; then :; \
elif git merge --no-ff "$WT_BRANCH" -m "merge: $WT_BRANCH"; then :; \
else echo "BLOCKED: merge of $WT_BRANCH into $BASE_BRANCH failed."; return 1 2>/dev/null || exit 1; fi

# Gate 4 (merged-result test) - EXECUTABLE. The merge can break the default branch
# even when both sides were green (a semantic conflict git can't see). Re-run the
# same gate on the merged result; RED -> undo the merge and STOP (never push red).
if [ -n "${TEST_GATE:-}" ] && [ "$TEST_GATE" != "DOCS_ONLY" ]; then
  bash -c "$TEST_GATE" || { echo "BLOCKED: merged result is RED - undoing the merge."; git reset --hard 'HEAD@{1}'; return 1 2>/dev/null || exit 1; }
fi
git push || { echo "BLOCKED: push failed (origin advanced? auth? branch-protected?). Worktree preserved; resolve and re-run."; return 1 2>/dev/null || exit 1; }

# Post-push verify: the worktree tip is genuinely on origin/$BASE_BRANCH now. If not, something raced.
if ! git merge-base --is-ancestor "$LOCAL_TIP" "origin/$BASE_BRANCH"; then
  echo "BLOCKED: $WT_BRANCH tip ($LOCAL_TIP) is NOT an ancestor of origin/$BASE_BRANCH after push. Worktree preserved - investigate."
  return 1 2>/dev/null || exit 1
fi

# Only now is destruction safe.
git worktree remove "$WORKTREE_PATH"
git branch -d "$WT_BRANCH"
git push origin --delete "$WT_BRANCH" || echo "warning: remote $WT_BRANCH delete failed (auth/permission/already-gone) - local cleanup already done."
```

If your task tracker has a link to this branch, update it to point at the merged commit now that the branch is deleted.
