---
name: cleanup-git
description: Safely audit and clean up accumulated git state across a repo — orphan branches, old worktrees, "wip" commits, diverged main, stale remote-tracking branches, local-only work that needs preserving. Use whenever the user says "clean up git", "tidy these branches", "what's left on this repo", "git is a mess", "my branches are everywhere", "audit my branches", "lots of wip commits", "diverged from origin", or before a machine move / handoff / long break. Also triggers on specific mentions of worktrees piling up, ancestor branches, remote-gone branches, or divergence between local and origin. Nothing is destroyed without proof that no work is lost — every destructive-looking operation is preceded by a content-verification audit and an explicit per-item approval gate. Use this before anyone types `git branch -D` or `git reset --hard` in anger.
---

# Git Cleanup

A disciplined methodology for safely tidying git state in a repo that has accumulated branches, worktrees, "wip" commits, and divergence from origin. Typically used after lots of parallel session work, before a machine move, or when the repo state is confusing enough that you're nervous about what's where.

## The one non-negotiable rule

**Nothing is destroyed without proving first that no work is lost.**

Every destructive-looking step (delete a branch, `git reset --hard`, force-push, remove a worktree) must be preceded by:

1. **A content check** that proves either (a) the work exists somewhere else that won't be touched, or (b) the branch/commit has no unique work at all.
2. **An explicit per-item approval** from the user. No batch "let's just tidy all of these up" sweeps.

If you find yourself reaching for `branch -D` (capital D = force) or `--force` anything without the audit, stop. Go back to Phase 3.

The reflog is a 90-day safety net — every deleted ref and reset can be recovered via `git reflog` or `git fsck --lost-found` for about three months. This is the emergency backstop, not the plan.

## Why this matters (the reasoning behind the rule)

Git makes destruction very easy. A single `git branch -D feature/whatever` vaporizes a branch with no undo prompt. A `git push --force` can obliterate commits someone else pushed while you were working. A `git reset --hard` wipes uncommitted work silently.

None of git's commands check "is this actually what the user wanted?" — that's your job, before you run them. The goal of this skill is to make that check **routine and disciplined**, not ad-hoc and hopeful.

Common ways real work has been accidentally destroyed:
- Deleting a branch that looks merged but has one unique commit not reachable from main (typical source: cherry-pick wasn't done, work lived only on the branch)
- `git reset --hard` while on the wrong branch — the working tree's uncommitted changes go with it
- `git push --force` overwriting work a teammate pushed between your last fetch and your push
- Removing a worktree with `--force` when the worktree had uncommitted changes
- Treating a "wip" commit as throwaway when it contained unsaved real work you forgot about

Every one of these can be prevented by running a short verification check first.

## Prerequisites — verify before you start

Before touching anything:

- **Working tree must be clean** (or the dirty changes must be known and safe). Run `git status --porcelain`. If non-empty, decide what to do with those changes before anything else — commit, stash, or explicitly discard with the user's blessing.
- **Know which branch you're on**. `git branch --show-current`. If you're about to delete or reset something, you should not be sitting on the thing you're modifying.
- **Fetch the latest from origin**. `git fetch --all --prune`. You want an up-to-date view of remote-tracking branches, especially the `gone` markers.

## The methodology — five phases (plus Phase 0 for orchestrator sweeps)

### Phase 0: Multi-repo discovery (orchestrator mode only)

**Skip this phase entirely if you're inside a single repo.** It only runs when the skill is invoked from a parent directory that contains multiple child git repos.

Detect mode:

```bash
# Immediate subdirs that contain their own .git mark child repos.
CHILD_REPOS=$(find . -maxdepth 2 -name .git 2>/dev/null \
  | grep -v '^\./\.git$' \
  | sed 's|/\.git$||;s|^\./||' \
  | sort)
[ -n "$CHILD_REPOS" ] && MODE=orchestrator || MODE=single
echo "cleanup mode: $MODE"
```

If `MODE=single`, jump to Phase 1.

If `MODE=orchestrator`, run a **read-only** sweep across every child repo (and the parent itself) into one table. No decisions, no destruction. For each repo collect:

- Default branch's local-vs-remote divergence (`rev-list --left-right --count`)
- Local branches whose remote is gone (`[gone]` markers in `branch -vv`)
- Open worktrees, with dirty flag for each
- Count of `wip` commits on the default branch
- Most recent commit timestamp (spot truly stale repos)

```bash
for repo in . $CHILD_REPOS; do
  pushd "$repo" >/dev/null || continue
  default=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|^refs/remotes/origin/||')
  default=${default:-main}
  div=$(git rev-list --left-right --count "origin/$default...$default" 2>/dev/null || echo "? ?")
  gone=$(git branch -vv | grep -c ': gone\]')
  wts=$(git worktree list --porcelain | grep -c '^worktree ')
  wips=$(git log "origin/$default..$default" --oneline 2>/dev/null | grep -c ' wip$')
  last=$(git log -1 --format=%cr 2>/dev/null)
  printf '%-30s | div=%-7s | gone=%-2s | wts=%-2s | wips=%-3s | last=%s\n' \
    "$repo" "$div" "$gone" "$wts" "$wips" "$last"
  popd >/dev/null
done
```

Present the table sorted by "noise" (highest sum of `gone + wips + extra worktrees + divergence` first). The point is to surface where the mess actually lives — most child repos will be clean and can be dismissed in one line.

**Then drill into the noisy ones one at a time.** For each repo the user picks, `cd` into it and run Phases 1-5 as if the skill had been invoked from inside that repo. Do NOT batch destructive operations across repos — the one non-negotiable rule applies per-repo, not per-session. A bad call in one repo shouldn't auto-execute in nineteen others.

**Worktree-liveness caveat.** Before flagging any worktree as "stale" in the table, remember that a clean, ahead=0 worktree is not necessarily abandoned — it may be a paused session. Check `~/.claude/projects/` for an active transcript dir keyed to the worktree path and `ps` for a live Claude process before recommending removal. When in doubt, mark it "needs human" and skip.

**A process scan alone is not enough — also check per-worktree file mtimes.** Codex agents work in their own worktrees too (often under `.Codex/worktrees/` alongside Claude's `.claude/worktrees/`), and Codex's `codex app-server` processes do **not** expose their working directory in `ps`/`pgrep` output — so a process sweep can report "no session active here" while a Codex (or Claude) agent is in fact writing to the worktree every few seconds. The reliable signal is the newest file mtime inside each worktree:

```bash
NOW=$(date +%s)
git worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r wt; do
  newest=$(find "$wt" -type f -not -path '*/.git/*' -not -path '*/node_modules/*' -not -path '*/.venv/*' \
    -exec stat -f '%m' {} \; 2>/dev/null | sort -rn | head -1)   # macOS; Linux: stat -c '%Y'
  [ -n "$newest" ] && printf '%-45s newest=%dmin ago\n' "$(basename "$wt")" "$(( (NOW - newest) / 60 ))"
done
```

Anything modified in the last few minutes is **LIVE — do not touch it**, regardless of what the process scan said. Pair this with a check for any `*.jsonl` transcript modified in the last ~10 min under `~/.claude/projects/` (Claude) and `~/.codex/sessions/` (Codex) to confirm which agent owns it. Burned-in lesson from a real cleanup: `pgrep` reported no session for the repo, but two worktrees were being written to live (one Codex, one Claude) and were correctly preserved only because the mtime check caught them.

#### Cross-repo worktree classification (the "tidy dormant worktrees" sweep)

The per-repo count above tells you *where* worktrees pile up. This sub-sweep tells you *which are safe to clear*, in one table across every repo — the common multi-machine case where dozens of dormant session worktrees accumulate and you want the merged ones gone without drilling into each repo. It is **read-only**; it decides nothing.

The load-bearing dimension the count table misses is **remote-backup status**: a worktree is only safe to unmount lossless if its unique commits are either on `main` OR pushed to its own remote branch. The three columns that matter:

- **REMOTE** — `pushed` (branch ref is on origin, nothing unpushed) / `UNPUSHED:n` (n local commits not on any remote) / `NO-REMOTE` (no upstream at all)
- **AHEAD/main** — unique commits not yet on `origin/main` (0 = work already merged)
- **LIVE / DIRTY** — from the liveness + mtime checks above

```bash
BASE="$(git rev-parse --show-toplevel)"; NOW=$(date +%s)
printf "%-16s %-40s %-5s %-5s %-12s %-6s %-6s %s\n" REPO WORKTREE LIVE DIRTY REMOTE AHEAD AGE STATE
for rel in . $CHILD_REPOS; do
  repo_dir="$BASE/$rel"; [ -d "$repo_dir/.git" ] || continue
  main_path=$(git -C "$repo_dir" rev-parse --show-toplevel 2>/dev/null) || continue
  git -C "$repo_dir" fetch --quiet origin 2>/dev/null
  git -C "$repo_dir" worktree list --porcelain | python3 -c "
import sys
main='''$main_path'''; cur={}; rows=[]
def flush(c):
    p=c.get('worktree')
    if p and p!=main: rows.append(p+'\t'+c.get('branch',''))
for l in sys.stdin:
    l=l.rstrip()
    if l.startswith('worktree '): flush(cur); cur={'worktree':l[9:]}
    elif l.startswith('branch '): cur['branch']=l[7:]
    elif l=='': flush(cur); cur={}
flush(cur)
print('\n'.join(rows))
" | while IFS=$'\t' read -r wt br; do
    [ -z "$wt" ] && continue
    enc=$(echo "$wt" | sed 's|/|-|g; s|\.|-|g'); sd="$HOME/.claude/projects/$enc"; live="no"
    { [ -d "$sd" ] && [ -n "$(find "$sd" -name '*.jsonl' -mmin -10 2>/dev/null | head -1)" ]; } && live="LIVE"
    pgrep -f "$wt" >/dev/null 2>&1 && live="LIVE"
    dirty=$(git -C "$wt" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    up=$(git -C "$wt" rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null)
    if [ -z "$up" ]; then remote="NO-REMOTE"
    else n=$(git -C "$wt" rev-list --count "${up}..HEAD" 2>/dev/null || echo "?"); [ "$n" = "0" ] && remote="pushed" || remote="UNPUSHED:$n"; fi
    ahead=$(git -C "$wt" rev-list --count origin/main..HEAD 2>/dev/null || echo "?")
    lc=$(git -C "$wt" log -1 --format=%ct 2>/dev/null); [ -n "$lc" ] && age="$(( (NOW-lc)/86400 ))d" || age="?"
    if [ "$live" = "LIVE" ]; then st="LIVE-skip"
    elif [ "$dirty" != "0" ]; then st="DIRTY-review"
    elif [ "$remote" = "NO-REMOTE" ] && [ "$ahead" != "0" ]; then st="LOCAL-ONLY-work!"
    elif [[ "$remote" == UNPUSHED* ]] && [ "$ahead" != "0" ]; then st="UNPUSHED-work"
    elif [ "$ahead" = "0" ]; then st="MERGED-clearable"
    else st="pushed-unmerged"; fi
    printf "%-16s %-40s %-5s %-5s %-12s %-6s %-6s %s\n" "$rel" "$(basename "$wt")" "$live" "$dirty" "$remote" "$ahead" "$age" "$st"
  done
done
```

**Reading the STATE column (drives the per-item decision — approval still required per worktree):**

| STATE | Meaning | Default action |
|---|---|---|
| `MERGED-clearable` | 0 unique commits vs main; work is on main | Fully clearable: `worktree remove` + `branch -d`. Safest batch. |
| `pushed-unmerged` | Unique commits NOT on main, but all on origin's branch | Unmount is **lossless** (branch survives on origin). Removing the mount ≠ discarding the work. Delete the branch only if the work is truly abandoned. |
| `UNPUSHED-work` | Local commits on no remote AND not on main | **Preserve first** — push the branch, THEN unmount. Never remove until backed up. |
| `LOCAL-ONLY-work!` | Ahead of main, no upstream at all | **Preserve first** — same as above; this is the only class that can lose work. |
| `DIRTY-review` | Uncommitted changes in the worktree | Commit/stash/discard first (Phase 2 rules). Never `--force`. |
| `LIVE-skip` | Live session or fresh file mtime | Do not touch. |

Caveat: `UNPUSHED:?` (rev-list returned `?`) with `AHEAD=0` usually means the upstream branch was **deleted from origin after merge** — the tracking ref is stale but the content is on main, so it is really `MERGED-clearable`. Confirm with `git ls-remote --heads origin <branch>` (0 matches = gone) before treating it as unpushed work.

After the table, act on the safe batch (`MERGED-clearable`) per-repo with per-item approval, and route `pushed-unmerged` through the same "unmount, keep branch" decision as any paused session. Then drill the noisy repos through Phases 1-5 as below.

### Phase 1: Discovery — enumerate the full state

Do not start classifying until you have a complete picture. Run all of these and keep the output visible:

```bash
# Working tree + current branch
git status --porcelain
git branch --show-current

# Every local branch, with remote-tracking info
git branch -vv

# Every worktree (main repo + additional worktrees)
git worktree list

# Every stash
git stash list

# Every commit reachable from any local ref but not from any remote
git log --all --not --remotes --oneline

# How local main diverges from origin/main (or replace main with your default branch)
git rev-list --left-right --count origin/main...main
# Output format: "<left count>  <right count>"  =  "<commits on origin not local>  <commits on local not origin>"
```

The output of Phase 1 is the canvas for everything that follows. Don't hurry past it — if you miss a branch or worktree here, the classification in Phase 2 is incomplete.

### Phase 2: Classify every item

For every branch, worktree, and unpushed commit block, answer these three questions:

1. **Is it an ancestor of the default branch?** If yes, every commit on it is already reachable from the default branch — deletion literally cannot lose anything, because the commit objects remain.
2. **Does it have unique commits?** If yes, read the diffs. Don't trust commit messages alone — a branch called "wip" might contain real work, and a branch called "feat: big thing" might be a duplicate.
3. **Is the remote still there?** If the branch tracks `[origin/…: gone]`, the remote has been deleted and the local copy is the only one. Deletion here is a real loss unless you've verified otherwise.

Classification table:

| Label | How to recognise it | What it means for safety |
|---|---|---|
| **Ancestor** | `git merge-base --is-ancestor <branch> main` exits 0 | Safe delete — zero loss. Commits remain on main. |
| **Unique, content duplicated elsewhere** | Branch has commits not on main, BUT the files those commits touch are byte-identical to another branch's current state | Safe delete IF you verified md5s. Merging the branch would be redundant. |
| **Unique, not duplicated** | Branch has commits not on main, and the content doesn't exist elsewhere | Destructive delete — needs merge/cherry-pick/explicit "abandon" before delete. |
| **Remote gone, no unique work** | `[origin/…: gone]` and all commits are ancestors of main or duplicated | Safe delete. |
| **Remote gone, with unique work** | `[origin/…: gone]` and has commits not on main or elsewhere | **Only copy in the world.** Push to a new remote name first, then decide. |
| **Diverged main** | `rev-list --left-right --count` shows non-zero on both sides | Needs reconcile, never force-push. |
| **Worktree, clean, branch matches an ancestor or duplicate** | `git status -s` in the worktree is empty; branch classified above | Safe to `worktree remove` then `branch -d`. |
| **Worktree, dirty** | `git status -s` in the worktree shows changes | **Do not touch.** Commit/stash/explicitly discard the dirty changes first. |

### Phase 3: Content verification (before any destructive action)

Three techniques reliably prove content preservation. Pick the one that matches the situation.

**Ancestor check** — the branch's commits are already reachable from the target:
```bash
git merge-base --is-ancestor <branch> main && echo "SAFE: ancestor of main"
```
If this succeeds, deletion cannot lose any commit on the branch — they all still exist on main. The branch name is just a label pointing at an old commit that main has since advanced past. Use this for orphan branches.

**Net-diff check** — quick proof that local-only commits have zero combined effect on the working tree:
```bash
git diff origin/main..main        # must return empty for "safe to reset --hard origin/main"
```
Use this when `main` has local-only `wip` commits and you suspect they cancel out (classic gitlink-cruft pattern: one commit adds a file, another removes it). An empty diff here is the strongest possible proof — the working tree is already byte-identical to the target, so the reset changes nothing on disk, only the commit ref history.

**Content duplication check** — the branch's files are byte-identical to another branch's:
```bash
for f in $(git show --name-only --format='' <sha>); do
  m1=$(git show <sha>:"$f" | md5)
  m2=$(git show <target-branch>:"$f" | md5)
  [ "$m1" = "$m2" ] && echo "  $f: identical" || echo "  $f: DIFFERS (would be lost)"
done
```
Use this when a branch has unique commits but you believe the content landed elsewhere via a different path (e.g. cherry-picked into a feature branch that then merged). Identical md5s mean the files survive even if the commit SHAs don't. Differing md5s mean the branch has work that isn't in the target — you need to merge, cherry-pick, or deliberately abandon.

**Note on `macOS` / `BSD`**: `md5` is the default on macOS; use `md5sum` on Linux. Both produce a stable hash.

### Picking the right check

| Situation | Use |
|---|---|
| Orphan branch, possibly fully merged | Ancestor check |
| Local `wip` commits on main, suspected gitlink cruft / net-zero | Net-diff check |
| Branch with unique SHAs, content possibly replicated elsewhere | Content duplication check |
| Mix of the above | Run all three — they're cheap |

### Phase 4: Decide, per item

Match the classification to an action:

| Situation | Action |
|---|---|
| Ancestor branch | `git branch -d <branch>` — the lowercase `-d` refuses to delete if unmerged, as a safety net |
| Branch with real unique work, clean apply on main | `git cherry-pick <sha>` for linear history, or `git merge --no-ff <branch>` to preserve the branch origin in history |
| Branch with work that would conflict on merge | Manual surgical edits: read the diff, apply the additive parts to main by hand with Edit, skip the no-ops and the conflicts. One clean commit. |
| Branch whose content is OLDER than main | The unique bits are stale. Either port forward (rare — usually supersedable) or safe delete. |
| Diverged main | `git fetch && git pull --rebase` to replay local commits on top of remote. **Never** `git push --force` to reconcile — that overwrites the remote's unique commits. |
| Worktree, clean, branch safe | `git worktree remove <path>` then `git branch -d <branch>` |
| Worktree, dirty | Commit & push, stash, or explicitly discard (with user approval) — then remove. Never `worktree remove --force` a dirty worktree without a recorded decision. |
| Remote-gone branch with unique work | `git push origin <branch>:<branch>` to re-create the remote (or push to a new name), THEN decide merge vs abandon. |
| `wip` commits on main | Verify they're duplicated elsewhere. If yes: `git reset --hard <last-clean-commit>`. If no: squash the wip commits into one clean commit (`git reset --soft <base> && git commit`) then push. |

### Phase 5: The destructiveness audit table

Before executing any destructive-looking plan — even a single command — present a table to the user showing exactly what each step does. The table format is the same whether the plan is 1 step or 10:

**Single-step example** (dropping net-zero wip commits on main):
```
| Step | Command | What's destroyed? | Recoverable? |
|---|---|---|---|
| 1 | git reset --hard origin/main | Drops commit refs <sha1>, <sha2> from main. Net diff vs origin verified empty — no file content changes. | Yes — reflog retains both SHAs for 90 days |
```

**Multi-step example** (squashing a feature branch to main):
```
| Step | Command | What's destroyed? | Recoverable? |
|---|---|---|---|
| 1 | git checkout main | Nothing (working tree verified clean) | n/a |
| 2 | git reset --hard origin/main | Drops commits <sha1>, <sha2> from main's ref. Content verified byte-identical in <feat-branch>. | Yes — reflog + feat-branch |
| 3 | git merge --ff-only <feat-branch> | Nothing. Pure fast-forward, errors out if not FF. | n/a |
| 4 | git push origin main | Nothing local. Origin fast-forwards. No history rewrite. | n/a |
| 5 | git branch -d <feat-branch> | Branch ref only. Commits reachable from main. `-d` (safe) — errors if not merged. | Yes — recreate with git branch |
```

Get explicit "yes, go ahead" from the user. Silence is not approval.

Read the output of each command after running it — don't chain multiple destructive operations in one bash call and assume they all worked.

## Common patterns you'll meet

### "wip" commits
These are often auto-generated by commit hooks. They fall into three categories:

- **Duplicated elsewhere** — the same work also landed in a feature branch or another ref. The wip is redundant noise. After md5 verification, `git reset --hard` to a known-good base drops them cleanly.
- **Real work not yet anywhere else** — preserve first. Squash the wip stream into one clean commit (`git reset --soft <base> && git commit -m "<descriptive message>"`), then push.
- **Gitlink cruft** — commits whose only changes are to `.claude/worktrees/<name>` files (the submodule-like pointers git maintains for additional worktrees). Net-zero, always safe to drop once the worktrees are gone.

### Orphan `claude/<random-name>-<hash>` branches
Created by Claude Code sessions. By the time you see them in a cleanup, they're usually ancestors of main (the session's work got merged, or was abandoned). Run `merge-base --is-ancestor` on each — most are trivial safe deletes.

### Remote-gone branches
`[origin/…: gone]` in `git branch -vv` output. Someone (maybe you, maybe a rebase/merge) deleted the remote branch, but the local one survived. Treat the local copy as "only copy in the world" until you've verified otherwise.

### Diverged main
Local main has commits origin doesn't, and origin has commits local doesn't. Usually happens when another session or machine pushed while you were working. Resolve with `git fetch && git pull --rebase`. Do not force-push. If the local unique commits look like duplicates of what's on origin, check md5s before reset.

### Worktree gitlink cruft
Files under `.claude/worktrees/<name>` are how git tracks additional worktrees. Commits that only modify these files are local-only plumbing and should almost never be pushed. A branch that's 5+ commits ahead of origin with only gitlink changes is safe to `reset --hard origin/<branch>` after confirming no real content moved.

### Accidental `.gitignore` regressions
Old branches sometimes have `.gitignore` diffs that **remove** legitimate ignore patterns (e.g. `tmp/`, `.claude/worktrees/`). These are almost always accidental — a Claude session rewrote the file and lost the lines. Merging the branch forward without noticing would un-ignore those paths on main. Drop the `.gitignore` change during the merge.

## Red flags — stop and confirm

If any of these come up, pause and re-verify with the user before proceeding:

- About to force-push to `main` / `master` — warn loudly, ask for explicit approval
- Reaching for `git branch -D` (capital D) — use `-d` unless you've verified unique content is preserved
- Branch tracks `[origin/…: gone]` AND has unique commits
- Worktree has uncommitted changes and you're about to remove it
- A proposed merge's `git diff --stat` shows more deletions than additions (work loss risk)
- About to `git clean -f` — untracked files are **not in reflog**, permanent deletion
- Current branch has uncommitted changes and you're about to switch branches or reset
- A merge-tree preview predicts conflicts you don't fully understand
- A branch's commits look like they'd revert newer work on main (content is OLDER, not missing)

## A typical cleanup session shape

1. **Orchestrator sweep (optional)** — if invoked from a parent that holds multiple child repos, run Phase 0 to find which repos actually have mess. Then pick one repo and continue with the steps below; loop back per repo.
2. **Discover** — run the Phase 1 bundle, count the outstanding items, note the divergence state.
3. **Classify** — go through each branch, worktree, and diverged block; label the state per the Phase 2 table.
4. **Verify** — for each destructive-looking action, run the ancestor or md5 check; record the result.
5. **Plan** — present the destructiveness audit table, grouped by branch/worktree.
6. **Execute per item with approval** — start with the safe ancestor deletes to build confidence; then the cherry-picks/merges; then the tricky ones with real unique work; save "remote-gone with unique content" and "diverged main" for last when you have full context.
7. **Final verify** — `branch -vv`, `worktree list`, `status -s` should all be clean. `rev-list --left-right --count origin/main...main` should be `0  0`. No stashes unless deliberately kept.

## What this skill does NOT cover

- Initial git setup, `.gitignore` design, or hooks configuration
- Removing secrets from history (use `git filter-repo` for that)
- Complex multi-branch rebase surgery (different risk profile — use a dedicated plan)
- Submodule surgery (git submodules are their own adventure)
- Anything that requires rewriting public history for reasons other than tidying local state

If the task is bigger than tidying current local state, surface that to the user and plan it separately — don't try to absorb it into a cleanup.

## Handoff tip

At the end of a cleanup session, record what you did in a short bulleted summary: which branches were deleted (with their final SHAs — useful for reflog recovery), which were merged and how, which were preserved (and where), and what the final state looks like. This makes the work audit-able later and gives the user a recoverable paper trail if something unexpected comes up.
