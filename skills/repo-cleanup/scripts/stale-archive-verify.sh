#!/usr/bin/env bash
# stale-archive-verify.sh - independent check of a stale-archive.sh record.
# For every DELETED-* row: the branch is gone on origin, the archive tag is on origin at the
# recorded SHA (and a recorded local tag at its local SHA), and the bundle object exists in the
# bucket. It reads the remote and the bucket
# itself; it does not trust the record's own claims. Other rows are listed, not checked.
#
# Usage: stale-archive-verify.sh --repo DIR --record RECORD.tsv [--restore]
#   --restore  also download each bundle and fetch the row's tag from it into an empty repo.
# Prints one line per row (OK or FAIL with the reason) and a summary. Exit 1 on any FAIL, on a
# malformed header or row, and when the record has rows but none is a DELETED-* row.
set -euo pipefail

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; }

REPO="" RECORD="" RESTORE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:?--repo needs a directory}"; shift 2 ;;
    --record) RECORD="${2:?--record needs a file}"; shift 2 ;;
    --restore) RESTORE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
if [ -z "$REPO" ] || [ -z "$RECORD" ]; then echo "--repo and --record are required" >&2; usage >&2; exit 2; fi
[ -f "$RECORD" ] || { echo "record not found: $RECORD" >&2; exit 2; }
git -C "$REPO" rev-parse --git-dir >/dev/null

TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
ls_remote() { git -C "$REPO" ls-remote origin "$1" | awk -v r="$1" '$2 == r {print $1}'; }

# The header is read once, as the first line, and its names are checked: a data row whose first
# field happens to be "repo" must not be mistaken for it.
exec 3< "$RECORD"
IFS= read -r header <&3 || header=""
header="${header%$'\r'}"
case "$header" in
  $'repo\tbranch\tsha\tarchive_tag\tbundle\tstate'|$'repo\tbranch\tsha\tarchive_tag\tbundle\tstate\tlocal_tag'|$'repo\tbranch\tsha\tarchive_tag\tbundle\tstate\tlocal_tag\tlocal_sha') ;;
  *) echo "FAIL  bad record header: $header" >&2; exit 1 ;;
esac
cols=$(( $(printf '%s' "$header" | tr -cd '\t' | wc -c) + 1 ))

rows=0 checked=0 ok=0 fail=0 other=0
declare -A DL=()   # bundle -> local copy (downloaded once)
# check_restore <bundle> <tag> <sha>: sets RR to the failure reason, or "" when it restores.
# (Not run in a subshell, so a downloaded bundle is cached for the next row.)
RR=""
check_restore() {
  local bundle="$1" tag="$2" sha="$3" d r
  RR=""
  if [ -z "${DL[$bundle]:-}" ]; then
    d="$TMP/dl$((${#DL[@]} + 1))"; mkdir -p "$d"
    if gcloud storage cp "$bundle" "$d/" >/dev/null 2>&1; then DL[$bundle]="$d/$(basename "$bundle")"; else DL[$bundle]=FAILED; fi
  fi
  if [ "${DL[$bundle]}" = FAILED ]; then RR="bundle download failed"; return 0; fi
  r="$(mktemp -d "$TMP/restore.XXXXXX")"; git init -q "$r"
  if ! git -C "$r" fetch -q "${DL[$bundle]}" "refs/tags/$tag:refs/tags/$tag" 2>/dev/null; then RR="restore: tag $tag not in bundle"
  elif [ "$(git -C "$r" rev-parse "refs/tags/$tag^{commit}")" != "$sha" ]; then RR="restore: tag $tag restores at the wrong SHA"; fi
}
n=0
while IFS= read -r line <&3 || [ -n "$line" ]; do
  line="${line%$'\r'}"
  case "$line" in ''|'#'*) continue ;; esac
  n=$((n + 1)); rows=$((rows + 1))
  # Tabs are counted, not split on: empty fields would collapse and shift the columns.
  if [ $(( $(printf '%s' "$line" | tr -cd '\t' | wc -c) + 1 )) -ne "$cols" ] \
     || [[ "$line" == *$'\t\t'* || "$line" == $'\t'* || "$line" == *$'\t' ]]; then
    fail=$((fail + 1)); echo "FAIL  row $n: malformed (expected $cols non-empty columns): $line"; continue
  fi
  IFS=$'\t' read -r _repo br sha tag bundle state ltag lsha <<< "$line"
  # Only the states stale-archive.sh writes are accepted: a typo must not read as "not a delete".
  case "$state" in
    DELETED-REMOTE|DELETED-REMOTE+LOCAL|DELETED-REMOTE+LOCAL-KEPT) ;;
    DRY-RUN|DELETE-FAILED|SKIPPED-TIP-MOVED|SKIPPED-GONE|SKIPPED-DEFAULT-BRANCH|SKIPPED-PROTECTED|SKIPPED-TAG-NAME-CONFLICT) other=$((other + 1)); echo "SKIP  $br ($state, not a delete)"; continue ;;
    NOT-DELETED-TRIGGER-CHECK-ERROR|NOT-DELETED-TAG-TRIGGER|NOT-DELETED-TAG|NOT-DELETED-TAG-PUSH|NOT-DELETED-BUNDLE|NOT-DELETED-RESTORE|NOT-DELETED-BUNDLE-COPY) other=$((other + 1)); echo "SKIP  $br ($state, not a delete)"; continue ;;
    *) fail=$((fail + 1)); echo "FAIL  $br: unknown state '$state'"; continue ;;
  esac
  # A local tag needs its SHA; a 7-column record has none, so a populated local_tag fails there too.
  if [ -n "${ltag:-}" ] && [ "$ltag" != - ] && ! [[ "${lsha:-}" =~ ^[0-9a-f]{40}$ ]]; then
    fail=$((fail + 1)); echo "FAIL  $br: local_tag is set but local_sha is not a full 40-character SHA"; continue
  fi
  checked=$((checked + 1))
  why=()
  now="$(ls_remote "refs/heads/$br" 2>/dev/null || echo ERR)"
  if [ "$now" = ERR ]; then why+=("cannot read origin")
  elif [ -n "$now" ]; then why+=("branch still on origin at ${now:0:8}"); fi
  t="$(ls_remote "refs/tags/$tag" 2>/dev/null || echo ERR)"
  if [ "$t" = ERR ]; then why+=("cannot read origin tags")
  elif [ -z "$t" ]; then why+=("tag $tag not on origin")
  elif [ "$t" != "$sha" ]; then why+=("tag $tag is at ${t:0:8}, record says ${sha:0:8}"); fi
  have_local=0
  if [ -n "${ltag:-}" ] && [ "$ltag" != - ]; then
    have_local=1
    lt="$(ls_remote "refs/tags/$ltag" 2>/dev/null || echo ERR)"
    if [ "$lt" = ERR ]; then why+=("cannot read origin tags")
    elif [ -z "$lt" ]; then why+=("local tag $ltag not on origin")
    elif [ -n "${lsha:-}" ] && [ "$lsha" != - ] && [ "$lt" != "$lsha" ]; then why+=("local tag $ltag is at ${lt:0:8}, record says ${lsha:0:8}"); fi
  fi
  if ! gcloud storage ls "$bundle" >/dev/null 2>&1; then why+=("bundle $bundle not found")
  elif [ "$RESTORE" -eq 1 ]; then
    check_restore "$bundle" "$tag" "$sha"; [ -z "$RR" ] || why+=("$RR")
    if [ "$have_local" -eq 1 ] && [ -n "${lsha:-}" ] && [ "$lsha" != - ]; then
      check_restore "$bundle" "$ltag" "$lsha"; [ -z "$RR" ] || why+=("$RR")
    fi
  fi
  if [ "${#why[@]}" -eq 0 ]; then ok=$((ok + 1)); echo "OK    $br ($tag)"
  else fail=$((fail + 1)); echo "FAIL  $br: $(IFS=';'; echo "${why[*]}")"; fi
done
exec 3<&-

if [ "$rows" -gt 0 ] && [ "$checked" -eq 0 ]; then
  fail=$((fail + 1)); echo "FAIL  the record has $rows row(s) but none is a DELETED-* row, so nothing was verified"
fi
echo "rows $rows, checked $checked, ok $ok, fail $fail, not-a-delete $other"
[ "$fail" -eq 0 ]
