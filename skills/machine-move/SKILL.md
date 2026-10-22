---
name: machine-move
description: "Live multi-machine sync (the daily driver) OR one-time new-machine setup. SYNC pushes all git state online, pulls the other machine's work, prunes merged branches, keeps tooling current and makes local-only data durable; its dry run is also the pre-flight audit before you leave a machine. SETUP bootstraps a fresh machine. Triggers on: machine move, move computer, switch machine, new computer, setup machine, receiving machine, sync machine, sync everything online, synchronise machines, push everything up, pre-flight check, sync check, portability check"
---

# Machine Move

Two modes:

1. **SYNC** (live multi-machine sync) - the daily driver. Run it on ANY machine you work on, as often as you like, back and forth. It pushes everything online (main checkout, child repos, worktree branches, dirty-worktree work-in-progress commits) and pulls anything another machine pushed, **without closing anything out**. Then it brings tooling up to date, prunes fully-merged branches, and makes local-only data durable. The SYNC dry run is also the **pre-flight audit**: run it before you leave a machine.
2. **SETUP** (new machine bootstrap) - run ONCE on a new machine after cloning your main repo. Runs your setup scripts, pulls all repos, authenticates, verifies the environment. A fresh machine has nothing for SYNC to act on until SETUP has run.

There is no separate "sending" mode. Leaving a machine is just a final SYNC: it gets every branch and every dirty worktree online, and the local-data step makes files that never enter git durable.

## Mode detection

Ask if ambiguous; otherwise infer:
- "new computer", "just set up", "set up this machine", "receiving", "just opened here", "clone everything" -> **SETUP**
- "sync", "sync this machine", "sync everything online", "push everything up", "pre-flight", "before I leave this machine", "switching computers", "portability check" -> **SYNC**
- "machine move" with no qualifier -> ask

## Configure once: your repo set

Both modes loop over the same set of repos: the main ("parent") repo plus any child repos you keep beside or inside it. Keep that list in ONE place, a plain file with one directory per line (comments start with `#`), for example `scripts/repos.txt` in your parent repo:

```
# directory (relative to the parent repo)
child-project-1
child-project-2
```

Read it with a loop that is safe in both bash and zsh (a literal `for d in $REPOS` string does not word-split in zsh and silently iterates once):

```bash
BASE="$(git rev-parse --show-toplevel)"
REPOS_FILE="$BASE/scripts/repos.txt"          # CONFIGURE
# parent + children
{ printf '.\n'; grep -vE '^[[:space:]]*(#|$)' "$REPOS_FILE"; } | while IFS= read -r dir; do
  echo "=== $dir ==="
  # ... per-repo commands, run as: git -C "$BASE/$dir" ...
done
```

Everything below that says "per repo" means this loop.

---

# SYNC MODE - Live Multi-Machine Sync

A SYNC run has three parts: **repos** (Steps 0-4), **tooling and hygiene** (Steps 5-8), and **local data** (Step 9). A sync is not finished when the repos converge; it is finished when the machine is also on current tools and its local-only data is durable.

## Why it exists

Anything that wip-commits for you (an auto-commit hook, an editor) but never pushes silently accumulates unpushed commits on `main`, child repos and worktree branches. Files you generate or download during a session sit only on this disk. SYNC gets all of it online and pulls the other machine's work back.

## Safety contract (non-negotiable)

- **Append-only.** Push branches that are ahead. Never `--force`, never squash, never soft-reset. (Every historical force-push traced to squashing commits that were already pushed.)
- **Behind -> `git pull --ff-only`** (no merge commits).
- **Diverged -> tag a backup first** (`git tag sync-backup/<branch>-<stamp>`), then rebase ONLY if the diverged commits touch disjoint files. On file overlap, **surface it for a human**. Never auto-resolve "drop local / take remote".
- **Worktrees: never touch a dirty or live worktree, and never do anything but a fast-forward.** Push the branch ref; never merge-to-main, remove, switch, force, or reconcile content. A dormant dirty worktree may get a `wip` commit so the work is captured, unless a live session owns it or a rebase/merge/cherry-pick/bisect is mid-flight (`.git/rebase-merge`, `rebase-apply`, `MERGE_HEAD`, `CHERRY_PICK_HEAD`, `BISECT_LOG`, `sequencer/`). A clean, dormant worktree that is purely behind **its own** remote branch may be fast-forwarded onto `origin/<its-branch>` only.
- **"Live" means any of:** a Claude Code transcript for that path touched in the last 10 minutes, a process whose cwd is inside it, or a changed file (staged, unstaged or untracked, not ignored) edited in the last 30 minutes. If a liveness check itself errors, treat the worktree as live.
- **Per-repo resilient.** One repo's failure never aborts the sweep. Collect failures and report them.
- **Preserve before reconcile.** The backup tag exists before any rebase.

## Step 0: Setup readiness (always first, read-only)

SYNC assumes SETUP has run once on this machine (or, on a shared host, this account). On a machine that was never set up, a sweep would "succeed" on a half-empty environment: no child repos, no settings, no hooks. Check first, and stop if SETUP never ran.

```bash
miss=0; warn=0
[ -f ~/.claude/machine-setup-done ] || { echo "BLOCK: no setup marker (~/.claude/machine-setup-done)"; miss=1; }
[ -f ~/.claude/settings.json ]      || { echo "BLOCK: ~/.claude/settings.json missing"; miss=1; }
# At least one child repo from your repos file must be cloned (the parent alone is not a set-up machine).
cloned=0; total=0
while IFS= read -r dir; do
  total=$((total+1)); { [ -d "$BASE/$dir/.git" ] || [ -f "$BASE/$dir/.git" ]; } && cloned=$((cloned+1))
done < <(grep -vE '^[[:space:]]*(#|$)' "$REPOS_FILE")
[ "$total" -gt 0 ] && [ "$cloned" -eq 0 ] && { echo "BLOCK: none of the $total child repos is cloned"; miss=1; }
[ "$cloned" -lt "$total" ] && { echo "WARN: $((total-cloned)) of $total child repos not cloned (a headless machine may skip some on purpose)"; warn=1; }
# Add your own BLOCK checks here: deployed hooks, the plugin manifest, a Claude Code login, a cloud login.
[ "$miss" -eq 0 ] && echo "READY (warnings: $warn)" || echo "SETUP NEEDED"
```

- **BLOCK** (`SETUP NEEDED`): stop the sync, tell the owner, and switch to SETUP mode. Do not work around it by skipping the check. A BLOCK that is only "the plugin manifest gained a plugin" (often arriving with a pull) is not a missing SETUP: install the missing plugins (install-only, never a clean or uninstall), then re-run the check.
- **WARN**: report it and continue. A repo skipped on purpose stays a warning, and an expired cloud login is reported so it is renewed before Step 9.

Running this loop from a worktree session needs the main checkout as `BASE` (see "Running SYNC from a worktree session").

## Step 1: Dry run (always first, read-only)

Fetch every repo and report what a sync WOULD do. Nothing changes.

```bash
{ printf '.\n'; grep -vE '^[[:space:]]*(#|$)' "$REPOS_FILE"; } | while IFS= read -r dir; do
  r="$BASE/$dir"
  [ -d "$r/.git" ] || [ -f "$r/.git" ] || { echo "=== $dir === MISSING (not cloned)"; continue; }
  echo "=== $dir ==="
  git -C "$r" fetch --all --prune --quiet 2>&1 || echo "  FAIL: fetch"
  git -C "$r" status -sb | head -1                          # branch + ahead/behind
  git -C "$r" status -s | head -20                          # uncommitted
  git -C "$r" stash list                                    # stashed work
  git -C "$r" for-each-ref --format='%(refname:short) %(upstream:short) %(upstream:track)' refs/heads \
    | awk '$2=="" {print "  no upstream: " $1} $3!="" {print "  " $0}'   # local-only / ahead / behind branches
  git -C "$r" log --branches --not --remotes --oneline | head -20   # unpushed commits on ANY branch
  git -C "$r" worktree list                                 # worktrees to check for dirt/liveness
done
```

Present it as a table, one row per repo (and per worktree): uncommitted, stashes, local-only branches, unpushed, behind. Classify each branch: `IN-SYNC`, `WOULD-PUSH`, `WOULD-FF-PULL`, `WOULD-REBASE` (disjoint divergence), `SURFACE` (overlapping divergence, needs a human). For each worktree: `WT-WOULD-PUSH`, `WT-WOULD-COMMIT` (dormant dirty), `WT-BEHIND` (clean, behind its own remote), `WT-SKIP` (detached HEAD or mid-sequencer), `WT-SKIP-DIRTY` (live, leave alone). Flag every non-clean row.

If you only came for the pre-flight audit, stop here and report: "Safe to leave" (all clean and pushed) or the list of problems with the fix for each.

## Step 2: One blanket approval, then execute

Ask once: "push main + children + worktree branches, ff-pull where behind, rebase only disjoint divergences (backup-tagged first), wip-commit dormant dirty worktrees; nothing destructive". Then, per repo:

```bash
git -C "$r" push origin <branch>            # branches that are ahead (use -u for a branch with no upstream)
git -C "$r" pull --ff-only                  # current branch, when behind
# diverged, disjoint files only:
git -C "$r" tag "sync-backup/<branch>-$(date +%Y%m%d-%H%M)" <branch>
git -C "$r" rebase origin/<branch>
```

Dirty dormant worktree: `git -C <worktree> add -A && git -C <worktree> commit -m "wip (sync)"`, then push. Only after the secrets check: do not `add -A` a tree that holds `.env` files or credentials that are not gitignored.

Run unattended apart from surfaced items and per-repo failures; both are reported, neither is destructive.

### Catching up a stale worktree

A clean, dormant worktree that is simply behind its own remote (the branch advanced on another machine) is not a problem, just a catch-up: `git -C <worktree> merge --ff-only @{u}`. It is lossless (ff-only, zero unique local commits) and leaves the worktree mounted. Anything dirty, live, or tracking a different upstream is left as `WT-BEHIND` with the blocker named.

## Step 3: Resolve surfaced items (the only human-judgment part)

Everything left under NEEDS HUMAN was deliberately untouched:

- **A repo's `main` diverged with file overlap** (classically a shared index or notes file both machines edited). Your state is preserved at the `sync-backup/` tag. Resolve by hand, usually `git pull --rebase`, taking both sides of index-style collisions (preserve, do not choose), then push and re-run SYNC.
- **A worktree branch diverged.** Rare. Never reconcile worktree content automatically. Inspect, decide, resolve inside that worktree, re-run.

Recurring cases with a proven fix (all keep history append-only; never force-push):

1. **Push rejected for an oversized file (GitHub 100 MB limit).** A wip commit absorbed a big data file. Confirm the blob exists ONLY in unpushed commits (`git log origin/<b>..<b>`, then `git ls-tree -r -l <b>` filtered by size). Amend the unpushed commit to drop it (`git rm --cached <file>`, add a `.gitignore` entry with a comment, `git commit --amend --no-edit`); this is safe because the commit never reached origin. Keep the file on disk, then archive it and write an archive note: back it up to your backup location (Step 9b, with its approval), verify the byte size or checksum against the local copy, and document it in the tree. The note is an `ARCHIVE.md` next to the data holding what the file is, its size, where the backup lives, the exact restore command and the date, and the `.gitignore` comment points at it. Commit the note and push. A file that is ignored but has no archive note is a portability gap.
2. **Diverged worktree where local is an amended superset of a remote wip commit** (`+1/-1`, `git range-diff` pairs the commits). Another machine pushed the wip, then you amended locally. `git rebase origin/<b>`, resolve the add/add conflict with `git checkout --theirs <file>` (during a rebase `--theirs` is the local commit being replayed), `rebase --continue`, verify the final tree equals the pre-rebase local tree (`git diff <old-sha> HEAD` is empty), then push.
3. **Main push rejected by a "changes must be made through a pull request" rule.** This recurs every run until the commit lands via a PR, so treat it as an action item. `git push origin main:sync/<slug>`, open a PR from it, merge it with a rebase-merge (commits stay 1:1), then `git pull --rebase` locally.
4. **`push -u` rejected on a new worktree branch** because an older session reused the same branch name, pushed and merged it, and never deleted it on origin. Check `git cherry origin/main origin/<b>` and `git cherry origin/main <b>`: if every line starts with `-`, both sides are already in main and nothing is at risk. If any line starts with `+`, that commit is unique, so stop and inspect. Never force-push over the old remote branch.
5. **Diverged because local is a squash of wips that were already pushed** (the session squashed after the sync pushed). Wait first and do NOT reset to origin: that discards the clean squash. Only if clearly abandoned, rebase the squash onto the pushed wips as in case 2.
6. **A stale handed-off branch** (picked up and finished on the other machine): `git cherry` shows commits patch-equivalent and the local diff adds nothing. It has no unique content; resetting it to origin or closing the worktree drops local commits, so get an explicit OK. The backup tag preserves the old state either way.

## Step 4: Multi-machine convergence (the A -> B -> A dance)

SYNC is stateless and converges by sequential runs: sync the primary (pushes its work), sync the secondary (pulls the primary's, pushes its own), then the primary again (pulls the secondary's). Keep alternating until a run pushes nothing, pulls nothing and surfaces nothing on the machine you finish on. That means the **branches** match origin. Worktrees that are merely behind or skipped do not block convergence, so count them and report the number; a catch-up needs the ff-only step above, not more dancing.

## Step 5: Tool updates

A sync should leave the machine both synchronised and current. Two laptops on different CLI versions (Claude Code, Codex, Gemini CLI, git, gh, node, python, your cloud CLI) behave differently on the same repo, invisibly until something misbehaves.

- Print a version table of your tracked tools (installed vs latest), apply the updates for that tracked set (bounded and reversible), then re-verify and print the table again.
- Ask before a bare `brew upgrade` / `apt upgrade` of everything: the long tail moves interpreters and system libraries other tooling stands on (a package-manager run that removes an old Python can break every virtualenv built on it).
- After any wide upgrade, re-verify the environment checks below (wrapper scripts, memory symlinks, settings), because an upgrade can silently drop entry points.
- Keep upgrades out of the git sweep. They are slow, machine-global and can break the interpreters the sweep runs on, so a failed upgrade must never leave a half-synced repo.

## Step 6: Plugins and settings

Confirm the plugin/extension set and the Claude Code settings your team expects are present and identical on both machines (see Environment checks 2e-2f). If you keep a manifest of expected plugins, diff it against what is installed and prune anything the manifest dropped.

## Step 7: Worktree closeout and stale sessions

Closing worktrees is destructive, so SYNC removes a worktree only when ALL of these hold:

- a linked worktree (never the main checkout), not locked, with a branch checked out
- no sequencer mid-flight
- completely clean: no tracked changes, no untracked files; any ignored file is a regenerable cache (`node_modules`, `.venv`, `__pycache__`, `dist`, `build`) or byte-identical to the main checkout's copy
- HEAD is an ancestor of `origin/<default>` after a fresh fetch (a failed fetch skips the repo)
- not live (no process cwd inside it, no running Claude Code session there)
- idle for at least 30 days on transcript, HEAD commit date and newest file mtime

Use `git worktree remove <path>` WITHOUT `--force`, so it can only succeed on a clean, merged worktree. Keep the branch (Step 8 handles it later). Every worktree outside this exact category is skipped, with the reason, and closes through your normal wrap-up or cleanup routine. A directory under `.claude/worktrees/` that git does not list is an orphan: remove it only by hand after checking its contents.

Also list (read-only, never stop or delete) leftover session records older than 7 days: crashed or killed sessions leave `~/.claude/sessions/<pid>.json` entries whose pid is gone. Do not call a CLI command that lists agents for this; read the files directly, since some CLI versions delete dead-session records as a side effect.

## Step 8: Prune fully-merged, inactive branches

Branch deletion is destructive, so it is a gated step, not part of the append-only sweep. But a **fully-merged** branch carries no unique work (every commit is an ancestor of the default branch), so deleting it is lossless. A branch is pruned only if ALL of:

(a) merged into the default branch; (b) not checked out in any open worktree; (c) not a `backup/` or `sync-backup/` ref; (d) not a long-lived environment branch: not on the fixed list (`staging`, `production`, `prod`, `develop`, `dev`, `preview`, `release`, `release/*`) and not named in any `branches:` filter of a CI workflow on the default branch (a deploy workflow can trigger on a fully-merged, idle environment branch, so "merged and old" does not mean "unused"); (e) untouched for 30 days (the pick-up window, so anything you might resume this month survives).

```bash
# Per repo $r. Preview first: drop the final `git push origin --delete` line to list candidates only.
DEFAULT=$(git -C "$r" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|^refs/remotes/origin/||'); DEFAULT=${DEFAULT:-main}
git -C "$r" fetch origin --prune -q || { echo "SURFACE: fetch failed for $r, skipping"; continue; }
OPEN_WT=$(git -C "$r" worktree list --porcelain | awk '/^branch /{sub("refs/heads/","",$2); print $2}')
NOW=$(date +%s); MIN_AGE_DAYS=30
# Branch names that CI workflows on the default branch mention (fail closed if unreadable).
WF_TEXT=$(git -C "$r" ls-tree -r --name-only "origin/$DEFAULT" .github/workflows/ 2>/dev/null \
  | while IFS= read -r f; do git -C "$r" show "origin/$DEFAULT:$f" || exit 1; done) \
  || { echo "SURFACE: cannot read workflows for $r, skipping"; continue; }
git -C "$r" branch -r --merged "origin/$DEFAULT" --list 'origin/*' | grep -v ' -> ' | sed 's# *origin/##' \
  | grep -vxF "$DEFAULT" | grep -vE '^(backup/|sync-backup/)' \
  | grep -vxE '(staging|production|prod|develop|dev|preview|release|release/.*)' \
  | while read -r b; do
      [ -z "$b" ] && continue
      printf '%s\n' "$OPEN_WT" | grep -qxF "$b" && { echo "keep (open worktree): $b"; continue; }
      printf '%s\n' "$WF_TEXT" | grep -qF -- "$b" && { echo "keep (a workflow mentions it): $b"; continue; }
      TIP=$(git -C "$r" log -1 --format=%ct "origin/$b" 2>/dev/null || echo "$NOW")
      [ $(( NOW - TIP )) -lt $(( MIN_AGE_DAYS * 86400 )) ] && { echo "keep (inside ${MIN_AGE_DAYS}d window): $b"; continue; }
      echo "PRUNE (merged + inactive): $b"
      git -C "$r" push origin --delete "$b" || echo "  delete failed (permission / already gone), next sync retries"
    done
```

A clean classification needs no per-item approval; print what was pruned. Only STOP and surface a branch that cannot be classified (failed fetch, errored check, ambiguous ref): "unconfirmed" is not "confirmed safe". Anything outside the category (unique commits, a squash-merged branch that reads as unmerged, a diverged branch) is not covered here; audit it per item. Remove a local copy only with `git branch -d` (lowercase, which itself refuses an unmerged branch), never `-D`. When in doubt, keep the branch: a stray costs nothing, a wrong delete costs work.

## Step 9: Local-data durability and cleanup

Files that never enter git (gitignored data: exports, downloads, generated reports, local databases) exist only on this disk and are lost when the machine is retired. Make them durable, then reclaim disk only on an approved list.

**9a. Find them (read-only).**
```bash
git -C "$r" ls-files --others --ignored --exclude-standard | grep -vE '(^|/)(node_modules|\.venv|venv|__pycache__|dist|build|\.next|\.cache|coverage)/'
```
Group by repo. Skip regenerable caches and build output. Skip files under linked worktrees (they are reported with their worktree).

**9b. Back up (ask first; uploads cost money).** Copy each file to YOUR backup location (a cloud bucket, a NAS, an encrypted drive) and verify by checksum or byte size. Never delete backup objects.

**9c. Reclaim disk (ask first, with an explicit manifest).** Unlinking a local file is the one irreversible act in SYNC, so it has its own safeguards.

1. **Candidates and manifest.** A file is only a candidate when ALL of these hold: an identical copy exists in the backup (checksum match, not just the same name), it is older than 30 days by mtime, it is not inside an open worktree, it is not live config (anything under `.claude/`, such as editor or preview config; back it up, never unlink it), and its path contains no newline or carriage return (the manifest is line-based, so such a path is never listed or pruned). Write the candidates to a manifest file (one path per line, in your scratchpad) and present the list FROM THE MANIFEST FILE, not from log lines: a crafted filename can forge a log line, and the manifest is what the unlink step acts on. Show count, total size, and files grouped by repo and folder, and name any folder that looks like live working files.
2. **Approval covers the list, not the idea.** If the owner approves the whole list, unlink exactly the manifest. If they approve only part of it, or do not approve, skip 9c for this sync. Never add files to the manifest after approval and never unlink by hand outside it. A file that crosses the 30-day line after the preview simply waits for the next sync. An empty manifest means there is nothing to reclaim: skip.
3. **Re-hash at unlink time, per object.** The candidate list came from an earlier read, so immediately before each unlink re-read the backup copy's checksum NOW and re-hash the local file, and keep the file on any mismatch (a file edited since, a stale or spoofed listing, a backup object removed in the meantime). Sketch, with `backup_hash` as the one function you fill in for your backup location (for example `rclone hashsum`, `gsutil hash`, `aws s3api head-object`, or `sha256sum` over ssh on your NAS):

   ```bash
   backup_hash() { :; }   # CONFIGURE: print the checksum of the backup copy of "$1", or nothing if absent
   while IFS= read -r f; do
     [ -f "$f" ] && [ ! -L "$f" ] || { echo "skip (not a regular file): $f"; continue; }
     local_sum=$(sha256sum -- "$f" | cut -d' ' -f1)
     remote_sum=$(backup_hash "$f")
     if [ -n "$remote_sum" ] && [ "$local_sum" = "$remote_sum" ]; then
       rm -- "$f" && echo "unlinked: $f"
     else
       echo "KEEP (checksum mismatch or no backup): $f"
     fi
   done < "$MANIFEST"
   ```

   Print what was unlinked. This is archive-then-unlink, not delete: the data lives on in the backup.
4. **Never put deletion lifecycle rules on the backup location.** Step 9 treats "a verified copy exists in the backup" as proof that the local file may go. An age-based or count-based object-deletion rule on that bucket or share would turn "durable" into "gone" without anyone noticing. Check the backup location's lifecycle or retention settings when you adopt it and again whenever a sync reports a missing object, and never add a delete rule there. Repos with local-only data but no mapped backup location are reported `AT-RISK` and never reclaimed.
5. **Order.** Run 9c only after 9b has made everything durable. Any file still reported as needing backup is local-only: upload it, then re-run to reclaim its disk.

## Running SYNC from a worktree session

If your session lives in a linked worktree (the usual state when work is isolated per session), the repo set and the sweep must still point at the MAIN checkout, not the worktree: the children live beside or inside the main checkout, not inside the worktree.

```bash
MAIN="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"   # git lists the main checkout first
BASE="$MAIN"; REPOS_FILE="$BASE/scripts/repos.txt"
```

Two rules:

1. Call the MAIN checkout's sync scripts by absolute path (`$MAIN/scripts/...`). A sync script that derives its base from its own location sweeps only the worktree when you run the worktree's copy.
2. If your harness restricts compound commands inside a worktree (for example refusing a command line that `cd`s into another checkout, runs `git -C` on a variable path, or chains loops and pipes), do not fight it. Create the multi-line check as a script file with your editor or file-write tool, then run it alone with `bash <file>`. Do not write the file with a heredoc on the same command line, and do not put `sudo` or process substitution on the same line as the script. The restriction reads the command line, not the script body.

---

# ENVIRONMENT CHECKS (shared by SETUP and SYNC)

Local state that does not live in git cannot ride a `git pull`. SETUP runs all of these to verify a new machine; SYNC runs the ones that drift between machines you use live. Report each as OK / MISSING with the fix.

## 2a. Memory symlinks and topic-file portability

If you keep Claude Code auto-memory in your repo (so it travels via git), every file in the auto-memory directory must be a symlink to a git-tracked repo file. Plain files there are NOT portable and are lost on a machine move.

```bash
# Cache key = absolute repo path with / replaced by - and prefixed with -
REPO_PATH="$(pwd)"
CACHE_KEY="-$(echo "$REPO_PATH" | sed 's|^/||; s|/|-|g')"
AUTOMEM="$HOME/.claude/projects/$CACHE_KEY/memory"
ls -la "$AUTOMEM/"
for f in "$AUTOMEM"/*; do
  name=$(basename "$f")
  [[ "$name" == ".DS_Store" ]] && continue
  if [ -L "$f" ]; then
    target=$(readlink "$f")
    [ -f "$target" ] && echo "OK: $name -> $target" || echo "BROKEN: $name -> $target (dangling symlink)"
  elif [ -f "$f" ]; then
    echo "LOOSE: $name (plain file, NOT portable: move into repo memory/ and symlink)"
  fi
done
```

Fix for a loose file: move it into the repo's `memory/` directory, symlink it back, `git add` it:
```bash
mv "$AUTOMEM/loose-file.md" "$(pwd)/memory/" && ln -s "$(pwd)/memory/loose-file.md" "$AUTOMEM/loose-file.md" && git add memory/loose-file.md
```

Memory hygiene that keeps this cheap: the always-loaded index is guardrails plus one-line pointers (identity, preferences, rules that prevent mistakes), topic files hold reference data and are read on demand, project-specific knowledge lives in that project's own directory, and each fact lives in exactly one place. Test before adding to the index: "will this prevent a mistake or save a tool call in more than half of conversations?" If not, it belongs in a topic file. After any session that creates topic files, re-run the check above.

## 2b. Claude Code auth

```bash
[ -f ~/.claude/.credentials.json ] && echo "Claude credentials: OK" || echo "Claude credentials: MISSING (will re-auth on launch)"
```
On macOS the login may live in the keychain instead; a missing file there is not an error. Confirm by launching `claude` once.

## 2c. Cloud provider authentication

```bash
# Example for gcloud - adapt to your provider
gcloud auth list 2>/dev/null
[ -f ~/.config/gcloud/application_default_credentials.json ] && echo "ADC: OK" || echo "ADC: MISSING"
```

## 2d. MCP wrapper scripts and servers

Check every wrapper script your MCP setup creates, and that the MCP servers you expect are registered (`claude mcp list`; read server names with `sed`, not `grep -o '^[a-z0-9_-]*:'`, because plugin server names contain colons). Also flag servers you did NOT expect, ignoring plugin-namespaced ones (they contain `:`).

```bash
# CONFIGURE: your wrapper scripts. Literal args, so it also works in zsh.
for w in my-wrapper-1 my-wrapper-2; do
  [ -x ~/.local/bin/$w ] && echo "OK: $w" || echo "MISSING: $w"
done
```
Fix: re-run your MCP setup script.

## 2e. Claude Code settings and hooks

```bash
[ -f ~/.claude/settings.json ] && echo "settings.json: OK" || echo "settings.json: MISSING"
grep -c "$HOME" ~/.claude/settings.json 2>/dev/null && echo "(paths reference the current home dir; they will not match another machine)"
```
Confirm hooks referenced by settings exist and are executable, and that any scheduled jobs (launchd/systemd) that back them are installed and active on THIS machine.

## 2f. Plugins and project-level MCP

Compare installed plugins and marketplaces against your expected manifest. Audit per-project `.mcp.json` files for stale or duplicate registrations and for absolute paths that do not exist here.

## 2g. Skill symlinks

If your parent repo symlinks child-project skills into its own `.claude/skills/`, list broken symlinks (`find .claude/skills -xtype l`) and child skills that are not linked yet; re-run your skills setup script to repair.

## 2h. Gitignore audit

Review every `.gitignore` for local-only data files and confirm each has a backup (Step 9). A file that is ignored AND not backed up is a portability gap.

---

# HEADLESS AND CLOUD MACHINES (read first when SETUP or SYNC runs on one)

An ephemeral or persistent Linux box with no screen, authenticated only as a service account (or a deploy key), with no interactive owner login, breaks several default assumptions of SETUP and SYNC. Classify the machine before you run either mode.

## Detect the machine class

Deterministic, in priority order:

1. **Explicit marker:** the file `~/.claude/machine-class` or the env var `MACHINE_CLASS`, holding `local`, `cloud-web` (Claude Code on the web: single repo, short-lived) or `cloud-vm` (a managed or long-lived headless box).
2. **Harness env vars:** `CLAUDE_CODE_SESSION_ATTENDED=0` means unattended; `CLAUDE_CODE_REMOTE=true` means a cloud-web session. These belong to the harness and can change, so treat any value you do not recognise as "default safe" (assume unattended and non-interactive).
3. **Fallbacks:** a non-macOS `uname`, a cloud CLI that lists only a service account (`gcloud auth list`, `aws sts get-caller-identity`, and so on), no display, an attached-instance hostname.

On the `cloud-vm` class, **write the marker during SETUP** (`echo cloud-vm > ~/.claude/machine-class`) so later runs get a definite answer instead of guessing.

## Unattended-run rule

When the machine is unattended (marker, `CLAUDE_CODE_SESSION_ATTENDED=0`, or an unrecognised value):

- **Never block on a prompt and never "ask the user".** There is nobody to answer. Run the safe subset (read-only checks, append-only pushes, ff-only pulls, install-only steps) and collect everything that needs a human into a **"manual / interactive follow-ups"** checklist for the owner: the exact item, why it needs a person, and the command to run.
- **No interactive auth.** Browser OAuth, device-code logins and password prompts cannot be answered headless. Do not start one. Record it as a follow-up; use the machine's service identity for whatever it can read.
- **No approval-gated destructive step runs unattended.** Step 8 (branch prune on shared origin) belongs to one site that sees every machine's worktrees, usually a workstation SYNC. Step 9b/9c (uploads, unlinking local data) are approval-gated, so on an unattended machine they are listed, not run.
- **Ephemeral containers:** everything under `~/.claude`, `~/.local`, MCP registrations, plugins, timers and cloned repos can be reclaimed when the container idles, so SETUP is **per container, not one-time**. The durable home for the bootstrap is the environment's own provisioning script, which should call the headless-safe subset of your setup scripts. Do not commit a machine-specific config snapshot from a throwaway hostname.

## Per-machine opt-outs

A machine-local file, `~/.claude/machine-flags`, turns an otherwise-expected component off on that machine only. One flag per line:

```
no-plugin <name@marketplace>
no-mcp <server-name>
```

Your plugin-install and MCP-install steps must honour it: never install or enable a `no-plugin` entry (disable it if it is on), never register a `no-mcp` server (remove it if present), print the active flags, and treat an opted-out component as NOT missing in the readiness check (Step 0) and in the manifest diff (Step 6). Typical use: a heavy tool (a browser-automation MCP, say) that a small box cannot afford. Rules:

- **Never delete a machine's flag file** during SETUP or SYNC. It is that machine's record of a decision.
- On a shared host, **each account has its own file** (its own `$HOME`).
- A plugin enabled at **project** scope in a repo's `.claude/settings.json` overrides the user-scope disable, so do not enable an opted-out plugin at project scope.

## Shared multi-user hosts

Several Linux accounts on one host each start with an empty `~/.claude`: no hooks, memory links, timers, plugins, config or git identity. Each account's first run is a SETUP, not a SYNC. Points that bite:

- **System-wide CLIs are root-owned.** A per-account `npm install -g` with `prefix=~/.local` installs a copy that shadows the system binary on PATH and then never gets the system updater. Install or update the AI and cloud CLIs once for all accounts with elevated rights, not per account. Per-user logins (`codex login`, cloud auth) still apply per account.
- **Set a git identity per account** (`git config --global user.name` / `user.email`). A new account has none, and every commit, including an auto-commit hook, fails without it.
- **Do not commit a host-wide config snapshot from every account.** If your setup writes a per-hostname config backup that all accounts share, a fresh account's near-empty config can overwrite the committed snapshot. Commit it from exactly one account and `git checkout --` the others' diffs.
- **Dry-run an installer before running it on a host with live sessions.** User-scope hook and settings changes reach running sessions mid-session. Run the installer against a copy of `~/.claude` in a sandbox `HOME`, diff the resulting `settings.json` against the live one, and run the real install only when the diff is exactly the intended change.
- **Never restart or stop other accounts' long-running services from SYNC.** Record process ids before and after a run and report any change instead of restarting anything.

---

# SETUP MODE - New Machine Setup

Run on the NEW machine after cloning your main repo. Runs setup scripts, pulls everything to latest, verifies the environment. On a headless or cloud machine, read "Headless and cloud machines" above first.

## Setup on a not-quite-fresh machine

If SETUP is re-run on a machine that has been working a while, and `git status -sb` on the parent or any child shows commits ahead of origin BEFORE you start, treat them as real work and reconcile by rebase, not destructive reset:

- `git pull --rebase` auto-drops commits already upstream under different SHAs.
- Stash working-tree changes your setup scripts make (gitignore additions, config refreshes) before rebasing; they conflict on pop and need both sides merged.
- Conflicts in index-style notes files: take both sets of entries (preserve, do not choose).
- Modify/delete conflicts: check whether the file ever existed on `origin/main` (`git log origin/main -- <path>` empty means local-only, keep it).
- Unique unpushed work in a child survives a rebase as a clean ahead commit; push it at the end.

## Step 1: Check prerequisites

```bash
for cmd in node npm npx python3 gcloud claude git gh; do
  command -v "$cmd" >/dev/null 2>&1 && echo "OK: $cmd ($(command -v $cmd))" || echo "MISSING: $cmd"
done
```
If critical tools are missing (macOS example): `brew install node python pipx uv gh`, `brew install --cask google-cloud-sdk`, `npm install -g @anthropic-ai/claude-code`. Do NOT run setup scripts until prerequisites are met.

## Step 2: Cloud provider authentication

Check auth state and walk through login if needed (for gcloud: `gcloud auth login`, then `gcloud auth application-default login`).

## Step 3: Run your setup scripts

Run your setup scripts in order (for example `./scripts/setup-*.sh`: one that clones or pulls child repos, one that creates memory symlinks, one that installs MCP servers and wrappers). Each should be idempotent.

Then restore your global settings (for example `cp config-backup/global/settings.json ~/.claude/settings.json`) and install the plugins your manifest lists.

## Step 4: Pull all repos to latest

Per repo: `git fetch --all --prune` then `git pull --ff-only`. If a repo is not a fast-forward, stop and use the not-quite-fresh-machine notes above.

## Step 5: Restore local data (optional)

Pull down any backed-up local-only data this machine needs (the inverse of SYNC Step 9b).

## Step 6: Clean up stale artifacts

Orphan repos (a directory with a `.git` that is not in your repos file, so a new machine would never clone it), stale MCP wrappers and servers, legacy directories, stale skill symlinks, loose memory files, and plugins/marketplaces the manifest no longer lists.

## Step 7: Verify

Run the Environment Checks above and present a checklist:

| Check | Status | Action needed |
|---|---|---|
| Memory symlinks | OK / MISSING | re-run the memory setup script |
| Claude credentials | OK / MISSING | auth on first launch |
| Cloud auth | OK / MISSING | provider login command |
| MCP wrappers | OK / N MISSING | re-run the MCP setup script |
| settings.json | OK / MISSING | restore from your config backup |

## Step 8: Summary

If everything passed, write the setup marker that SYNC Step 0 looks for (`date -u +%Y-%m-%dT%H:%M:%SZ > ~/.claude/machine-setup-done`; on a shared host each account has its own `$HOME`, so each account writes its own), then say: "New machine fully set up. All repos cloned and up to date. MCP servers registered. Restart Claude Code to load MCP servers." Remind about first-use OAuth: any MCP server that authenticates in the browser will prompt on first use.

If issues remain, list each with its fix and offer to re-run the specific setup script. After SETUP, switch to SYNC for all future work between machines.
