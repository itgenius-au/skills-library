#!/usr/bin/env bash
# stale-archive.sh - archive-then-delete runner for repo-cleanup's stale-work mode
# (references/stale-work.md, 3a and 3c). For each approved branch it tags the tip, pushes the
# tags, saves ONE restore-tested bundle to a private bucket, and only then deletes the branch.
#
# Usage: stale-archive.sh --repo DIR --plan FILE --bucket gs://BUCKET/PREFIX [--exec]
#                         [--out RECORD.tsv] [--allow-triggers]
#   --plan    TSV lines: branch<TAB>sha, the remote tip the owner approved. Blank lines and
#             # comments are ignored.
#   --exec    do it. Without it this is a DRY RUN: it prints and records the plan and changes
#             nothing (only `git fetch --prune`, which updates remote-tracking refs).
#   --out     record TSV (default ./branch-archive-record-<date>.tsv). On --exec it is also
#             copied next to the bundle in the bucket.
#   --allow-triggers  go on even when an archive tag push would start a workflow.
# Record columns: repo branch sha archive_tag bundle state local_tag local_sha
# It deletes REMOTE branches only; local copies are kept and listed at the end.
# Exit 0 only when every planned branch is deleted or skipped with a reason; 1 on any gate
# failure (nothing is deleted after a failed gate).
set -euo pipefail

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; }

REPO="" PLAN="" BUCKET="" EXEC=0 OUT="" ALLOW_TRIG=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:?--repo needs a directory}"; shift 2 ;;
    --plan) PLAN="${2:?--plan needs a file}"; shift 2 ;;
    --bucket) BUCKET="${2:?--bucket needs gs://BUCKET/PREFIX}"; shift 2 ;;
    --out) OUT="${2:?--out needs a file}"; shift 2 ;;
    --exec) EXEC=1; shift ;;
    --allow-triggers) ALLOW_TRIG=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
if [ -z "$REPO" ] || [ -z "$PLAN" ] || [ -z "$BUCKET" ]; then
  echo "--repo, --plan and --bucket are required" >&2; usage >&2; exit 2
fi
case "$BUCKET" in gs://?*) ;; *) echo "--bucket must look like gs://BUCKET/PREFIX" >&2; exit 2 ;; esac
BUCKET="${BUCKET%/}"
[ -f "$PLAN" ] || { echo "plan file not found: $PLAN" >&2; exit 2; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PLAN="$(cd "$(dirname "$PLAN")" && pwd)/$(basename "$PLAN")"

D="$(date +%F)"   # once per run, so a run that crosses midnight keeps one set of names
OUT="${OUT:-$PWD/branch-archive-record-$D.tsv}"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac

cd "$REPO"
git rev-parse --git-dir >/dev/null
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
URL="$(git remote get-url origin)"
NAME="$(basename "${URL%/}")"; NAME="${NAME%.git}"

ls_remote() { git ls-remote origin "$1" | awk -v r="$1" '$2 == r {print $1}'; }
short() { printf '%s' "${1:0:8}"; }

git fetch --quiet --prune origin

# Default branch: ask the SERVER (the local origin/HEAD can be stale, and a stale answer here
# would let the real default branch be deleted). If the server does not answer, stop.
SRVHEAD="$(git ls-remote --symref origin HEAD | awk -F'\t' '$2 == "HEAD" && $1 ~ /^ref: refs\/heads\// {sub(/^ref: refs\/heads\//, "", $1); print $1; exit}')" \
  || { echo "cannot ask origin for its default branch" >&2; exit 1; }
[ -n "$SRVHEAD" ] || { echo "origin did not report a default branch (git ls-remote --symref origin HEAD); not guessing" >&2; exit 1; }
DEF="origin/$SRVHEAD"
git rev-parse --verify --quiet "$DEF^{commit}" >/dev/null || { echo "the server default branch $SRVHEAD is not in the local clone after fetch" >&2; exit 1; }

# Records. ROWS holds finished rows; ITEMS holds branches that will be archived.
ROWS=()
row() { # row <branch> <sha> <tag> <bundle> <state> [local-tag [local-sha]]
  ROWS+=("$(printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s' "$NAME" "$1" "$2" "$3" "$4" "$5" "${6:--}" "${7:--}")")
}
write_record() {
  { printf 'repo\tbranch\tsha\tarchive_tag\tbundle\tstate\tlocal_tag\tlocal_sha\n'
    [ "${#ROWS[@]}" -eq 0 ] || printf '%s\n' "${ROWS[@]}"; } > "$OUT"
}
# A failed gate: nothing is deleted. Rows still waiting for their delete are recorded as such.
stop() { # stop <gate-name> <message>
  local i
  for i in "${!IT_BR[@]}"; do row "${IT_BR[$i]}" "${IT_SHA[$i]}" "${IT_TAG[$i]}" - "NOT-DELETED-$1" "${IT_LTAG[$i]}" "${IT_LTAG[$i]:+${IT_LSHA[$i]}}"; done
  write_record
  echo "STOP: $2 (nothing deleted; record: $OUT)" >&2
  exit 1
}

# All tags known locally or on origin, so a name is never reused for another SHA.
declare -A KNOWN=()
while read -r sha ref; do KNOWN["${ref#refs/tags/}"]="$sha"; done < <(git for-each-ref --format='%(objectname) %(refname)' refs/tags)
while read -r sha ref; do
  case "$ref" in *'^{}') continue ;; esac
  KNOWN["${ref#refs/tags/}"]="$sha"
done < <(git ls-remote --tags origin 'refs/tags/archive/*')

# conflicts <tag> <sha>: 1 if the name is taken by another SHA or git would refuse it
# (an existing tag is a folder of it, or a parent folder of it is a tag).
conflicts() {
  local t="$1" sha="$2" k p
  [ -z "${KNOWN[$t]:-}" ] || [ "${KNOWN[$t]}" = "$sha" ] || return 0
  for k in "${!KNOWN[@]}"; do
    case "$k" in "$t"/*) return 0 ;; esac
  done
  p="$t"
  while [ "${p%/*}" != "$p" ]; do
    p="${p%/*}"
    [ -z "${KNOWN[$p]:-}" ] || return 0
  done
  return 1
}
# pick_tag <desired> <sha> -> prints a tag name, or nothing when even the suffixed name conflicts
pick_tag() {
  local t="$1" sha="$2"
  conflicts "$t" "$sha" || { printf '%s' "$t"; return 0; }
  t="$t--$(short "$sha")"
  conflicts "$t" "$sha" || { printf '%s' "$t"; return 0; }
  return 1
}

# --- 1. plan: re-check every remote tip, pick tag names ------------------------
IT_BR=() IT_SHA=() IT_TAG=() IT_LSHA=() IT_LTAG=()
TAGS=()                       # every tag this run needs, name only, unique
declare -A TAGSHA=()          # tag -> sha
declare -A TIPTAG=()          # sha -> tag: identical tips share one tag
# tag_for <desired-tag> <sha>: prints the tag for this tip (shared if already tagged this run);
# returns 1 when even the suffixed name is unusable. Does not register anything.
tag_for() {
  [ -z "${TIPTAG[$2]:-}" ] || { printf '%s' "${TIPTAG[$2]}"; return 0; }
  pick_tag "$1" "$2"
}
register() { # register <tag> <sha>
  [ -n "${TAGSHA[$1]:-}" ] || { TAGSHA["$1"]="$2"; TAGS+=("$1"); KNOWN["$1"]="$2"; }
  TIPTAG["$2"]="$1"
}

while IFS=$'\t' read -r br sha _rest || [ -n "${br:-}" ]; do
  br="${br%$'\r'}"
  case "$br" in ''|'#'*) continue ;; esac
  [[ "$br" =~ ^[[:space:]]*$ ]] && continue
  sha="${sha%$'\r'}"
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "plan line for '$br' has no full 40-character SHA" >&2; exit 2; }
  case "$br" in
    "${DEF#origin/}") row "$br" "$sha" - - SKIPPED-DEFAULT-BRANCH; continue ;;
    backup/*|sync-backup/*|staging|develop|production|release/*) row "$br" "$sha" - - SKIPPED-PROTECTED; continue ;;
  esac
  now="$(ls_remote "refs/heads/$br")"
  if [ -z "$now" ]; then row "$br" "$sha" - - SKIPPED-GONE; continue; fi
  if [ "$now" != "$sha" ]; then row "$br" "$sha" - - SKIPPED-TIP-MOVED; echo "tip moved: $br is $now, plan has $sha" >&2; continue; fi
  git cat-file -e "$sha^{commit}" 2>/dev/null || { echo "commit $sha for $br is not in the local clone after fetch" >&2; exit 1; }
  tag="$(tag_for "archive/$D/$br" "$sha")" || { row "$br" "$sha" - - SKIPPED-TAG-NAME-CONFLICT; continue; }
  lsha="$(git rev-parse -q --verify "refs/heads/$br^{commit}" || true)" ltag=""
  if [ -n "$lsha" ] && [ "$lsha" != "$sha" ]; then
    # Reserve the main tag first so the local name cannot collide with it.
    register "$tag" "$sha"
    ltag="$(tag_for "archive/$D/$br--local-$(short "$lsha")" "$lsha")" || { row "$br" "$sha" - - SKIPPED-TAG-NAME-CONFLICT; continue; }
    register "$ltag" "$lsha"
  else
    register "$tag" "$sha"
  fi
  IT_BR+=("$br") IT_SHA+=("$sha") IT_TAG+=("$tag") IT_LSHA+=("$lsha") IT_LTAG+=("$ltag")
done < "$PLAN"

echo "repo=$NAME default=$DEF date=$D mode=$([ "$EXEC" = 1 ] && echo EXEC || echo DRY-RUN) planned=${#IT_BR[@]}"
for i in "${!IT_BR[@]}"; do
  echo "plan: ${IT_BR[$i]} ${IT_SHA[$i]} -> ${IT_TAG[$i]}${IT_LTAG[$i]:+ (+ local ${IT_LTAG[$i]})}"
done

# --- 2. gate: no archive tag push may start CI --------------------------------
if [ "${#TAGS[@]}" -gt 0 ]; then
  declare -A SEEN=()
  for t in "${TAGS[@]}"; do
    s="${TAGSHA[$t]}"
    [ -z "${SEEN[$s]:-}" ] || continue
    SEEN[$s]=1
    # Judge the tag names that will really be pushed for this tip, not a made-up sample.
    targs=(); for u in "${TAGS[@]}"; do [ "${TAGSHA[$u]}" = "$s" ] && targs+=(--tag "$u"); done
    rc=0; out="$("${PYTHON:-python3}" -I "$HERE/tag_trigger_check.py" "$PWD" "$s" "${targs[@]}" 2>&1)" || rc=$?
    # Only exit 0 (all SAFE) and 1 (TRIGGERS or UNSURE) are verdicts. Anything else (2, 127, a
    # signal) means the check did not run properly, and --allow-triggers must not override that.
    if [ "$rc" -gt 1 ]; then stop TRIGGER-CHECK-ERROR "tag_trigger_check.py did not give a verdict for $s (exit $rc): $out"; fi
    if [ "$rc" -ne 0 ]; then
      printf '%s\n' "$out" | sed "s/^/  trigger $(short "$s"): /" >&2
      [ "$ALLOW_TRIG" -eq 1 ] || stop TAG-TRIGGER "an archive tag at $(short "$s") would start a workflow (or cannot be judged); review it, or pass --allow-triggers"
      echo "WARN: continuing despite tag triggers at $(short "$s") (--allow-triggers)" >&2
    fi
  done
fi

# --- dry run ends here ---------------------------------------------------------
if [ "$EXEC" -ne 1 ]; then
  for i in "${!IT_BR[@]}"; do row "${IT_BR[$i]}" "${IT_SHA[$i]}" "${IT_TAG[$i]}" - DRY-RUN "${IT_LTAG[$i]}" "${IT_LTAG[$i]:+${IT_LSHA[$i]}}"; done
  write_record
  echo "dry run: nothing changed. record: $OUT. Re-run with --exec to archive and delete."
  exit 0
fi
if [ "${#IT_BR[@]}" -eq 0 ]; then write_record; echo "nothing to archive. record: $OUT"; exit 0; fi

# --- 3. tag and push the tags --------------------------------------------------
REFS=()
for t in "${TAGS[@]}"; do
  git rev-parse -q --verify "refs/tags/$t" >/dev/null || git tag "$t" "${TAGSHA[$t]}" || stop TAG "could not create tag $t"
  [ "$(git rev-parse "refs/tags/$t^{commit}")" = "${TAGSHA[$t]}" ] || stop TAG "tag $t exists at another SHA"
  REFS+=("refs/tags/$t")
done
git push --quiet origin "${REFS[@]}" || stop TAG-PUSH "tag push failed"
for t in "${TAGS[@]}"; do
  [ "$(ls_remote "refs/tags/$t")" = "${TAGSHA[$t]}" ] || stop TAG-PUSH "tag $t is not on origin at the right SHA"
done

# --- 4. one bundle, restore test, bucket copy ----------------------------------
B="$TMP/$NAME-branch-archive-$D.bundle"
git bundle create "$B" "$DEF" "${REFS[@]}" >/dev/null 2>&1 || stop BUNDLE "git bundle create failed"
R="$TMP/restore"; git init -q "$R" || stop RESTORE "could not create the restore repo"
# An empty repo proves the bundle needs nothing else; `git bundle verify` alone does not.
git -C "$R" fetch -q "$B" 'refs/tags/*:refs/tags/*' || stop RESTORE "restore test: fetch from the bundle failed"
want="$(printf '%s\n' "${TAGS[@]}" | sort -u)"; got="$(git -C "$R" tag -l 'archive/*' | sort -u)"
[ "$want" = "$got" ] || stop RESTORE "restore test: the bundle does not hold every tag created in this run"
for t in "${TAGS[@]}"; do
  [ "$(git -C "$R" rev-parse "refs/tags/$t^{commit}")" = "${TAGSHA[$t]}" ] || stop RESTORE "restore test: tag $t restores at the wrong SHA"
done
# Never overwrite an earlier bundle: a second run on the same day gets a numbered name.
BN="$(basename "$B")"; n=1
while gcloud storage ls "$BUCKET/$NAME/$BN" >/dev/null 2>&1; do n=$((n + 1)); BN="${NAME}-branch-archive-$D-$n.bundle"; done
[ "$BN" = "$(basename "$B")" ] || { mv "$B" "$TMP/$BN"; B="$TMP/$BN"; }
DEST="$BUCKET/$NAME/$BN"
gcloud storage cp "$B" "$DEST" >/dev/null || stop BUNDLE-COPY "copy to $DEST failed"
gcloud storage ls "$DEST" >/dev/null || stop BUNDLE-COPY "cannot see $DEST after the copy"
echo "bundle: $DEST"

# --- 5. deletes: only now ------------------------------------------------------
rc=0; KEPT=()
for i in "${!IT_BR[@]}"; do
  br="${IT_BR[$i]}" sha="${IT_SHA[$i]}" lsha="${IT_LSHA[$i]}"
  LTAGV="${IT_LTAG[$i]}" LSHAV="${IT_LTAG[$i]:+$lsha}"
  # The branch may have moved since the plan: a moved tip was not archived, so keep it.
  if [ "$(ls_remote "refs/heads/$br")" != "$sha" ]; then row "$br" "$sha" "${IT_TAG[$i]}" "$DEST" SKIPPED-TIP-MOVED "$LTAGV" "$LSHAV"; continue; fi
  # The delete itself is conditional on the archived SHA (the server compares it), so a push
  # that lands between the check above and this line cannot lose a commit.
  if ! git push --quiet --force-with-lease="refs/heads/$br:$sha" origin ":refs/heads/$br" 2>/dev/null; then
    if [ "$(ls_remote "refs/heads/$br")" != "$sha" ]; then row "$br" "$sha" "${IT_TAG[$i]}" "$DEST" SKIPPED-TIP-MOVED "$LTAGV" "$LSHAV"
    else row "$br" "$sha" "${IT_TAG[$i]}" "$DEST" DELETE-FAILED "$LTAGV" "$LSHAV"; rc=1; fi
    continue
  fi
  # This script deletes REMOTE branches only. A local copy (merged or not, a symref, or checked
  # out in a worktree) is never touched: it is listed at the end for a human to remove.
  state=DELETED-REMOTE
  if [ -n "$lsha" ]; then state=DELETED-REMOTE+LOCAL-KEPT; KEPT+=("$br"); fi
  row "$br" "$sha" "${IT_TAG[$i]}" "$DEST" "$state" "$LTAGV" "$LSHAV"
done
write_record
gcloud storage cp "$OUT" "${DEST%.bundle}.record.tsv" >/dev/null || { echo "WARN: could not copy the record to the bucket" >&2; rc=1; }
printf '%s\n' "${ROWS[@]}" | cut -f2,5,6
echo "record: $OUT"
if [ "${#KEPT[@]}" -gt 0 ]; then
  echo "Local copies kept (delete by hand after checking):"
  for b in "${KEPT[@]}"; do printf '  git branch -d -- %q\n' "$b"; done
fi
exit "$rc"
