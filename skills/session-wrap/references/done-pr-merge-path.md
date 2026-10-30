# Step 7: done, merge path for a PR-protected default branch

`CLAUDE_SKILL_DIR` is this skill's folder (the one that holds `SKILL.md`). If you read this file from disk, put that folder in its place. The `dev-deploy-safely` skill sits beside it, in the same parent folder.

```bash
BASE_BRANCH=${DEFAULT_BRANCH#origin/}
# The branch is already pushed (Step 6). Bring it up to base first so the PR is a
# clean, current diff, then open and merge the PR.
git -C "$WORKTREE_PATH" fetch origin "$BASE_BRANCH" -q
git -C "$WORKTREE_PATH" merge --ff-only "origin/$BASE_BRANCH" && git -C "$WORKTREE_PATH" push
gh pr create --base "$BASE_BRANCH" --head "$WT_BRANCH" \
  --title "<type>(<scope>): <summary>" --body "<what + why>"

# The merge gate: use the gate-merge.sh script bundled with the dev-deploy-safely skill
# (`../dev-deploy-safely/scripts/gate-merge.sh`, relative to this skill's folder; it runs
# pr-checks-green.sh from the same folder). It waits up to 30 minutes for every check on
# the PR (run it in the background), merges ONLY the commit it gated (squash, pinned to
# that commit's SHA), and confirms the PR shows MERGED. It prints "MERGED <n>" on success and "STOP: <why>" otherwise.
# Never gate on the exit code of `gh pr checks` (some gh versions exit 0 on a CANCELLED
# check) and never hand-roll the check-rollup read.
GATE_MERGE="${CLAUDE_SKILL_DIR}/../dev-deploy-safely/scripts/gate-merge.sh"
gh pr view <n> --json mergeable,mergeStateStatus,reviewDecision   # look first
# --allow-none passes a PR with no checks ONLY when the repo has no CI. The script exits 0
# only when the PR shows MERGED, so the delete below runs only after a confirmed merge.
bash "$GATE_MERGE" <n> --allow-none && git push origin --delete "$WT_BRANCH"
# If the merge is refused because a review is required (reviewDecision=REVIEW_REQUIRED:
# a PR author cannot approve their OWN PR) AND you hold an authorised bypass and the owner
# has said to use it: re-run the same script with --admin. Otherwise stop and get a reviewer.
```

The script is the only merge path for this step: do not rebuild the check read or call `gh pr merge` by hand. If the bundled script is not available, stop and report that instead of merging on a hand-read of the checks. The remote-branch delete in the block above is safe only because the script confirmed `MERGED` first.

If your team tracks work in a task tracker, link the merged PR there once it shows `state=MERGED`.

Two footguns in this path, both easy to hit:

- **`mergeStateStatus: BEHIND`** - rules usually require the branch up to date with base. The merge is refused until the branch is merged up to base, and that update **RESTARTS the required checks**. `gate-merge.sh` handles this itself (it updates the branch with a merge, never a force-push, then gates again, a few times at most); if it still stops with "still behind", merge `origin/$BASE_BRANCH` into the branch by hand, push, and run the script again. Confirm the merge actually landed (`gh pr view <n> --json state` = `MERGED`) before any cleanup. A chained `merge && cleanup` one-liner built from a hand-rolled merge will happily clean up around a still-refused merge.
- **Never delete the remote branch while the PR is OPEN.** Deleting the head branch auto-closes the PR and strands the commits. The `state=MERGED` check is the gate on the delete, not a formality.

Also, do NOT pass `--delete-branch` to `gh pr merge` from inside a worktree: gh then tries to check out the base branch locally and fails (`fatal: '<base>' is already used by worktree at ...`). The server-side merge still succeeds, but the branch is left undeleted - so merge, THEN delete the remote branch as a separate pure-remote op once `state=MERGED`.

Then the LOCAL worktree cleanup (the PR path above deleted only the REMOTE branch). **If this session RESUMED into the worktree (a pick up) rather than creating it with `EnterWorktree` this session, `ExitWorktree(action: remove)` refuses** (not the owner, or a liveness lock is held), and you cannot `git worktree remove` a checkout the session is standing in. The working sequence: call **`ExitWorktree(action: keep)` first** - it returns the session to the main checkout and releases the resume lock - THEN from the main checkout run `git worktree remove "$WORKTREE_PATH"` and `git branch -D "$WT_BRANCH"` (the local branch reads as unmerged after a PR squash-merge, so `-D`; its content is on the base branch and the remote branch is already gone). Only fall back to a manual post-session command if `git worktree remove` still refuses and names another live session as the lock owner.
