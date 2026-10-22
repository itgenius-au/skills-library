# Machine-wide sweep (every account, every clone)

Use this when the ask is "check this machine for stray repos" or "find work from old sessions that never reached main or origin", not just one repo. The Phase 0 table covers child repos under one parent. A whole machine also hides work in `/tmp` clones, in other accounts, and in agent workspaces, so commits can exist only on the box.

Everything here is **read-only** until the per-item approval gate. Deletions still follow Phases 3-5.

## 1. Find every repo

```bash
find / -xdev \( -path /proc -o -path /sys -o -name node_modules -o -name .cache -o -name .venv \) -prune \
  -o -name .git -print 2>/dev/null | sed 's|/\.git$||' | sort > repos.txt
```

- Drop test fixtures (pytest dirs, review-scratch repos whose `origin` is a local bare repo) and package caches. Keep only repos with a real hosted `origin`, plus any repo whose `origin` is a local path to a real repo (commits there are not on the host).
- Group checkouts by `git rev-parse --path-format=absolute --git-common-dir`, so a repo and its worktrees are audited once.
- A path that fails `rev-parse` is not safe to skip. Inspect it: a "dubious ownership" error means another user owns it (read with `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0='*'` in a script); a `.git` FILE pointing at a missing gitdir is a copied worktree (section 5).
- Agent tools can keep private checkouts outside the usual folders (for example per-task workspaces under a hidden dot-folder in a home directory). Sync tools usually do not look there. Include them.

## 2. Other Linux accounts

A process cannot read another account's home (mode 750). If you have sudo, audit **as the owner**, not as root, so nothing root-owned lands in their repos:

```bash
cd /tmp                                   # the owner must be able to stat the cwd, or git fails "failed to stat ... Permission denied"
sudo -u <owner> -H env GIT_OPTIONAL_LOCKS=0 bash /path/to/audit-script.sh --no-fetch
```

- `GIT_OPTIONAL_LOCKS=0` stops `git status` from rewriting the owner's index. Do not fetch: their tracking refs are stale, so verify flagged items against the host instead (section 3).
- If the owner has no host credential, push their local-only work by writing a `git bundle` as the owner, importing it into a scratch bare repo as yourself, verifying the tip SHAs and `fsck`, then pushing a NEW backup branch (no force).
- If sudo is gone mid-session (access can be revoked), stop. Hand the owner a script that re-verifies each item and acts only on the account that runs it.

## 3. Prove where the work is

"Unpushed" on a local branch usually means **squash-merged**: the host deleted the merged branch, and `fetch --prune` removed the tracking ref, so the old SHAs look local-only. Clear or confirm each flagged branch:

| Evidence | Check |
|---|---|
| Merged PR | `gh pr list --repo <o>/<r> --head <branch> --state all --json number,state,baseRefName,headRefOid` with `headRefOid` = branch tip and base = default branch |
| Patch already on main | `git cherry origin/main <branch>` shows `-` for every commit |
| Content on main | per-file blob compare, `git rev-parse <branch>:<f>` vs `origin/main:<f>`; or the share of added lines present on main |
| Commit on the host at all | `gh api repos/<o>/<r>/commits/<full-sha>` (404 = not there) |

A 404 is a finding only with a **positive control**: query a commit you know is on `main` first. Otherwise a wrong SHA form or a token problem reads as "not on the host".

## 4. Before any delete

- **Ignored files.** `git status` hides gitignored files, and deleting the folder removes them. Count ignored files that are not regenerable caches: `git status --ignored --porcelain | grep '^!!'` minus `node_modules/`, `.venv/`, `__pycache__`, build output. Anything left is a design artifact or data: preserve or name it.
- **Idle time.** Measure the newest file mtime EXCLUDING `.git` (`find <dir> -name .git -prune -o -type f -printf '%T@\n'`). Your own `fetch`/`status` touches files inside `.git`, which makes every audited clone look fresh.
- **Live use.** Check process working directories (`ls -l /proc/[0-9]*/cwd`, needs root to see other accounts) and open files before removing a `/tmp` clone.
- **Count worktrees, not checkouts.** A repo's main checkout on `main` is "clean and merged" but is never a removal candidate. Filter to paths under the worktree folder before you report a count.
- **Hidden edits.** `git status` does not show edits to files marked skip-worktree or assume-unchanged, and `git worktree remove` deletes them. Run `git ls-files -v`: a line that starts with `S` (skip-worktree) or a lowercase letter (assume-unchanged) means keep the worktree.
- **Re-check right before the remove.** The checks above take time, and `git worktree remove` deletes ignored files even without `--force`. Run the clean, hidden-edit, ignored-data and live-use checks again immediately before each remove. A file written during a slow check has been lost this way.
- **Session listing is not read-only.** `claude agents --json [--all]` can delete the registry files of dead sessions while it lists (CLI 2.1.283). For a read-only session inventory, read `~/.claude/sessions/<pid>.json` and `~/.claude/jobs/<id>/state.json` directly.

## 5. Copied worktrees

A `cp -r` of a linked worktree keeps a `.git` FILE that points at the ORIGINAL worktree's admin dir (`<repo>/.git/worktrees/<name>`). Read `<repo>/.git/worktrees/<name>/gitdir` to see which path is registered.

- In the copy, `git status` compares the copy's files with the REAL worktree's index: "dirty" files are just the copy being older, and a plain status can rewrite that shared index. Read copies with `GIT_OPTIONAL_LOCKS=0`.
- To prove the copy holds nothing unique: for each modified file, `git hash-object <file>` and `git cat-file -e <hash>`. A hash already in the object store came from a commit or the index.
- **Remove a copy with `rm -rf` only.** `git worktree remove` on the copy deletes the real worktree's admin data.

## 6. Shell traps

- `find -size -1M` matches only EMPTY files: `find` rounds sizes up to whole MiB, so `-1M` means 0 MiB. Use `-size -1024k`.
- A worktree-isolated agent session refuses `git -C <other repo>`, env-injected git config, and complex loops. Write each step as a script file and run it with one plain command.

## 7. Secrets found on the way

A machine sweep often finds secret files in shared `/tmp` that every account can read (service-account key JSON, bare token files, keys inside logs). Restrict each with `chmod 600` as its owner first (non-destructive). Delete only pure secret copies (a key JSON, or a bare token file of 2 lines or fewer with no spaces) idle 48h or more; leave mixed files (logs, reports, scripts) at `600`. Report service-account identities (`client_email`), never key material. Key rotation is the owner's call: check who can get a shell (local login users, SSH keys in instance and project metadata, OS Login, IAM roles that can add keys) before recommending it.
