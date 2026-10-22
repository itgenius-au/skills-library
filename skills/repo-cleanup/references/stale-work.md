# Stale-work mode: branches and PRs untouched for 30+ days

Use this mode when the ask is about OLD work, not git mess: "branches nobody has touched in a month", "old PRs", "merge or close stale work", "tidy the repo's open PRs". It finds open PRs, remote branches, and local branches with unpushed work, with no activity for `--days` (default 30), sorts each one into a class, and proposes merge or close. Every action still needs a per-item approval and the no-loss audit in SKILL.md Phase 3.

The default repo-cleanup path treats 30 days as a KEEP window for merged branches. This mode is the other side of that window: it only lists items OLDER than `--days`.

## 1. Inventory (read-only)

Run from inside the repo (or pass `--repo`). From a parent folder that holds several repos, run it per child repo from the Phase 0 list.

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/stale-inventory.sh" [--repo <dir>] [--days N] [--all]
```

`CLAUDE_SKILL_DIR` is this skill's folder. If you read this file from disk, put that folder in its place.

- **Default (mine):** your items are actionable. Other people's items show as `report-only`, so you still see them.
- **`--all` (admin):** other people's items become actionable (`other`), but only when `gh api repos/{owner}/{repo}` reports `permissions.admin: true` for you. Without admin they stay `report-only`.
- The script runs `git fetch --prune origin`, then only reads. It never deletes, merges, tags, pushes, or comments.
- If `gh` is missing, not logged in, or offline, it warns and lists branches only.

Output: a header line (`repo`, `base`, `me`, `admin`, `days`, `scope`), a TSV table, then `# fresh items hidden: N`.

| Column | Meaning |
|---|---|
| `KIND` | `pr` (open PR, same repo), `pr-fork` (open PR from a fork), `remote` (remote branch, no PR), `local` (local branch with no remote branch, or with commits not pushed to it; the note says how many) |
| `REF` | branch name, or `#<n>` for a fork PR |
| `PR` | PR number, if any |
| `AUTHOR` | PR author login; for a branch with no PR, the tip commit's author email |
| `AGE_D` | days since the last activity: the later of the tip commit date and the PR's last update (comments and reviews count) |
| `CLASS` | see below |
| `SCOPE` | `mine`, `other` (admin with `--all`), or `report-only` |
| `NOTE` | why the class was chosen |

Ownership of a branch with no PR is a best guess: the tip author email against your `git config user.email`. Check `AUTHOR` before you act on an item the script calls `mine`.

## 2. Classes and the proposed action

| CLASS | Test (against `origin/<default>`) | Propose |
|---|---|---|
| `already-merged` | Tip is an ancestor of the default branch, or merging it changes nothing (squash or cherry-pick already landed) | Archive (3a), then delete the branch and close the PR. |
| `mergeable-now` | Unique work, clean merge | Merge through a PR (see 3b). If the note says the default branch also changed every file it touches, read the diff first: the work may be out of date, so archive and close can be the better call. |
| `needs-rebase` | Unique work that conflicts | Bring the default branch into it and merge, or archive and close. |
| `needs-human` | A `backup/` or `sync-backup/` branch, a long-lived branch (`staging`, `develop`, `production`, `release/*`), a fork PR, a PR to a non-default base, the base of an open PR, PR head gone, no shared history, or `git merge-tree` failed | Report only. Never act on it in this mode. |

Backup branches (`backup/`, `sync-backup/`) and long-lived branches (`staging`, `develop`, `production`, `release/*`) are never merged, closed, or deleted in this mode. Backups are kept, and a long-lived branch is often a deploy branch. The machine-sync branch prune skips backups for the same reason. Another long-lived name (for example `master` in a repo whose default is `main`) still reads as a normal branch: check before you act on it.

A note `checked out in a worktree` means a session may still use it: run the worktree liveness and freshness checks in Phase 0 before you propose anything.

A PR into a non-default base (for example `staging`) is usually dark, flag-gated work parked short of production. It is never "merged" evidence; see the Merged-PR check in SKILL.md.

For other people's items (`other`), the default proposal is **archive and close**. Merge only when the user picks it for that item.

## 3. Act, one item at a time

Present the table, oldest first, grouped by class, with your proposal per row. Then, before any delete or close:

- Ask which of these branches have open sessions on other machines. Git cannot see them.
- Run the Phase 3 audit for that item (Ancestor check, Merged-PR check, Content duplication check).
- Get an explicit approval for THAT item. Never batch.

### 3a. Archive first, every time

Never delete without an archive. Archive EVERY item before you close or delete it, merged or not: a squash-merged branch holds commits the default branch does not have. Never archive-and-delete a backup or long-lived branch.

**Tag names.** One tag per distinct tip: `archive/<YYYY-MM-DD>/<branch>`. When a `local` row's tip differs from the remote tip of the same branch, tag the local tip `archive/<YYYY-MM-DD>/<branch>--local-<short-sha>`. Two rows with the same tip share one tag. If git refuses a name because another tag already uses it as a folder (`archive/<date>/foo` against `archive/<date>/foo/bar`), add `--<short-sha>` to the second one. Never overwrite an existing tag (no `-f`). Set the date once per run (`D=$(date +%F)`) and reuse it, so a run that crosses midnight keeps one set of names.

**Check that a tag push cannot start CI.** GitHub runs the workflow files of the TAGGED commit, not the default branch's. So review the workflows at each tip you will tag. Tips with the same workflow tree share one review:

```bash
git rev-parse -q --verify "<sha>:.github/workflows" || echo "no workflows"   # same tree hash = same review
git ls-tree --name-only "<sha>" .github/workflows/
git show "<sha>:.github/workflows/<file>"
```

Read each file's `on:` block. An archive tag push starts the workflow when: `on: push` (scalar or list form), or a `push:` with no filters; a `push:` with only `paths:` or `paths-ignore:` (path filters are not checked for tag pushes); a `push:` with `tags:` or `tags-ignore:` that `archive/...` matches (in these globs `*` stops at `/`, `**` does not); or a `create` event. A `push:` with `branches:` or `branches-ignore:` and no `tags:` does not run on tags. Ask the user only when an archive tag would start a workflow, or you cannot tell.

**Per item,** tag the tip and push the tag:

```bash
D=$(date +%F)                                    # once per run
SHA=$(git rev-parse "origin/<branch>")          # remote or pr row
SHA=$(git rev-parse "refs/heads/<branch>")       # every local row (local-only work, or commits past the remote branch)
TAG="archive/$D/<branch>"                        # a local tip that differs from the remote tip: "archive/$D/<branch>--local-<short-sha>"
git tag "$TAG" "$SHA"
git push origin "refs/tags/$TAG"
```

**Once per repo, after the tags,** save an offsite copy: one self-contained bundle (the default branch plus every new archive tag) in a private backup bucket. Check the bucket's lifecycle rules first (`gcloud storage buckets describe gs://<bucket> --format='value(lifecycle_config)'`): a rule that deletes objects rules it out. A bucket used for short-lived logs or session transcripts often has such a rule, so it usually fails this check. Ask the user when no suitable bucket is known. Never use a public bucket.

```bash
B="<repo>-branch-archive-$D.bundle"
git bundle create "$B" "origin/<default>" $(git tag -l "archive/$D/*")
T=$(mktemp -d) && git init -q "$T" && git -C "$T" fetch -q "$PWD/$B" 'refs/tags/*:refs/tags/*' && echo "bundle restores on its own"
git -C "$T" tag -l "archive/*"                   # must list every tag you created in this run
gcloud storage cp "$B" "gs://<private-backup-bucket>/backups/branch-archive-bundles/<repo>/"
```

The fetch into an empty repo proves the bundle needs nothing else; `git bundle verify` alone does not. Delete only after the tag push, the restore test (with every created tag listed), and the bundle copy all succeed. Right before each remote delete, check the branch has not moved: `git ls-remote origin refs/heads/<branch>` must still show the archived SHA; if not, archive the new tip first. Record the SHA, the tag, and the bundle path. Restore a branch at any time with `git push origin <sha>:refs/heads/<branch>`, or from the bundle with `git fetch <bundle> "refs/tags/archive/<date>/<branch>"`.

**Run it with the scripts.** `scripts/stale-archive.sh` does the whole of 3a for a list of branches the owner approved, and the branch delete of 3c (with `CLAUDE_SKILL_DIR` set as in section 1):

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/stale-archive.sh" --repo <dir> --plan <plan.tsv> --bucket gs://<private-backup-bucket>/<prefix> [--exec] [--out <record.tsv>] [--allow-triggers]
```

The plan is a TSV of `branch<TAB>sha`, the remote tip the owner approved (blank lines and `#` comments are ignored). Without `--exec` it is a dry run: it prints and records the plan and changes nothing. With `--exec` it follows the steps above in order, and each gate stops the run before any delete:

- a branch whose remote tip is no longer the planned SHA is skipped (`SKIPPED-TIP-MOVED`) and the others go on, including a push that lands just before the delete (the delete is `git push --force-with-lease=<ref>:<sha>`, which the server rejects if the branch moved); the default branch (asked from the server with `git ls-remote --symref origin HEAD`, never the local `origin/HEAD`; the run stops if the server does not answer) and backup or long-lived branches are never touched;
- `scripts/tag_trigger_check.py <repo-dir> <sha> [--tag NAME ...] [--tag-prefix archive/]` runs on every tagged tip with the real tag names that will be pushed (`--tag`, repeatable; without it only made-up samples are tested), and any workflow that is not `SAFE` stops the run before the tag push (`--allow-triggers` overrides a TRIGGERS or UNSURE result, exit 1, once you have read the workflow; any other exit, such as 2, 127 or a signal, means the check gave no verdict and always stops the run). A `**` in a tags filter is trusted only as the last segment (`archive/**`, `**`); anywhere else the file is UNSURE. The checker finds `.github/workflows` from the repo root even when `<repo-dir>` is a subdirectory, and judges each supplied tag on its own;
- the tag push, the empty-repo restore test (every tag listed), and the bucket copy must all succeed; then each branch is re-checked and deleted.

The record has the columns `repo branch sha archive_tag bundle state local_tag local_sha`; its states are `DRY-RUN`, `DELETED-REMOTE`, `DELETED-REMOTE+LOCAL-KEPT` (an older record may also say `DELETED-REMOTE+LOCAL`), `SKIPPED-*`, `DELETE-FAILED`, and `NOT-DELETED-<gate>` after a stop. A copy goes next to the bundle in the bucket. Check the bucket's lifecycle rules yourself first (see above); the script does not.

### 3b. Merge

1. Decide if the repo deploys on merge to the default branch. Check its `CLAUDE.md` and `docs/deployment.md`, and look in `.github/workflows/` for a deploy job on push to the default branch. When unsure, treat it as deployable.
2. **Deployable repo:** do NOT merge. Mark the item "needs build path" and hand it to `dev-quick-build`. A merge there is a production deploy.
3. **Otherwise:** open a PR if there is none (`gh pr create --base <default> --head <branch> --fill`), wait for its checks, then merge it with the repo's usual method. A `needs-rebase` item first gets the default branch merged into it in a temp worktree; resolve, run the repo's gates, and push normally. Never force-push.

### 3c. Close

- **PR:** comment, then close. For someone else's item, the comment names them and the way back:

  ```
  Closing as stale (no activity for <N> days) during a repo tidy-up.
  The work is kept: tag archive/<date>/<branch> at <sha>.
  To restore the branch: git push origin <sha>:refs/heads/<branch>
  ```

  `gh pr close <n> --comment "<text>"`. Add `--delete-branch` only after 3a, and only when the table has no `local` row for that branch: it also force-deletes the local branch, unpushed commits included.
- **Branch:** `git push origin --delete <branch>` (skip it for a `local` row whose branch is not on origin). The local copy is a separate, manual step: `git branch -d -- <branch>` after the remote delete, only when `-d` accepts it (it refuses unmerged commits and a branch checked out in a worktree). If `-d` refuses, keep the local branch: the tag already holds those commits. Never use `-D`.

**Run it with the scripts (delete).** The delete half of 3c is `scripts/stale-archive.sh --exec` (above): it re-checks each tip right before the delete, and the delete is conditional on the archived SHA. It deletes REMOTE branches only and never touches a local branch (merged or not, a symref, or checked out in a worktree). Every deleted branch that also exists locally is recorded as `DELETED-REMOTE+LOCAL-KEPT`, and the run ends with a list, `Local copies kept (delete by hand after checking)`, of the `git branch -d -- <branch>` commands to run yourself. Closing a PR stays a manual `gh pr close`, after the record shows the branch as `DELETED-*`.

## 4. Record

End with the Phase 5 record: for each item, the class, the action, the SHA, the archive tag, and the bundle path. Items you skipped stay listed with the reason.

**Run it with the scripts.** Verify a finished run from a clean clone, and prove that squash-merged work lost nothing:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/stale-archive-verify.sh" --repo <dir> --record <record.tsv> [--restore]
bash "${CLAUDE_SKILL_DIR}/scripts/added-lines-check.sh" --repo <dir> [--base origin/<default>] [--show-missing] <ref>...
```

`stale-archive-verify.sh` reads origin and the bucket itself: for each `DELETED-*` row the branch is gone, the tag (and the local tag, at `local_sha`) is on origin at the recorded SHA, and the bundle exists (`--restore` also fetches those tags from the downloaded bundle into an empty repo and compares the SHAs). It prints OK or FAIL per row and exits 1 on any FAIL, a malformed header or row, an unknown state (a typo such as `DELETD-REMOTE`), a local tag without a full 40-character `local_sha` (7-column records included), or a record that has rows but no `DELETED-*` row. `added-lines-check.sh` is the Phase 3 content check for squash merges, where a blob compare is the wrong test: each ref's added lines (since the fork point) must be on the base, in the same file or anywhere else, and it exits 1 if any are missing or UNVERIFIED (a changed file with no added text line: binary, mode-only, deletion-only) and 2 if git failed (an ERROR line, never `landed`). Only lines with no letter or digit (a lone code fence, `}`, `];`) are ignored; every other line counts, however short (`x=1`). Run `git fetch origin` first. Put the record, the verifier's summary, and the bucket path in the Phase 5 record.
