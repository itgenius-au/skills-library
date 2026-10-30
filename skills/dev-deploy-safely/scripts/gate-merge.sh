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
# GATE_MERGE_EXPECT_HEAD=<full 40-character sha>: stop, unmerged, when the gated head is not that commit
#   (a short sha exits 4; take it from `gh pr view <pr> --json headRefOid --jq .headRefOid`).
# Exit: 0 merged; 1 not merged (red, still behind, red base, merge refused or not confirmed); 4 usage error;
#   5 not merged because GitHub could not be reached (the gate's NETWORK stop, or a network error
#   on the merge or the MERGED read-back that retries did not clear). Exit 5 never means a red check:
#   run the same command again when the network is back.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
GATE="${GATE_MERGE_GATE:-$HERE/pr-checks-green.sh}"
GH="${GATE_MERGE_GH:-gh}"
NET_TRIES="${GATE_MERGE_NET_TRIES:-5}"
NET_SLEEP="${GATE_MERGE_NET_SLEEP:-15}"
NET_RE='i/o timeout|TLS handshake timeout|connection reset|connection refused|no such host|unexpected EOF|error connecting to|check your internet connection|context deadline exceeded|Client.Timeout exceeded|HTTP 50[234]'

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
if [ -n "${GATE_MERGE_EXPECT_HEAD:-}" ] && ! [[ "$GATE_MERGE_EXPECT_HEAD" =~ ^[0-9a-f]{40}$ ]]; then
  echo "STOP: GATE_MERGE_EXPECT_HEAD must be a full 40-character lower-case SHA (gh pr view --json headRefOid)"
  exit 4
fi

GATE_ERR="$(mktemp)"
NET_ERR="$(mktemp)"
trap 'rm -f "$GATE_ERR" "$NET_ERR"' EXIT

# gh_read ARGS...: run a read-only gh call and print its stdout. A network error is retried
# NET_TRIES times, NET_SLEEP seconds apart. Returns 0, 1 (any other error) or 5 (a network error
# on every try). Never used for a write.
gh_read() {
  local n=1 out
  while :; do
    if out=$("$GH" "$@" 2>"$NET_ERR"); then printf '%s\n' "$out"; return 0; fi
    grep -qE "$NET_RE" "$NET_ERR" || return 1
    [ "$n" -lt "$NET_TRIES" ] || return 5
    echo "gate-merge: network error on gh $1 $2, try $n of $NET_TRIES; again in ${NET_SLEEP}s" >&2
    n=$((n + 1))
    sleep "$NET_SLEEP"
  done
}

# net_stop WHAT: a read the merge depends on could not reach GitHub. Nothing was merged.
net_stop() {
  echo "STOP: NETWORK: GitHub could not be reached while $1 ($(head -c 200 "$NET_ERR" | tr '\n' ' ')); not merged. Run this again."
  exit 5
}

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
  gate_rc=$?
  if [ "$gate_rc" -eq 5 ] || grep -q "^STOP: NETWORK" "$GATE_ERR"; then
    echo "STOP: NETWORK: GitHub could not be reached while gating; checks not read; not merged. Run this again."
    exit 5
  fi
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
  if ! ub_err=$("$GH" pr update-branch "$pr" "${repo_args[@]}" 2>&1 >&2); then
    [ -z "$ub_err" ] || printf '%s\n' "$ub_err" >&2
    if grep -qE "$NET_RE" <<< "$ub_err"; then
      # A write: never retried blind. The next run gates again from the start.
      echo "STOP: NETWORK: gh pr update-branch hit a network error; not merged. Check the PR, then run this again."
      exit 5
    fi
    echo "STOP: gh pr update-branch failed; not merged"
    exit 1
  fi
  wait_not_behind
done
[ -n "${SHA:-}" ] || { echo "STOP: the gate passed but printed no commit; not merged"; exit 1; }
# A caller that proved one head sets GATE_MERGE_EXPECT_HEAD: a push between that proof and this gate
# must not merge.
if [ -n "${GATE_MERGE_EXPECT_HEAD:-}" ] && [ "$SHA" != "$GATE_MERGE_EXPECT_HEAD" ]; then
  echo "STOP: the head moved after the proof ($SHA is not $GATE_MERGE_EXPECT_HEAD); not merged"
  exit 1
fi

# A PR can be green against an older base and still land on a base that has since gone red: with
# "require branches up to date" off, nothing else stops it, and a
# red main run alerts nobody but the merger. Red = a check on the base's latest commit that failed,
# timed out or failed to start; a cancelled or running check is untested, not red. The check suites
# are read too: a workflow that fails before it starts a job (an invalid workflow file) leaves no
# failed check run, only a failed suite (an automated review caught this case). An unreadable base is a warning, not a refusal.
base_info=$(gh_read pr view "$pr" "${repo_args[@]}" --json url,baseRefName --jq '.url + " " + .baseRefName')
[ "$?" -ne 5 ] || net_stop "reading the PR's base branch"
base_url=${base_info% *} base=${base_info##* }
IFS=/ read -r _ _ _ base_owner base_repo _ <<< "$base_url"
RED_IF='select(.conclusion == "failure" or .conclusion == "timed_out" or .conclusion == "startup_failure")'
red="" red_suites="" base_read=""
if [ -n "$base_owner" ] && [ -n "$base_repo" ] && [ -n "$base" ] && [ "$base" != "$base_info" ]; then
  # A network error here must not skip the red-base check and merge.
  # Read one commit: the base branch's SHA now, so the three reads below agree.
  base_sha=$(gh_read api "repos/$base_owner/$base_repo/commits/$base" --jq .sha); sha_rc=$?
  [ "$sha_rc" -ne 5 ] || net_stop "reading the latest commit of the base branch $base"
  [[ "$base_sha" =~ ^[0-9a-f]{40}$ ]] || base_sha=""
  base_ref=${base_sha:-$base}
  # A Dependabot updater run (a workflow run whose path starts dynamic/dependabot/) is not CI: a
  # crashed dependency update must not make the base red and block every merge. Leave out the
  # check runs and suites of those runs; every other failure counts.
  # If the runs cannot be read for another reason, nothing is left out.
  skip=""
  if [ -n "$base_sha" ]; then
    # --paginate prints one id per line across every page; join them after.
    skip=$(gh_read api --paginate "repos/$base_owner/$base_repo/actions/runs?head_sha=$base_sha&per_page=100" \
      --jq '.workflow_runs[] | select((.path // "") | startswith("dynamic/dependabot/")) | .check_suite_id')
    [ "$?" -ne 5 ] || net_stop "reading the Actions runs of the base branch $base"
    skip=$(printf '%s\n' "$skip" | sed '/^$/d' | paste -sd, -)
    [[ "$skip" =~ ^[0-9]+(,[0-9]+)*$ ]] || skip=""
  fi
  [ -z "$skip" ] || echo "gate-merge: ignored $(printf '%s' "$skip" | tr ',' '\n' | grep -c .) Dependabot updater run(s) on the base branch $base (not CI)" >&2
  KEEP_RUN="select((.check_suite.id // 0) as \$s | [$skip] | any(.[]; . == \$s) | not)"
  KEEP_SUITE="select(.id as \$s | [$skip] | any(.[]; . == \$s) | not)"
  red=$(gh_read api --paginate "repos/$base_owner/$base_repo/commits/$base_ref/check-runs?per_page=100" \
    --jq ".check_runs[] | $RED_IF | $KEEP_RUN | .name"); runs_rc=$?
  [ "$runs_rc" -ne 5 ] || net_stop "reading the checks of the base branch $base"
  if [ "$runs_rc" -eq 0 ]; then
    red_suites=$(gh_read api --paginate "repos/$base_owner/$base_repo/commits/$base_ref/check-suites?per_page=100" \
      --jq ".check_suites[] | $RED_IF | $KEEP_SUITE | .app.name"); suites_rc=$?
    [ "$suites_rc" -ne 5 ] || net_stop "reading the check suites of the base branch $base"
    [ "$suites_rc" -ne 0 ] || base_read=1
  fi
fi
if [ -n "$base_read" ]; then
  red=$(printf '%s\n%s\n' "$red" "$red_suites" | sed '/^$/d' | sort -u | paste -sd, - | sed 's/,/, /g')
  if [ -n "$red" ] && [ -z "$allow_red_base" ]; then
    echo "STOP: the base branch $base is red ($red); not merged. Fix $base first, or merge the fix with --allow-red-base"
    exit 1
  fi
  [ -z "$red" ] || echo "gate-merge: the base branch $base is red ($red); merging anyway, allowed by --allow-red-base" >&2
else
  echo "gate-merge: WARNING: could not read the checks of the base branch; merging without the red-base check" >&2
fi

# pr_state: print the PR state (MERGED, OPEN, CLOSED). A network error is retried NET_TRIES times;
# prints nothing when it still cannot be read, and returns 5 when the last error was a network one.
pr_state() {
  gh_read pr view "$pr" "${repo_args[@]}" --json state --jq .state
}

# Capture gh's stderr (and still show it) so a policy refusal can get the --admin hint below.
if ! merge_err=$("$GH" pr merge "$pr" "${repo_args[@]}" --squash --match-head-commit "$SHA" "${merge_flags[@]}" 2>&1 >&2); then
  [ -z "$merge_err" ] || printf '%s\n' "$merge_err" >&2
  # A network error can hide a merge that landed: read the state before calling it refused.
  if grep -qE "$NET_RE" <<< "$merge_err"; then
    state=$(pr_state); state_rc=$?
    if [ "$state" = "MERGED" ]; then
      case " ${merge_flags[*]:-} " in
        *" --delete-branch "*) echo "gate-merge: the merge landed before the network error; check that the head branch was deleted" >&2 ;;
      esac
      echo "MERGED $pr ($SHA)"
      exit 0
    fi
    if [ "$state_rc" -eq 5 ] || [ -z "$state" ]; then
      echo "STOP: NETWORK: gh pr merge hit a network error and the PR state could not be read; check the PR before running this again"
    else
      echo "STOP: NETWORK: gh pr merge hit a network error; the PR is '$state', not merged. Run this again."
    fi
    exit 5
  fi
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
state=$(pr_state); state_rc=$?
if [ "$state" != "MERGED" ] && [ "$state_rc" -eq 5 ]; then
  echo "STOP: NETWORK: the merge call returned, but the PR state could not be read; check the PR, do not merge again blind"
  exit 5
fi
[ "$state" = "MERGED" ] || { echo "STOP: the PR state is '${state:-unknown}', not MERGED"; exit 1; }
echo "MERGED $pr ($SHA)"
