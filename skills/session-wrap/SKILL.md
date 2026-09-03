---
name: session-wrap
description: "End a project working session cleanly: summarize work, capture durable documentation, handle git state, and leave clear pickup instructions."
argument-hint: "[pause|done] [project-name]"
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

If multiple projects were touched, handle each repo separately. Wrap nested repos before the parent repo that contains them.

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

Classify intent as:

- **pause**: work continues later. Preserve branch and worktree.
- **done**: work is complete. Prepare to integrate, push, and close the worktree if applicable.

Infer from the user's words:

| User wording | Intent |
|---|---|
| `pause`, `continue later`, `pick up later`, `for now` | pause |
| `done`, `finished`, `close it out`, `ship it`, `merge it` | done |
| `wrap up` without more detail | ask if worktree cleanup would be destructive |

When in doubt and a worktree exists, default to **pause**.

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

Report:

- What changed.
- Files or docs updated.
- Tests and checks run.
- Git branch and commit state.
- Whether pushed or left local.
- Worktree path if preserved.
- Exact next steps.

Keep the handoff short enough that another engineer can resume without reading the whole conversation.
