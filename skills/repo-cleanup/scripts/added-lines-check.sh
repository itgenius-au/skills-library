#!/usr/bin/env bash
# added-lines-check.sh - no-loss check for squash-merged work: is every line a branch ADDED
# (since its fork point) on the base branch now? After a squash merge the branch commits are
# not ancestors and the blobs differ, so a blob compare is the wrong test; the lines are what
# matter. Read-only: it never fetches, so run `git fetch origin` first.
#
# Usage: added-lines-check.sh --repo DIR [--base origin/<default>] [--show-missing] <ref>...
#   A line counts as present when, trimmed, it equals a whole line of the same file on the base,
#   else a whole line of any file on the base (it may have moved). Blank lines are ignored.
#   A file deleted on the base has every line counted as missing unless found elsewhere.
#   Lines with no letter or digit at all (a lone ``` fence, "}", "});", "];") are ignored: they
#   match anywhere, so they prove nothing. Every other line counts, however short ("x=1").
#   A changed file with no added text line (binary, mode-only, deletion-only, the old side of a
#   rename) cannot be checked: the ref gets verdict UNVERIFIED (exit 1), never landed.
#   --show-missing  print up to 20 missing lines per ref, and the UNVERIFIED files, with names.
# Exit 0 when every ref is landed, 1 when any ref is MISSING or UNVERIFIED, 2 when git failed for any
# ref (printed as ERROR, never as landed).
set -euo pipefail

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; }

REPO=. BASE="" SHOW=0 REFS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:?--repo needs a directory}"; shift 2 ;;
    --base) BASE="${2:?--base needs a ref}"; shift 2 ;;
    --show-missing) SHOW=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    *) REFS+=("$1"); shift ;;
  esac
done
[ "${#REFS[@]}" -gt 0 ] || { echo "give at least one ref" >&2; usage >&2; exit 2; }

# Work from the repo root: pathspecs below are root-relative, so a subdirectory --repo must not
# change any verdict.
TOP="$(git -C "$REPO" rev-parse --show-toplevel)" || { echo "not a git work tree: $REPO" >&2; exit 2; }
cd "$TOP"
if [ -z "$BASE" ]; then
  BASE="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  if [ -z "$BASE" ] || ! git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null; then
    BASE=""
    for c in origin/main origin/master; do
      git rev-parse --verify --quiet "$c^{commit}" >/dev/null && { BASE="$c"; break; }
    done
  fi
fi
if [ -z "$BASE" ] || ! git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null; then
  echo "cannot resolve the base branch; pass --base" >&2; exit 1
fi

T="$(mktemp -d)"
trap 'rm -rf -- "$T"' EXIT
trim() { sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }

# Every git call below is checked explicitly: a failed diff or grep must never read as "no
# added lines" or "no match", which would report landed. grep exit 1 (no match) is normal;
# 2 or more is an error.
err() { echo "$ref: ERROR $*"; }

# check_ref <ref>: prints one verdict line; returns 0 landed, 1 missing, 2 error.
check_ref() {
  local ref="$1" mb total=0 miss=0 unv=0 f n m st line found
  git rev-parse --verify --quiet "$ref^{commit}" >/dev/null || { err "cannot resolve ref"; return 2; }
  mb="$(git merge-base "$BASE" "$ref" 2>/dev/null)" || { err "no common history with $BASE"; return 2; }
  git diff --name-only -z --no-renames "$mb" "$ref" > "$T/files" || { err "git diff --name-only failed"; return 2; }
  : > "$T/missing"; : > "$T/unverified"
  while IFS= read -r -d '' f; do
    git -c core.quotepath=off diff -U0 --no-color --no-renames "$mb" "$ref" -- "$f" > "$T/diff" || { err "git diff failed for $f"; return 2; }
    # Only lines inside hunks are content, so a "+++" content line is not mistaken for a header.
    awk '/^@@/{h=1; next} h && /^\+/{print substr($0, 2)}' "$T/diff" > "$T/raw" || { err "reading the diff of $f failed"; return 2; }
    # A change with no added text line (binary, mode-only, deletion-only, the old side of a
    # rename) says nothing about what landed, so it is UNVERIFIED, never quietly fine.
    if [ ! -s "$T/raw" ]; then unv=$((unv + 1)); printf '%s\n' "$f" >> "$T/unverified"; continue; fi
    st=0
    trim < "$T/raw" | grep -vE '^[[:punct:][:space:]]*$' | sort -u > "$T/added" || st=$?
    [ "$st" -le 1 ] || { err "filtering the added lines of $f failed"; return 2; }
    [ -s "$T/added" ] || continue
    # Same file on the base? "absent" (empty ls-tree output) is not the same as "git failed".
    git ls-tree -z --name-only "$BASE" -- "$f" > "$T/lstree" || { err "git ls-tree failed for $f"; return 2; }
    : > "$T/now"
    if [ -s "$T/lstree" ]; then
      git show "$BASE:$f" > "$T/basefile" || { err "git show $BASE:$f failed"; return 2; }
      trim < "$T/basefile" | sort -u > "$T/now" || { err "reading $f on $BASE failed"; return 2; }
    fi
    st=0; grep -vxFf "$T/now" "$T/added" > "$T/cand" || st=$?
    [ "$st" -le 1 ] || { err "grep failed for $f"; return 2; }
    # Not in the same file: look for the line anywhere on the base (moved or split files).
    : > "$T/gone"
    while IFS= read -r line; do
      st=0; git grep -h -I --no-color -F -e "$line" "$BASE" -- > "$T/gg" 2>/dev/null || st=$?
      found=0
      if [ "$st" -eq 0 ]; then
        trim < "$T/gg" > "$T/ggt"
        st=0; grep -qxF -- "$line" "$T/ggt" || st=$?
        [ "$st" -le 1 ] || { err "grep failed for $f"; return 2; }
        [ "$st" -ne 0 ] || found=1
      elif [ "$st" -ne 1 ]; then
        err "git grep failed on $BASE"; return 2
      fi
      [ "$found" -eq 1 ] || printf '%s\n' "$line" >> "$T/gone"
    done < "$T/cand"
    n=$(wc -l < "$T/added"); m=$(wc -l < "$T/gone")
    total=$((total + n)); miss=$((miss + m))
    [ "$m" -eq 0 ] || awk -v f="$f" '{print f "\t" $0}' "$T/gone" >> "$T/missing"
  done < "$T/files"
  if [ "$miss" -eq 0 ] && [ "$unv" -eq 0 ]; then echo "$ref: added $total, missing 0, verdict landed"; return 0; fi
  if [ "$miss" -gt 0 ]; then verdict=MISSING; else verdict=UNVERIFIED; fi
  if [ "$unv" -gt 0 ]; then echo "$ref: added $total, missing $miss, unverified $unv, verdict $verdict"
  else echo "$ref: added $total, missing $miss, verdict $verdict"; fi
  if [ "$SHOW" -eq 1 ]; then
    head -20 "$T/missing" | while IFS=$'\t' read -r f line; do
      printf '  MISSING in %s: %s\n' "$f" "$(printf '%s' "$line" | cut -c1-120)"
    done
    [ "$miss" -le 20 ] || echo "  ... and $((miss - 20)) more"
    head -20 "$T/unverified" | while IFS= read -r f; do
      printf '  UNVERIFIED %s (no added text line: binary, mode-only, deletion-only or renamed)\n' "$f"
    done
  fi
  return 1
}

rc=0
for ref in "${REFS[@]}"; do
  st=0; check_ref "$ref" || st=$?
  if [ "$st" -gt "$rc" ]; then rc="$st"; fi
done
exit "$rc"
