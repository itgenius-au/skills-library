#!/usr/bin/env bash
# stale-inventory.sh - read-only list of stale branches and open PRs for repo-cleanup's
# stale-work mode. Lists open PRs, remote branches, and local branches with unpushed work and no activity
# for --days (default 30), classifies each against the default branch, and prints a TSV.
# It never deletes, merges, tags, pushes, or comments. The only write is `git fetch --prune`,
# which updates remote-tracking refs.
#
# Usage: stale-inventory.sh [--repo DIR] [--days N] [--all]
#   --all   include other people's items as actionable (only when you are a repo admin);
#           without it, or without admin, their items show as report-only.
set -euo pipefail

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }

REPO=. DAYS=30 SCOPE=mine
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:?--repo needs a directory}"; shift 2 ;;
    --days) DAYS="${2:?--days needs a number}"; shift 2 ;;
    --all) SCOPE=all; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
case "$DAYS" in ''|*[!0-9]*) echo "--days must be a whole number, got: $DAYS" >&2; exit 2 ;; esac

cd "$REPO"
git rev-parse --git-dir >/dev/null
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
warn() { echo "WARN: $*" >&2; }

git fetch --quiet --prune origin 2>/dev/null || warn "git fetch failed; using cached remote refs"

BASE="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
BASE="${BASE#origin/}"; BASE="${BASE:-main}"
BASE_REF="refs/remotes/origin/$BASE"
git rev-parse --verify --quiet "$BASE_REF" >/dev/null || { echo "no origin/$BASE ref" >&2; exit 1; }
BASE_TREE="$(git rev-parse "$BASE_REF^{tree}")"
NOW="$(date +%s)"
CUTOFF=$((NOW - DAYS * 86400))
ME_EMAIL="$(git config user.email || true)"

ME_LOGIN="$(gh api user 2>/dev/null | jq -r '.login // empty' 2>/dev/null || true)"
ADMIN=-
if [ "$SCOPE" = all ]; then
  ADMIN="$(gh api 'repos/{owner}/{repo}' 2>/dev/null | jq -r '.permissions.admin // false' 2>/dev/null || true)"
  [ -n "$ADMIN" ] || { ADMIN=unknown; warn "could not read your repo permission; other people's items stay report-only"; }
fi

# Open PRs as TSV: number, head, author, updated (epoch), cross-repo, base.
if gh pr list --state open --limit 500 \
     --json number,headRefName,author,updatedAt,isCrossRepository,baseRefName > "$TMP/prs.json" 2>/dev/null \
   && jq -r '.[] | [.number, .headRefName, (.author.login // "" | if . == "" then "-" else . end), (.updatedAt | fromdateiso8601), .isCrossRepository, .baseRefName] | @tsv' \
        "$TMP/prs.json" > "$TMP/prs.tsv" 2>/dev/null; then :
else
  warn "could not list open PRs (gh missing, not logged in, or offline); branches only"
  : > "$TMP/prs.tsv"
fi
[ "$(wc -l < "$TMP/prs.tsv")" -lt 500 ] || warn "500 or more open PRs; the PR list may be cut off"
[ -n "$ME_LOGIN" ] || warn "could not read your GitHub login; PR ownership shows as other"

git worktree list --porcelain | sed -n 's|^branch refs/heads/||p' > "$TMP/worktrees"

scope_for() { # scope_for <is-mine>
  if [ "${1}" = yes ]; then echo mine
  elif [ "$SCOPE" = all ] && [ "$ADMIN" = true ]; then echo other
  else echo report-only; fi
}

classify() { # classify <tip-ref> -> "class<TAB>note"
  local tip="${1}" mb merged rc=0 note
  mb="$(git merge-base "$BASE_REF" "$tip" 2>/dev/null)" || { printf 'needs-human\tno common history with %s\n' "$BASE"; return; }
  if git merge-base --is-ancestor "$tip" "$BASE_REF"; then printf 'already-merged\tancestor of %s\n' "$BASE"; return; fi
  merged="$(git merge-tree --write-tree "$BASE_REF" "$tip" 2>/dev/null)" || rc=$?
  if [ "$rc" -eq 1 ]; then printf 'needs-rebase\tconflicts with %s\n' "$BASE"; return
  elif [ "$rc" -ne 0 ]; then printf 'needs-human\tgit merge-tree failed (exit %s)\n' "$rc"; return; fi
  if [ "$(printf '%s\n' "$merged" | head -1)" = "$BASE_TREE" ]; then
    printf 'already-merged\tcontent already on %s (squash or cherry-pick)\n' "$BASE"; return
  fi
  note="clean merge into $BASE"
  git diff --name-only "$mb" "$tip" | sort > "$TMP/bf"
  git diff --name-only "$mb" "$BASE_REF" | sort > "$TMP/mf"
  if [ -z "$(comm -23 "$TMP/bf" "$TMP/mf")" ]; then
    note="$note; $BASE also changed every file it touches since the fork, read the diff"
  fi
  printf 'mergeable-now\t%s\n' "$note"
}

FRESH=0
: > "$TMP/rows"
# emit <kind> <ref-label> <branch> <tip-ref or empty> <pr-row or empty> [extra note]
emit() {
  local kind="${1}" label="${2}" branch="${3}" tip="${4}" pr="${5}" extra="${6:-}"
  local pr_num="" pr_author="" pr_updated=0 pr_cross="" pr_base="" act=0 tip_ct=0 email="" author mine cls
  if [ -n "$pr" ]; then IFS=$'\t' read -r pr_num _ pr_author pr_updated pr_cross pr_base <<< "$pr"; fi
  if [ -n "$tip" ]; then
    tip_ct="$(git log -1 --format=%ct "$tip")"; email="$(git log -1 --format=%ae "$tip")"
  fi
  act=$tip_ct; [ "${pr_updated:-0}" -gt "$act" ] && act=$pr_updated
  if [ "$act" -gt "$CUTOFF" ]; then FRESH=$((FRESH + 1)); return; fi
  if [ -n "$pr" ]; then author="$pr_author"; { [ -n "$ME_LOGIN" ] && [ "$(lc "$pr_author")" = "$(lc "$ME_LOGIN")" ]; } && mine=yes || mine=no
  else author="$email"; is_my_email "$email" && mine=yes || mine=no; fi
  if [ -n "$branch" ] && is_backup "$branch"; then cls=$'needs-human\tbackup branch, keep'
  elif [ -n "$branch" ] && is_long_lived "$branch"; then cls=$'needs-human\tlong-lived branch, keep'
  elif [ "$pr_cross" = true ]; then cls=$'needs-human\tPR from a fork'
  elif [ -n "$pr" ] && [ "$pr_base" != "$BASE" ]; then cls="needs-human"$'\t'"PR targets $pr_base, not $BASE"
  elif [ -z "$tip" ]; then cls=$'needs-human\tPR head branch is gone'
  elif [ -n "$branch" ] && awk -F'\t' -v b="$branch" '$6 == b' "$TMP/prs.tsv" | grep -q .; then
    cls=$'needs-human\tbase of an open PR (a long-lived branch)'
  else cls="$(classify "$tip")"; fi
  [ -n "$extra" ] && cls="$cls; $extra"
  if [ -n "$branch" ] && grep -qxF "$branch" "$TMP/worktrees"; then
    cls="$cls; checked out in a worktree, run the worktree checks first"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$kind" "$label" "$pr_num" "$author" \
    $(( (NOW - act) / 86400 )) "${cls%%$'\t'*}" "$(scope_for "$mine")" "${cls#*$'\t'}" >> "$TMP/rows"
}

is_long_lived() { case "${1}" in staging|develop|production|release/*) return 0 ;; esac; return 1; }
lc() { printf '%s' "${1}" | tr '[:upper:]' '[:lower:]'; }
# Mine: my git email (any case), or the GitHub no-reply address of my gh login.
is_my_email() {
  local e me; e="$(lc "${1}")"
  { [ -n "$ME_EMAIL" ] && [ "$e" = "$(lc "$ME_EMAIL")" ]; } && return 0
  [ -n "$ME_LOGIN" ] || return 1
  me="$(lc "$ME_LOGIN")@users.noreply.github.com"
  case "$e" in "$me"|*"+$me") return 0 ;; esac
  return 1
}
is_backup() { case "${1}" in backup/*|sync-backup/*) return 0 ;; esac; return 1; }

pr_for() { awk -F'\t' -v b="${1}" '$2 == b && $5 == "false"' "$TMP/prs.tsv" | head -1; }

# Remote branches (with or without a PR).
git for-each-ref --format='%(refname:lstrip=3)' refs/remotes/origin > "$TMP/remote"
while IFS= read -r b; do
  [ "$b" = HEAD ] || [ "$b" = "$BASE" ] && continue
  pr="$(pr_for "$b")"
  if [ -n "$pr" ]; then emit pr "$b" "$b" "refs/remotes/origin/$b" "$pr"
  else emit remote "$b" "$b" "refs/remotes/origin/$b" ""; fi
done < "$TMP/remote"

# Same-repo PRs whose head branch is not on origin.
while IFS= read -r pr; do
  b="$(printf '%s' "$pr" | cut -f2)"
  grep -qxF "$b" "$TMP/remote" || emit pr "$b" "$b" "" "$pr"
done < <(awk -F'\t' '$5 == "false"' "$TMP/prs.tsv")

# Fork PRs: their head lives in another repo.
while IFS= read -r pr; do
  emit pr-fork "#$(printf '%s' "$pr" | cut -f1)" "" "" "$pr"
done < <(awk -F'\t' '$5 == "true"' "$TMP/prs.tsv")

# Local branches: local-only work, or commits not pushed to the same-named remote branch.
while IFS= read -r b; do
  [ "$b" = "$BASE" ] && continue
  if grep -qxF "$b" "$TMP/remote"; then
    n="$(git rev-list --count "refs/remotes/origin/$b..refs/heads/$b")"
    [ "$n" -gt 0 ] && emit local "$b" "$b" "refs/heads/$b" "" "$n commit(s) not on origin/$b"
  else
    emit local "$b" "$b" "refs/heads/$b" ""
  fi
done < <(git for-each-ref --format='%(refname:lstrip=2)' refs/heads)

echo "# repo=$(basename "$(git rev-parse --show-toplevel)") base=$BASE me=${ME_LOGIN:-?} admin=$ADMIN days=$DAYS scope=$SCOPE"
printf 'KIND\tREF\tPR\tAUTHOR\tAGE_D\tCLASS\tSCOPE\tNOTE\n'
sort -t$'\t' -k5,5nr "$TMP/rows"
echo "# fresh items hidden: $FRESH"
