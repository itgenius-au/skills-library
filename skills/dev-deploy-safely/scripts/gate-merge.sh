#!/usr/bin/env bash
# gate-merge.sh: gate a pull request on green checks, merge ONLY the gated commit, confirm MERGED.
#
# Usage: gate-merge.sh <pr> [--repo owner/name] [--admin] [--delete-branch] [--allow-none] [--allow-red-base]
#   <pr>             PR number, URL or branch (as `gh pr view` takes it)
#   --admin          self-merge as a ruleset bypass actor (your own non-deploy PR on a review-gated repo)
#   --delete-branch  delete the head branch after the merge (not from inside a worktree of that repo)
#   --allow-none     pass a PR with no checks, only when its repo has no CI
#   --allow-red-base merge although the base branch is red (only for the PR that fixes it)
#
# It runs pr-checks-green.sh (waits up to 30 minutes, so run this in the background). A PR with no checks
# passes by itself when its base requires none (see pr-checks-green.sh). When that
# gate stops because the base branch moved and requires up-to-date branches, it runs
# `gh pr update-branch` (a merge, never a force-push) and gates again, up to GATE_MERGE_UPDATES
# times (default 3); each update restarts the required checks. Before the merge it reads the checks of the
# base branch's latest commit and stops if one failed (a red base), unless --allow-red-base. Then
# `gh pr merge --squash --match-head-commit <gated sha>`, so a push after the
# gate makes GitHub refuse the merge, and a final `gh pr view --json state` must print MERGED.
# Prints "MERGED <pr>" on success, "STOP: <why>" otherwise.
# Exit: 0 merged; 1 not merged (red, still behind, red base, merge refused or not confirmed); 4 usage error.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
GATE="${GATE_MERGE_GATE:-$HERE/pr-checks-green.sh}"
GH="${GATE_MERGE_GH:-gh}"

usage() { sed -n '4,9p' "$0" >&2; exit 4; }
pr="" repo_args=() merge_flags=() gate_flags=() allow_red_base=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) [ "$#" -ge 2 ] || usage; repo_args=(--repo "$2"); shift 2 ;;
    --admin) merge_flags+=(--admin); shift ;;
    --delete-branch) merge_flags+=(--delete-branch); shift ;;
    --allow-none) gate_flags+=(--allow-none); shift ;;
    --allow-red-base) allow_red_base=1; shift ;;
    -h | --help) usage ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) [ -z "$pr" ] || usage; pr="$1"; shift ;;
  esac
done
[ -n "$pr" ] || usage

GATE_ERR="$(mktemp)"
trap 'rm -f "$GATE_ERR"' EXIT

gate() {  # gate -> sets SHA and fills GATE_ERR, returns the gate's exit code
  local rc
  SHA=$(bash "$GATE" "${gate_flags[@]}" "$pr" "${repo_args[@]}" 2>"$GATE_ERR"); rc=$?
  cat "$GATE_ERR" >&2
  return "$rc"
}

# After `gh pr update-branch`, GitHub takes a few seconds to recompute the merge state and keeps
# reporting BEHIND (or UNKNOWN) meanwhile; gating at once just sees the old state (seen in practice).
# Wait until it reports anything else, up to about 2 minutes; then the gate decides.
wait_not_behind() {
  local i st
  for i in $(seq 1 "${GATE_MERGE_POLL_TRIES:-24}"); do
    st=$("$GH" pr view "$pr" "${repo_args[@]}" --json mergeStateStatus --jq .mergeStateStatus 2>/dev/null)
    case "$st" in '' | BEHIND | UNKNOWN) sleep "${GATE_MERGE_POLL_S:-5}" ;; *) return 0 ;; esac
  done
  echo "gate-merge: GitHub still reports '${st:-nothing}' after the update; gating anyway (attempt $i)" >&2
}

# A busy base branch can move again while the restarted checks run (a base that takes a merge every
# few minutes can beat a single update more than once).
# So a behind branch is updated up to GATE_MERGE_UPDATES times. Only "behind" earns a retry: a red
# or cancelled check stops at once, on any round.
updates=0
max_updates="${GATE_MERGE_UPDATES:-3}"
until gate; do
  if ! grep -q "requires up-to-date branches" "$GATE_ERR"; then
    if [ "$updates" = 0 ]; then echo "STOP: checks are not green; not merged"
    else echo "STOP: checks are not green after the update; not merged"; fi
    exit 1
  fi
  if [ "$updates" -ge "$max_updates" ]; then
    echo "STOP: the base branch kept moving ($updates updates); not merged. Run this again when main is quieter."
    exit 1
  fi
  updates=$((updates + 1))
  echo "gate-merge: the base branch moved; updating the PR branch ($updates of $max_updates), then gating again" >&2
  "$GH" pr update-branch "$pr" "${repo_args[@]}" >&2 || { echo "STOP: gh pr update-branch failed; not merged"; exit 1; }
  wait_not_behind
done
[ -n "${SHA:-}" ] || { echo "STOP: the gate passed but printed no commit; not merged"; exit 1; }

# A PR can be green against an older base and still land on a base that has since gone red: with
# "require branches up to date" off, nothing else stops it, and a
# red main run alerts nobody but the merger. Red = a check on the base's latest commit that failed,
# timed out or failed to start; a cancelled or running check is untested, not red. The check suites
# are read too: a workflow that fails before it starts a job (an invalid workflow file) leaves no
# failed check run, only a failed suite (an automated review caught this case). An unreadable base is a warning, not a refusal.
base_info=$("$GH" pr view "$pr" "${repo_args[@]}" --json url,baseRefName --jq '.url + " " + .baseRefName' 2>/dev/null)
base_url=${base_info% *} base=${base_info##* }
IFS=/ read -r _ _ _ base_owner base_repo _ <<< "$base_url"
RED_IF='select(.conclusion == "failure" or .conclusion == "timed_out" or .conclusion == "startup_failure")'
red="" red_suites=""
if [ -n "$base_owner" ] && [ -n "$base_repo" ] && [ -n "$base" ] && [ "$base" != "$base_info" ] \
   && red=$("$GH" api --paginate "repos/$base_owner/$base_repo/commits/$base/check-runs?per_page=100" \
       --jq ".check_runs[] | $RED_IF | .name" 2>/dev/null) \
   && red_suites=$("$GH" api --paginate "repos/$base_owner/$base_repo/commits/$base/check-suites?per_page=100" \
       --jq ".check_suites[] | $RED_IF | .app.name" 2>/dev/null); then
  red=$(printf '%s\n%s\n' "$red" "$red_suites" | sed '/^$/d' | sort -u | paste -sd, - | sed 's/,/, /g')
  if [ -n "$red" ] && [ -z "$allow_red_base" ]; then
    echo "STOP: the base branch $base is red ($red); not merged. Fix $base first, or merge the fix with --allow-red-base"
    exit 1
  fi
  [ -z "$red" ] || echo "gate-merge: the base branch $base is red ($red); merging anyway, allowed by --allow-red-base" >&2
else
  echo "gate-merge: WARNING: could not read the checks of the base branch; merging without the red-base check" >&2
fi

# Capture gh's stderr (and still show it) so a policy refusal can get the --admin hint below.
if ! merge_err=$("$GH" pr merge "$pr" "${repo_args[@]}" --squash --match-head-commit "$SHA" "${merge_flags[@]}" 2>&1 >&2); then
  [ -z "$merge_err" ] || printf '%s\n' "$merge_err" >&2
  # The hint goes to stderr, so STOP stays the last stdout line (callers parse it). Only a
  # ruleset refusal gets it: --admin does not fix a conflict or a moved head.
  case " ${merge_flags[*]:-} " in
    *" --admin "*) ;;
    *) case "$merge_err" in
         *"base branch policy prohibits"*)
           echo "HINT: a ruleset rule blocked the merge; gh prints this text for every BLOCKED state. Find" \
                "the rule first: unresolved review threads (resolve them), a required review (wait for it)," \
                "or a rule the author cannot satisfy alone, such as an attribution rule. Only in the last case," \
                "as a verified bypass actor with standing self-merge autonomy on your own non-deploy PR," \
                "re-run with --admin." >&2 ;;
       esac ;;
  esac
  echo "STOP: gh pr merge refused (head moved, review required, or conflict); not merged"
  exit 1
fi
state=$("$GH" pr view "$pr" "${repo_args[@]}" --json state --jq .state 2>/dev/null)
[ "$state" = "MERGED" ] || { echo "STOP: the PR state is '${state:-unknown}', not MERGED"; exit 1; }
echo "MERGED $pr ($SHA)"
