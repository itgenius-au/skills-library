---
name: session-wrap
description: "End or checkpoint a working session cleanly with three distinct intents - done (complete: integrate and close), pause (staying in this window), or pick up (window closing or compacting: hand off a self-sufficient resume prompt). Summarizes work, captures durable docs, and handles git state."
argument-hint: "[done|pause|pick up] [project-name]"
---

# Session Wrap

Use this skill at the end of a working session in a project or worktree.

The goal is to preserve useful state, keep documentation current, and avoid leaving ambiguous git or deployment state for the next person.

## Step 1: Detect Active Project

Identify the project from:

- Current working directory.
- Git root.
- Worktree path.
- Files changed during the session.
- The most recent context activation.

If multiple repos were touched, handle each separately. Wrap nested repos before the parent repo that contains them.

Run:

```bash
pwd
git rev-parse --show-toplevel
git status --short --branch
git branch --show-current
```

## Step 2: Summarize The Session

Prepare a concise summary before changing git state.

Include:

| Section | Content |
|---|---|
| Done | Features, fixes, reviews, deploys, docs completed |
| Discovered | Findings, gotchas, decisions, external service behavior |
| Pending | Started but unfinished work |
| State | Current branch, dirty files, pushed/unpushed commits, deployment state |

If the session included production work, include exact deploy targets, revisions, smoke checks, and rollback pointers.

## Step 3: Decide Wrap Intent

Three distinct intents, with different downstream behaviour. The key split is
whether this window stays open:

- **done**: work is complete. Integrate to the default branch and clean up
  (worktree removed, branch pruned). The next session starts fresh.
- **pause**: work continues in THIS window - you are staying, usually waiting on
  something external. Make the work durable (commit and push) and keep the
  worktree mounted, but do NOT clean up and do NOT emit a full resume prompt. The
  open window keeps the context alive, so the full handoff would be wasted.
- **pick up**: this window is CLOSING or being COMPACTED - work continues in a
  future or freshly-compacted session. Preserve everything (worktree and branch
  stay) and hand off a single copyable resume prompt. Write it to be
  self-sufficient enough to survive a full window close, even when you expect to
  resume right after compacting (a compact keeps only a little context).

Infer from the user's words:

| User wording | Intent |
|---|---|
| `done`, `finished`, `close it out`, `ship it`, `merge it` | done |
| `pause`, `hold`, `waiting on`, `keep the window open`, `standby` | pause |
| `pick up`, `pickup`, `compact`, `continue later`, `new session`, `for now` | pick up |
| `wrap up` with no qualifier | ask before proceeding (worktree cleanup is destructive) |

When in doubt and a worktree exists, default to **pick up**, never done - never
auto-delete a worktree. pick up and pause are both non-destructive.

## Step 4: Scan For Documentation Updates

Review the session for anything that should outlive the conversation.

Checklist:

- Architecture changed.
- Infrastructure or environment changed.
- External service behavior learned.
- New credentials, services, webhooks, or scheduled jobs introduced.
- Deployment process changed.
- Project instructions or routing became stale.
- A gotcha was discovered.
- A technical decision was made.
- A deploy or rollback happened.

Prefer project documentation over global memory.

Priority order:

| Priority | Target | What belongs there |
|---|---|---|
| 1 | Your project's `docs/architecture.md` | System shape, components, data flow |
| 1 | Your project's `docs/deployment.md` | Deploy commands, environment, verification |
| 1 | Topic docs | Integration-specific behavior |
| 2 | Your project's `docs/gotchas.md` | Project-specific footguns |
| 2 | `.claude/CLAUDE.md` or `AGENTS.md` | Routing pointers to new docs |
| 3 | Shared or parent-repo docs | Cross-project patterns only |

Do not create new memory files for project-specific details when an existing project doc can be extended.

Before writing docs:

1. Read the target doc.
2. Propose the exact section to add or update.
3. Get approval if the team's workflow requires review before documentation changes.

## Step 5: Detect Worktree State

Run:

```bash
GIT_DIR=$(git rev-parse --git-dir)
COMMON_DIR=$(git rev-parse --git-common-dir)
if [ "$GIT_DIR" != "$COMMON_DIR" ]; then
  IS_WORKTREE=1
  WORKTREE_PATH=$(git rev-parse --show-toplevel)
  MAIN_PATH=$(dirname "$COMMON_DIR")
  WT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
  WT_NAME=$(basename "$WORKTREE_PATH")
  echo "In worktree at $WORKTREE_PATH on branch $WT_BRANCH (main checkout: $MAIN_PATH)"
else
  IS_WORKTREE=0
  echo "Not in a linked worktree."
fi
```

Then check branch relationship:

```bash
git fetch origin --prune
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|^refs/remotes/||')
[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH="origin/main"
git status --short --branch
git rev-list --left-right --count "$DEFAULT_BRANCH"...HEAD
```

## Step 6: Clean Up Commits

If the repo uses auto-commit hooks, squash session `wip` commits into one descriptive commit before pushing.

General pattern:

```bash
LAST_REAL=$(git log --oneline | grep -v "^[a-f0-9]* wip$" | head -1 | awk '{print $1}')
git reset --soft "$LAST_REAL"
git status --short
git commit -m "Describe the completed work"
```

Only squash commits that belong to this session. Do not rewrite unrelated team commits.

If there are no changes, say so and skip commit work.

## Step 7: Handle Worktree Closeout

### If Intent Is Pause

Leave the worktree and branch in place.

Provide:

- Worktree path.
- Branch name.
- Current dirty or committed state.
- Next command to resume.
- Remaining tasks.

Example:

```text
Paused on wt/fix-auth-refresh at /path/to/project/.claude/worktrees/fix-auth-refresh.
Resume with: cd /path/to/project/.claude/worktrees/fix-auth-refresh
Next: finish OAuth callback tests and rerun npm test.
```

### If Intent Is Pick Up

Also non-destructive: leave the worktree and branch mounted exactly as they are.
The only difference from pause is the handoff - because the window is closing (or
about to be compacted), Step 8 emits a full, copyable resume prompt instead of a
short recap. Do not clean up, merge, or delete anything here.

### If Intent Is Done

Before merging or deleting anything:

1. Ensure all changes are committed.
2. Fetch origin.
3. Confirm the worktree branch includes the current default branch.
4. Confirm the main checkout is clean and on the default branch.
5. Ask before deleting the worktree or remote branch if the team requires explicit cleanup approval.

Safe merge pattern from the main checkout:

```bash
BASE_BRANCH=${DEFAULT_BRANCH#origin/}
cd "$MAIN_PATH"

PRIMARY_BRANCH=$(git rev-parse --abbrev-ref HEAD)
PRIMARY_DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$PRIMARY_BRANCH" != "$BASE_BRANCH" ] || [ "$PRIMARY_DIRTY" != "0" ]; then
  echo "Primary checkout is not clean on $BASE_BRANCH. Stop and resolve manually."
  return 1 2>/dev/null || exit 1
fi

git fetch origin --prune
git pull --ff-only
git merge --ff-only "$WT_BRANCH" || git merge --no-ff "$WT_BRANCH" -m "merge: $WT_BRANCH"
git push
git worktree remove "$WORKTREE_PATH"
git branch -d "$WT_BRANCH"
git push origin --delete "$WT_BRANCH" || true
```

Stop immediately if any command fails. Do not continue cleanup after a failed merge or push.

## Step 8: Final Handoff

Branch on intent - the three modes end differently.

### done

A readable close-out; there is nothing to resume. State the outcome, the
branch/worktree disposition (merged and removed, or discarded), deploy state if
relevant, and end with a one-line "next session starts fresh".

### pause

A short status recap, NOT a resume prompt - the window stays open and context is
live. Say what was pushed, what docs were captured, and what you are waiting on,
then the exact next action for when you resume.

### pick up

Emit ONE copyable, self-sufficient resume prompt as a single fenced block. It
must let a fresh (or freshly-compacted) session continue without the prior
context, so include: project, worktree path + branch, deployed/branch state,
known blockers, the exact next steps, and any reference doc. Even when you expect
to resume right after compacting, write it so it stands alone if the window is gone.

Worktree mode:

```text
Activate <project> context with worktree as <wt-name>. Pick up from <date> session.
State: worktree at <path> on branch <branch> - <commits ahead>, <clean/dirty>.
Deployed: <what is live, if any>.
Next steps:
1. <highest priority>
2. <second priority>
Reference: <plan or doc, if any>
```

Single mode (no worktree):

```text
Activate <project> context. Pick up from <date> session.
State: <what is deployed, what branch>.
Next steps:
1. <highest priority>
2. <second priority>
Reference: <plan or doc, if any>
```

Keep every handoff short enough that another engineer, or your next session, can
resume without reading the whole conversation. For pick up, the copyable prompt
must be one unbroken block, not split across prose.
