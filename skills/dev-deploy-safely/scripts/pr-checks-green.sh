#!/usr/bin/env bash
# pr-checks-green.sh: the merge gate. Wait for a pull request's checks, then exit 0 and print
# the PR's head commit SHA (the only stdout line) only when it is safe to merge that commit.
# Merge with: gh pr merge <pr> --match-head-commit "$SHA" (so a later push cannot slip in).
#
# Do not gate a merge on the exit code of `gh pr checks --watch`: gh 2.101 exits 0 when a
# check was CANCELLED. GitHub can cancel a check that waits too long in the runner queue; the
# check then never runs, and a gate that trusts the watch's exit code merges the PR without it.
#
# Usage: pr-checks-green.sh [--allow-none] [--wait-minutes N] <pr> [--repo owner/name]
#   <pr>            PR number, URL or branch (as `gh pr view` takes it)
#   --allow-none    pass a PR with no checks, only when its repo has no CI to run
#   --wait-minutes  how long to wait for checks to register and finish (default 30)
# Exit codes: 0 green, 1 red (a check did not succeed), 2 no checks registered,
#   3 checks still running at the time limit, 4 usage error, gh error, conflict or behind, 5 network.
# Exit 5 (NETWORK) means GitHub could not be reached after PR_CHECKS_NET_TRIES tries: the checks were not read.
#
# GREEN means all of these, seen on two polls in a row for the same head commit:
#   - every check on the head commit finished with SUCCESS (SKIPPED, CANCELLED and every other
#     result is red);
#     A NEUTRAL check that is not a required check of the base branch counts as passed (an
#     optional bot that declined to run); a required NEUTRAL check stays red.
#   - every required check of the base branch (rulesets and classic protection) is present;
#   - every GitHub Actions run for the head commit is complete (a job that waits on another
#     job registers its check late, so the check list alone can look green too early);
#   - the PR has no merge conflict and is not behind a base that requires up-to-date branches
#     (an UNKNOWN merge state, which GitHub shows while it computes, counts as still running).
# A PR with NO checks and NO Actions runs for its head commit also passes, without --allow-none,
# when the base branch demonstrably requires no status checks (no required_status_checks rule in
# the branch rules, and classic protection readable with none) and the merge state is CLEAN. It
# must look that way on every poll for PR_CHECKS_NONE_SETTLE seconds (default 60) and at least two
# polls, then prints "GREEN: no checks configured on <repo>; base requires none". If the rules
# or protection cannot be read, it never assumes "none": it keeps waiting and says why.
# A CI app outside GitHub Actions (a check app or commit status) is waited for only when it is
# a required check, so make such a check required in the base branch's ruleset.
#
# A network error from gh (i/o timeout, TLS handshake timeout, connection reset or refused, no
# such host, unexpected EOF, gh's "error connecting to" / "check your internet connection" for a
# DNS failure, a Go client timeout, HTTP 502/503/504) is retried PR_CHECKS_NET_TRIES times (default 5),
# PR_CHECKS_NET_SLEEP seconds apart (default 15). When every try fails it prints
# "STOP: NETWORK: ...; checks not read" and exits 5, never "red". Any other gh error stops at once.
# A network stop that reads as "checks are not green" sends you to debug a change that is fine.
set -u

GH=${PR_CHECKS_GH:-gh}
INTERVAL=${PR_CHECKS_INTERVAL:-20}
NONE_GRACE=${PR_CHECKS_NONE_GRACE:-60}
NONE_SETTLE=${PR_CHECKS_NONE_SETTLE:-60}
WAIT_S=${PR_CHECKS_WAIT_S:-}   # test hook: overrides --wait-minutes with a limit in seconds
NET_TRIES=${PR_CHECKS_NET_TRIES:-5}
NET_SLEEP=${PR_CHECKS_NET_SLEEP:-15}
NET_RE='i/o timeout|TLS handshake timeout|connection reset|connection refused|no such host|unexpected EOF|error connecting to|check your internet connection|context deadline exceeded|Client.Timeout exceeded|HTTP 50[234]'
allow_none=0
wait_minutes=30
pr=""
repo_args=()

usage() { sed -n '10,15p' "$0" >&2; exit 4; }

while [ "$#" -gt 0 ]; do
  case "${1}" in
    --allow-none) allow_none=1; shift ;;
    --wait-minutes)
      [ "$#" -ge 2 ] || usage
      wait_minutes=${2}; shift 2 ;;
    --repo)
      [ "$#" -ge 2 ] || usage
      repo_args=(--repo "${2}"); shift 2 ;;
    -h | --help) usage ;;
    -*) echo "unknown option: ${1}" >&2; usage ;;
    *)
      [ -z "$pr" ] || { echo "unexpected argument: ${1}" >&2; usage; }
      pr=${1}; shift ;;
  esac
done
[ -n "$pr" ] || usage
case "$wait_minutes" in '' | *[!0-9]*) echo "--wait-minutes needs a whole number" >&2; usage ;; esac

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Reads the `gh pr view` JSON and prints "<owner/repo> <base branch> <head sha>".
META=$(cat <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
parts = (d.get("url") or "").split("/")
if len(parts) < 7 or parts[5] != "pull" or not d.get("headRefOid") or not d.get("baseRefName"):
    sys.exit("unexpected gh pr view output: " + json.dumps(d)[:300])
print(parts[3] + "/" + parts[4], d["baseRefName"], d["headRefOid"])
PY
)

# Prints the state on the first line (GREEN, RED, PENDING, NONE, CONFLICT or BEHIND), then
# one line per finding. Arguments: pr.json rules.json branch.json runs.json
CLASSIFY=$(cat <<'PY'
import json, sys

pr, rules, branch, runs = (json.load(open(p)) for p in sys.argv[1:5])
merge_state = pr.get("mergeStateStatus") or ""
if merge_state == "DIRTY":
    print("CONFLICT")
    print("  the PR has a merge conflict, so its checks never start: rebase onto the base branch and push")
    sys.exit()
if merge_state == "BEHIND":
    print("BEHIND")
    print("  the base branch requires up-to-date branches: run `gh pr update-branch`, then gate again")
    sys.exit()

required = set()
for rule in rules if isinstance(rules, list) else []:
    if rule.get("type") == "required_status_checks":
        for c in (rule.get("parameters") or {}).get("required_status_checks") or []:
            if c.get("context"):
                required.add(c["context"])
rsc = ((branch.get("protection") or {}).get("required_status_checks") or {})
required.update(x for x in rsc.get("contexts") or [] if x)
required.update(c.get("context") for c in rsc.get("checks") or [] if c.get("context"))

rows, pending, bad, cancelled, seen = [], 0, 0, 0, set()
if merge_state == "UNKNOWN":
    pending += 1
    rows.append("  merge state: UNKNOWN (GitHub is still computing it)")
checks = pr.get("statusCheckRollup") or []
for c in checks:
    if c.get("__typename") == "StatusContext":
        name = c.get("context") or "?"
        result = (c.get("state") or "").upper()
        status = "PENDING" if result in ("", "PENDING", "EXPECTED") else "COMPLETED"
        url = c.get("targetUrl") or ""
    else:
        name = c.get("name") or "?"
        result = (c.get("conclusion") or "").upper()
        status = (c.get("status") or "").upper()
        url = c.get("detailsUrl") or ""
    seen.add(name)
    if status != "COMPLETED":
        pending += 1
        rows.append(f"  {name}: {status or 'PENDING'}")
        continue
    if result == "NEUTRAL" and name not in required:
        # An optional check that chose not to run (e.g. "Optional Review Bot: review declined").
        rows.append(f"  {name}: NEUTRAL, not a required check, counted as passed {url}".rstrip())
        continue
    if result != "SUCCESS":
        bad += 1
        cancelled += result == "CANCELLED"
    rows.append(f"  {name}: {result or 'NO RESULT'} {url}".rstrip())

for name in sorted(required - seen):
    pending += 1
    rows.append(f"  {name}: REQUIRED, NOT REPORTED YET")

workflow_runs = runs.get("workflow_runs") or []
for r in workflow_runs:
    name = f"run {r.get('name') or '?'} ({r.get('event') or '?'})"
    status = (r.get("status") or "").lower()
    result = (r.get("conclusion") or "").lower()
    if status != "completed":
        pending += 1
        rows.append(f"  {name}: {status or 'pending'}")
    elif result not in ("success", "skipped", "neutral"):
        bad += 1
        cancelled += result == "cancelled"
        rows.append(f"  {name}: {result or 'no result'} {r.get('html_url') or ''}".rstrip())

if bad:
    state = "RED"
elif pending:
    state = "PENDING"
elif not checks:
    state = "NONE"
else:
    state = "GREEN"
print(state)
if rows:
    print("\n".join(rows))
if cancelled:
    print("  a CANCELLED check never finished (often a runner queue timeout): re-run it with"
          " `gh run rerun <run-id>` and gate again; never merge over it")
PY
)

# Prints "yes" only when the base branch demonstrably requires no status checks and the PR is
# CLEAN with no Actions run for its head; otherwise "no: <why>". Arguments: pr.json rules.json
# branch.json runs.json
NOREQ=$(cat <<'PY'
import json, sys

pr, rules, branch, runs = (json.load(open(p)) for p in sys.argv[1:5])
if (pr.get("mergeStateStatus") or "") != "CLEAN":
    print("no: the merge state is not CLEAN")
elif runs.get("workflow_runs"):
    print("no: Actions runs exist for the head commit")
elif not isinstance(rules, list):
    print("no: could not read the branch rules")
elif any(r.get("type") == "required_status_checks" for r in rules):
    print("no: the branch rules require status checks")
elif not isinstance(branch.get("protection"), dict) and branch.get("protected") is not False:
    print("no: could not read the classic branch protection")
else:
    rsc = (branch.get("protection") or {}).get("required_status_checks") or {}
    if rsc.get("contexts") or rsc.get("checks"):
        print("no: classic branch protection requires status checks")
    else:
        print("yes")
PY
)

# gh_try FILE ARGS...: run gh with stdout in FILE and stderr in $WORK/err. A network error is
# retried (see the header). Returns 0 on success, 1 on any other error, 5 when every try hit a
# network error.
gh_try() {
  local file=${1} n=1
  shift
  while :; do
    "$GH" "$@" > "$file" 2> "$WORK/err" && return 0
    grep -qE "$NET_RE" "$WORK/err" || return 1
    [ "$n" -lt "$NET_TRIES" ] || return 5
    printf 'gh network error, try %s of %s, again in %ss: %s\n' "$n" "$NET_TRIES" "$NET_SLEEP" \
      "$(head -c 200 "$WORK/err" | tr '\n' ' ')" >&2
    n=$((n + 1))
    sleep "$NET_SLEEP"
  done
}

# net_stop ARGS...: the gh call ARGS hit a network error on every try.
net_stop() {
  printf 'STOP: NETWORK: gh %s failed %s times: %s; checks not read\n' "$*" "$NET_TRIES" \
    "$(head -c 300 "$WORK/err" | tr '\n' ' ')" >&2
  exit 5
}

# gh_json FILE ARGS...: run gh and keep stdout in FILE; on failure print the error and exit 4
# (5 after a network error on every try).
gh_json() {
  local file=${1} rc
  shift
  gh_try "$file" "$@"
  rc=$?
  [ "$rc" -eq 0 ] && return 0
  [ "$rc" -eq 5 ] && net_stop "$@"
  printf 'STOP: gh %s failed: %s\n' "$*" "$(cat "$WORK/err")" >&2
  exit 4
}

# Number of active workflows under .github/workflows/ (GitHub-managed ones such as Dependabot,
# path dynamic/..., are not CI), or "unknown" when the lookup fails.
repo_workflows() {
  gh_try "$WORK/workflows.json" api "repos/${1}/actions/workflows?per_page=100" || { echo unknown; return; }
  python3 -c 'import json, sys
d = json.load(open(sys.argv[1]))
print(sum(1 for w in d.get("workflows") or []
          if w.get("state") == "active" and (w.get("path") or "").startswith(".github/workflows/")))' \
    "$WORK/workflows.json" 2> /dev/null || echo unknown
}

start=$(date +%s)
deadline=$((start + wait_minutes * 60))
[ -z "$WAIT_S" ] || deadline=$((start + WAIT_S))
green_sha=""
rules_for=""
workflows=""
noreq_sha="" noreq_since=0 noreq_polls=0 noreq_why=""
while :; do
  gh_json "$WORK/pr.json" pr view "$pr" ${repo_args[@]+"${repo_args[@]}"} \
    --json url,headRefOid,baseRefName,mergeStateStatus,statusCheckRollup
  if ! meta=$(python3 -c "$META" "$WORK/pr.json" 2>&1); then
    printf 'STOP: %s\n' "$meta" >&2
    exit 4
  fi
  read -r repo base sha <<< "$meta"
  if [ "$rules_for" != "$repo $base" ]; then
    # A private repo on a free plan has no rulesets: GitHub answers 403 "Upgrade to GitHub Pro".
    gh_try "$WORK/rules.json" api "repos/$repo/rules/branches/$base"
    rules_rc=$?
    [ "$rules_rc" -eq 5 ] && net_stop api "repos/$repo/rules/branches/$base"
    if [ "$rules_rc" -ne 0 ]; then
      if grep -q "Upgrade to GitHub Pro" "$WORK/err" "$WORK/rules.json" 2> /dev/null; then
        echo "[]" > "$WORK/rules.json"
      else
        printf 'STOP: gh api repos/%s/rules/branches/%s failed: %s\n' "$repo" "$base" "$(cat "$WORK/err")" >&2
        exit 4
      fi
    fi
    gh_json "$WORK/branch.json" api "repos/$repo/branches/$base"
    rules_for="$repo $base"
  fi
  gh_json "$WORK/runs.json" api "repos/$repo/actions/runs?head_sha=$sha&per_page=100"
  if ! verdict=$(python3 -c "$CLASSIFY" "$WORK/pr.json" "$WORK/rules.json" "$WORK/branch.json" "$WORK/runs.json" 2>&1); then
    printf 'STOP: could not read the check results: %s\n' "$verdict" >&2
    exit 4
  fi
  state=${verdict%%$'\n'*}
  details=""
  [ "$verdict" = "$state" ] || details=${verdict#*$'\n'}
  now=$(date +%s)
  case "$state" in
    GREEN)
      if [ "$green_sha" = "$sha" ]; then
        printf 'GREEN: every check succeeded on %s (%s)\n%s\n' "$sha" "$repo" "$details" >&2
        echo "$sha"
        exit 0
      fi
      # Look once more before passing: a check can register late.
      green_sha=$sha
      sleep "$INTERVAL"
      continue ;;
    RED) printf 'RED: do not merge (%s)\n%s\n' "$repo" "$details" >&2; exit 1 ;;
    CONFLICT | BEHIND) printf 'STOP: %s\n' "$details" >&2; exit 4 ;;
    NONE)
      # Give checks a short grace to register; the time limit ends the grace early.
      if [ "$allow_none" -eq 1 ] && { [ $((now - start)) -ge "$NONE_GRACE" ] || [ "$now" -ge "$deadline" ]; }; then
        [ -n "$workflows" ] || workflows=$(repo_workflows "$repo")
        if [ "$workflows" = 0 ]; then
          echo "GREEN: this PR has no checks, and $repo has no CI workflows or required checks (--allow-none)" >&2
          echo "$sha"
          exit 0
        fi
        if [ "$now" -ge "$deadline" ]; then
          echo "STOP: no checks registered after ${wait_minutes} minutes, and $repo has ${workflows} CI workflows, so --allow-none does not apply" >&2
          exit 2
        fi
      fi
      # A repo that requires no checks never registers one: pass after a settle (see the header).
      noreq=$(python3 -c "$NOREQ" "$WORK/pr.json" "$WORK/rules.json" "$WORK/branch.json" "$WORK/runs.json" 2>&1) || noreq="no: $noreq"
      if [ "$noreq" = yes ]; then
        if [ "$noreq_sha" != "$sha" ]; then noreq_sha=$sha; noreq_since=$now; noreq_polls=0; fi
        noreq_polls=$((noreq_polls + 1))
        if [ "$noreq_polls" -ge 2 ] && [ $((now - noreq_since)) -ge "$NONE_SETTLE" ]; then
          echo "GREEN: no checks configured on $repo; base requires none ($sha)" >&2
          echo "$sha"
          exit 0
        fi
      else
        noreq_sha="" noreq_why=${noreq#no: }
      fi ;;
  esac
  green_sha=""
  if [ "$now" -ge "$deadline" ]; then
    if [ "$state" = NONE ]; then
      echo "STOP: no checks registered after ${wait_minutes} minutes; --allow-none passes only a repo with no CI" >&2
      case "$noreq_why" in
        "could not read"*) echo "  could not confirm that $base requires no status checks ($noreq_why), so a PR with no checks was not passed" >&2 ;;
      esac
      exit 2
    fi
    printf 'STOP: checks still running after %s minutes\n%s\n' "$wait_minutes" "$details" >&2
    exit 3
  fi
  sleep "$INTERVAL"
done
