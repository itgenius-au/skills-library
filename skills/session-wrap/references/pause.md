# Step 7: if intent is pause

Leave the worktree and branch in place.

If your team tracks work in a task tracker, post a wrap note there stating what is done, what is left, and the next step.

Provide:

- Worktree path.
- Branch name.
- Current dirty or committed state.
- Next command to resume.
- Remaining tasks.

If the user asks for a check or an alarm after the pause, set a durable timer (see "Dated follow-ups get a timer" in Step 9). Every dated follow-up the recap promises (a checkout to remove after a lock date, a check on a date) gets a timer in this same turn, with its id printed in the recap.

Example (a Markdown numbered list, not a fenced block; see "Line-per-item lists" in Step 9):

1. Paused on `wt/fix-auth-refresh` at `/path/to/project/.claude/worktrees/fix-auth-refresh`.
2. Resume with: `cd /path/to/project/.claude/worktrees/fix-auth-refresh`
3. Next: finish OAuth callback tests and rerun `npm test`.

#### Pause: merge decision (only if IS_WORKTREE=1)

Step 6 already squashed and pushed this checkpoint to the worktree branch, so the work is durable no matter what follows. The only question is whether this increment should ALSO land on the default branch now. Other sessions and parallel agents read the default branch, not your worktree branch, so documentation or a skill stranded on the branch is invisible to all of them until it merges.

**Rule:** merge to the default branch when the increment is self-contained and low-risk - documentation, memory, `CLAUDE.md`/`AGENTS.md`, or skills. Keep it branch-only when it touches code, config, or infra, because a partial build is incoherent and deploy-risky on the shared branch. Docs-class is the auto-yes; a partial build is the auto-no. **If ANY non-docs path is present, default to branch-only** (merge the docs later, when the build lands).

Classify the checkpoint's diff and recommend:

```bash
# What this checkpoint changed, relative to the default branch.
CHANGED=$(git -C "$WORKTREE_PATH" diff --name-only "${DEFAULT_BRANCH}...${WT_BRANCH}")
# "Safe-to-merge" class: docs, memory, CLAUDE/AGENTS, skills. Everything else = code/config.
NON_DOCS=$(printf '%s\n' "$CHANGED" | grep -vE '(\.md$|^docs/|^memory/|(^|/)CLAUDE\.md$|(^|/)AGENTS\.md$|^\.claude/)' | sed '/^$/d' || true)
echo "=== changed in this checkpoint ==="; printf '%s\n' "$CHANGED"
if [ -z "$CHANGED" ]; then
  echo "RECOMMEND: nothing to merge (no diff vs $DEFAULT_BRANCH)."
elif [ -z "$NON_DOCS" ]; then
  echo "RECOMMEND: merge to the default branch (docs-class only, low risk)."
else
  echo "RECOMMEND: branch-only (code/config present):"; printf '  %s\n' "$NON_DOCS"
fi
```

Present the file list and recommendation and **confirm before merging** (the default branch is shared; the merge is hard to unwind).

The Merge path named in the bullet below is in `references/done-merge-path.md`. Read it now, before you merge, and stop before its destructive cleanup.

- **Branch-only** (recommended for code): nothing more to do - the work is already on `origin/$WT_BRANCH`. Go to Step 9; pause skips the browser-tab cleanup in Step 8.
- **Merge to the default branch** (recommended for docs-class, once confirmed): run the guards and integration from the **Merge path** - Guards 0-2, the test gate, `pull --ff-only`, `merge`, `push`, ancestor verify - but **STOP before the destructive cleanup**. Do NOT run `git worktree remove`, `git branch -d`, or `git push origin --delete`. Then fast-forward the worktree branch so continued work stays a clean diff:

```bash
BASE_BRANCH=${DEFAULT_BRANCH#origin/}
# Bring the worktree branch back up to the just-merged default branch so the next
# checkpoint is a clean diff.
git -C "$WORKTREE_PATH" merge --ff-only "origin/$BASE_BRANCH" \
  || echo "note: worktree branch diverged from origin/$BASE_BRANCH; ff-realign skipped - resolve manually before continuing."
git -C "$WORKTREE_PATH" push || true   # keep origin/$WT_BRANCH in sync if the realign moved it
```

After a pause-merge the worktree is still mounted, still on `$WT_BRANCH`, now level with the default branch. Keep working in the same window.
