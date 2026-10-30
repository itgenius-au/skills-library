---
name: session-dsp
description: "Squash the per-turn `wip` commits from this session into one clean commit and push. Worktree-aware: skips the attribution check on a worktree branch (each worktree = one session, no collisions possible). Pairs with the bundled wip-commit hook (scripts/auto-commit.sh). Triggers on: session dsp, dsp, squash and push, clean up wips, finalize commits."
---

> **Opt-in.** This skill is inert until you install the bundled wip-commit hook (see "Install the wip-commit hook" below). Without the hook there are no `wip` commits to squash, and session-dsp has nothing to do.

# Session DSP - Squash + Push

The bundled wip-commit hook (`scripts/auto-commit.sh`) saves every Claude turn as a `wip`
commit in your working repo. DSP collapses those wips into one descriptive commit before pushing.

The naive form ("soft-reset to the last non-wip commit") is unsafe on a shared branch (for example a
shared `main`) when another Claude session has been working in the same directory: its wip
commits sit in the same window and would get swept into your commit message.

This skill is the safe form. It branches on context:

- **Worktree mode** - running inside a worktree (created with `git worktree add`, or by your editor or agent tooling; see Step 0.5). Each worktree is one session on its own branch. Attribution is trivially "all of it is yours", so skip the check.
- **Shared-branch mode** - running on a shared branch (e.g. `main` of a checkout used by more than one session). Run the attribution check before squashing.

## Step 0: Sanity checks

```bash
git rev-parse --abbrev-ref HEAD                # not detached
git status --porcelain                         # working tree state
git log --oneline -1                           # what's at HEAD
git rev-list --count @{u}..HEAD 2>/dev/null    # commits ahead of remote
```

Bail or ask if:
- Detached HEAD.
- Branch has no upstream (you'll need to push with `-u`).
- Working tree dirty with un-staged content (the wip hook normally handles this; if it did not, find out why).

## Step 0.5: Detect worktree mode

```bash
GIT_DIR=$(git rev-parse --git-dir)
COMMON_DIR=$(git rev-parse --git-common-dir)
[ "$GIT_DIR" != "$COMMON_DIR" ] && MODE=worktree || MODE=shared
echo "DSP mode: $MODE"
```

`--git-dir` returns the per-worktree dir (`.git/worktrees/<name>`) when in a worktree;
`--git-common-dir` always returns the main `.git`. They differ if and only if you are in a worktree.

- **`MODE=worktree`** -> skip Step 2. Every wip on this branch is yours by design (a worktree branch is per-session). Go to Step 3.
- **`MODE=shared`** -> run the Step 2 attribution check. This is the multi-session collision guard.

## Step 1: Locate the squash window

```bash
LAST_NONWIP=$(git log --pretty=format:'%H %s' | awk '$(2) != "wip" {print $(1); exit}')
git log --oneline ${LAST_NONWIP}..HEAD
```

The window is every commit after `LAST_NONWIP` up to `HEAD`. If the window is empty, there is
nothing to squash: skip to push (if ahead of remote).

## Step 2: Attribute each wip to this session, OR another

**Skip this step if `MODE=worktree` from Step 0.5.** Worktree branches are per-session by
construction; there is no other session committing there.

Shared-branch mode only. For each commit in the window, list its changed files:

```bash
for sha in $(git rev-list ${LAST_NONWIP}..HEAD); do
  echo "=== $sha ==="
  git show --pretty=format:'%h %ci %s' --name-only $sha
done
```

**Attribution rule:** a wip is *ours* if and only if every file it touched was also edited by
this conversation (your own Edit/Write tool calls). Read your tool history: you know what you
have touched this session. Do not guess.

**Harness-driven caveat.** Some wips touch only files the harness writes on your behalf (for
example auto-memory files under a `memory/` directory), not files from your direct Edit/Write
calls. Strict attribution would flag those as foreign and STOP. They are usually safe to bundle
when no *concurrent writer* is active. Before bundling, confirm no other live session is writing
to this repo:

```bash
# Any other Claude transcript for this project modified in the last 5 minutes?
find "$HOME/.claude/projects" -name "*.jsonl" -mmin -5 2>/dev/null | wc -l
# Any other claude process pointed at this working dir?
pgrep -f "$(basename "$PWD")" 2>/dev/null | grep -v $$ | wc -l
```

If both are effectively zero (or only your own session shows up), the harness-driven wips are
bundlable: surface them in the table and ask the user "concurrent sessions are quiet, OK to
bundle?" rather than auto-STOP.

Classify the window:
- **All ours, contiguous** -> proceed to Step 3 (normal DSP).
- **None ours** -> STOP. Print: "No wip commits from this session. Nothing to squash." Do not push someone else's work.
- **Mixed / interleaved** -> STOP. Print the table (sha, time, files, ours?) and ask the user how to proceed. Do NOT auto-rebase or cherry-pick around foreign commits: that is surgery, not DSP.

The "all ours, contiguous" path is the overwhelmingly common case for solo-session work. The
other cases are escape hatches that protect concurrent sessions.

## Step 3: Draft the commit message

Run:

```bash
git diff ${LAST_NONWIP}..HEAD --stat
git diff ${LAST_NONWIP}..HEAD
```

Draft a message that focuses on the *why*, not the *what*. Match the repo's commit style
(check recent non-wip commits with `git log --oneline -10 | grep -v ' wip$'`).

Format:
```
<scope>(<area>): <subject under 70 chars>

<body: why this change, what it enables, any gotchas>

<your repo's standard trailer / co-author line, if any>
```

**Show the draft to the user and wait for approval.** Never commit and push on their behalf
without an explicit OK.

One exception: when the user has asked `session-wrap` to close out the session and it runs this
squash in worktree mode, that request counts as the approval. Shared-branch mode always waits for an OK.

## Step 4: Squash + push (atomic)

**Secret scan first - it blocks the commit.** Before the reset, scan every line the squash
would commit. `CLAUDE_SKILL_DIR` is this skill's folder:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/scan_secrets.py" --base "$LAST_NONWIP"
```

- Exit 0: clean, go on.
- Exit 2: **STOP. Do not reset, commit or push.** Show the user the masked findings (the
  script never prints the value). Remove the value, and rotate it if it was ever pushed
  anywhere. For a known false positive, add `secret-scan: allow` to that line. Scan again.
- Exit 1: the scan could not run. Say so and ask the user before you push. Never read it as clean.

On Windows, use `python` if `python3` opens the Microsoft Store. A value that is code, not a
literal (`api_key=self.api_key`, `secret = get_secret(name)`), is not reported. A pushed secret
cannot be taken back, only rotated.

Once approved, run reset + commit + push in a **single bash call**. The wip hook fires after
every Claude turn: if reset and commit are in separate turns, the hook will re-wrap your
soft-reset state into a new `wip` between them.

```bash
git reset --soft <LAST_NONWIP> && git commit -m "$(cat <<'EOF'
<your drafted message>
EOF
)" && git push
```

For a nested repo (a repo inside the one you started in), confirm before running `git push`.

WARNING: **The squash target must be on the branch's own history: never `reset --soft
origin/main` from a worktree.** In a busy repo, `origin/main` has usually advanced past the
worktree's base; `reset --soft origin/main` then commits the worktree's STALE copies of every
file main changed in the meantime, silently baking reverts of other sessions' merged work into
your "clean" commit. Always squash to `<LAST_NONWIP>` on the branch. **Post-squash gate:**
`git diff --stat origin/main..HEAD` must list ONLY files your session touched. Any unexpected
file means the commit is poisoned: rebuild it as a pure patch (`git diff <worktree-base>
<tip>`, base from `git reflog show <branch>` "Created from" entry, applied onto current
`origin/main` with `git apply --3way`).

## Step 5: Verify

```bash
git log --oneline -3
git status
```

Confirm:
- New commit on top, no `wip` between it and `LAST_NONWIP`.
- Working tree clean.
- Branch in sync with remote (or one ahead if push was deferred).

## Install the wip-commit hook

The hook is **opt-in**. It commits a local `wip` after every Claude turn so nothing is ever
lost mid-session, and session-dsp squashes those into one clean commit. It never pushes, and it never
commits onto `main`/`master`/`trunk` (protected-branch guard), so it is safe on any feature or
worktree branch.

The pattern is small, so you can write your own instead: a Stop hook that, on a non-protected branch, runs
`git add -A && git commit -m wip` when the tree is dirty. The only contract session-dsp relies on is that
the throwaway commits have the exact subject `wip`.

**What the hook stages.** It runs `git add -A`, so it commits everything that is not git-ignored. Make sure
secrets, local env files and large build output are in `.gitignore` before you turn it on. Squashing
rewrites only local history; nothing is pushed until the final step of DSP.

1. The hook script ships with this skill at `scripts/auto-commit.sh`. Point your Stop hook at
   it. Add to `~/.claude/settings.json` (create the `hooks` block if it is not there):

   ```json
   {
     "hooks": {
       "Stop": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "\"${CLAUDE_PLUGIN_ROOT}/skills/session-dsp/scripts/auto-commit.sh\"",
               "shell": "bash"
             }
           ]
         }
       ]
     }
   }
   ```

   If your Claude build does not expand `${CLAUDE_PLUGIN_ROOT}` inside `settings.json`, copy the
   script somewhere stable (for example `~/.claude/hooks/auto-commit.sh`), `chmod +x` it, and
   point the `command` at that absolute path instead.

2. Start a new session on a feature or worktree branch. Each turn now leaves a `wip` commit.
   Run `session-dsp` when you are ready to collapse them and push.

## Edge cases

- **Hook re-wrapped between reset and commit**: you did not run them atomically. Soft-reset again from where the new wip lands and re-do as one bash call.
- **Push rejected (non-fast-forward)**: someone pushed to remote since you started. Pull/rebase, re-verify the squash window is still clean, push.
- **Window contains a real (non-wip) commit you forgot about**: `LAST_NONWIP` is correct by definition (first non-wip walking back from HEAD). If you see a non-wip commit in the window, your awk is wrong: debug before squashing.
- **The wips touch tooling/config files you did not intend**: read the diff carefully in Step 3. The hook captures *everything*, including stray edits from other tools. Reset narrower if needed (`git reset HEAD~N --soft` then re-stage selectively).
- **Multi-session reality (shared-branch mode)**: if you run DSP on a shared branch and another session's wip sits between yours, you cannot do a clean squash without rewriting their work. The right move is to use a worktree next time (`git worktree add ../my-task -b my-task`) so each session gets its own isolated branch, which eliminates the problem at the source. For the current jam, ask the user whether to (a) wait, (b) preserve foreign wips by cherry-picking onto a clean base before recommitting, or (c) leave as-is.

## Why "atomic" matters

The wip hook runs on stop. A bash call is one tool use; the hook waits until it returns. So
`reset && commit && push` inside one Bash call all happen before the hook fires. Splitting them
across turns gives the hook a chance to re-wip your soft-reset state, undoing the squash.
