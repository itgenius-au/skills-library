#!/usr/bin/env bash
# Tests for pr-checks-green.sh with a fake gh that prints fixed API results.

set -u

TEST_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
SUBJECT="$TEST_DIR/../pr-checks-green.sh"

shellcheck "$SUBJECT" "$0" || exit 1

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
failures=0

# Fake gh. `gh pr view` prints the fixtures named in FAKE_PR (one per call; the last one
# repeats), and the Actions runs lookup does the same with FAKE_RUNS. Other api calls:
# FAKE_RULES (ruleset JSON), FAKE_BRANCH (branch JSON), FAKE_WORKFLOWS (a count of CI
# workflows, or "fail"). FAKE_FAIL=pr or FAKE_FAIL=rules makes that call fail. Every call's
# arguments are logged to FAKE_LOG.
cat > "$WORK/gh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG"
pick() {
  local list count i
  read -r -a list <<< "${1}"
  count=$(grep -c "${2}" "$FAKE_LOG")
  i=$((count - 1))
  [ "$i" -lt "${#list[@]}" ] || i=$((${#list[@]} - 1))
  cat "$FAKE_DIR/${list[$i]}.json"
}
if [ "${1}" = pr ]; then
  if [ -n "${FAKE_NET_PR:-}" ] && [ "$(grep -c '^pr view' "$FAKE_LOG")" -le "$FAKE_NET_PR" ]; then
    if [ -n "${FAKE_NET_MSG:-}" ]; then printf '%b\n' "$FAKE_NET_MSG" >&2; else echo 'Post "https://api.github.com/graphql": dial tcp 192.0.2.1:443: i/o timeout' >&2; fi
    exit 1
  fi
  [ "${FAKE_FAIL:-}" = pr ] && { echo "HTTP 404: Not Found" >&2; exit 1; }
  pick "$FAKE_PR" "^pr view"
  exit 0
fi
case "${2}" in
  */rules/branches/*)
    if [ -n "${FAKE_NET_RULES:-}" ] && [ "$(grep -c 'rules/branches' "$FAKE_LOG")" -le "$FAKE_NET_RULES" ]; then
      echo 'Get "https://api.github.com/repos/example/repo/rules/branches/main": net/http: TLS handshake timeout' >&2; exit 1
    fi
    [ "${FAKE_FAIL:-}" = rules ] && { echo "HTTP 403: Forbidden" >&2; exit 1; }
    [ "${FAKE_FAIL:-}" = rules_free_plan ] && { echo '{"message":"Upgrade to GitHub Pro or make this repository public to enable this feature."}'; echo "gh: Upgrade to GitHub Pro or make this repository public to enable this feature. (HTTP 403)" >&2; exit 1; }
    printf '%s\n' "${FAKE_RULES:-[]}" ;;
  */actions/runs*) pick "${FAKE_RUNS:-no_runs}" "actions/runs" ;;
  */actions/workflows*)
    [ "${FAKE_WORKFLOWS:-0}" = fail ] && exit 1
    printf '{"workflows":[{"state":"active","path":"dynamic/dependabot/dependabot-updates"}'
    for _ in $(seq 1 "${FAKE_WORKFLOWS:-0}"); do printf ',{"state":"active","path":".github/workflows/ci.yml"}'; done
    printf ']}\n' ;;
  */branches/*)
    if [ -n "${FAKE_BRANCH:-}" ]; then printf '%s\n' "$FAKE_BRANCH"; else echo '{"protection":{"enabled":false}}'; fi ;;
esac
SH
chmod +x "$WORK/gh"

fixture() { printf '%s\n' "${2}" > "$WORK/${1}.json"; }
# prj MERGE_STATE CHECKS [SHA] [URL]: a `gh pr view` result.
prj() {
  printf '{"url":"%s","headRefOid":"%s","baseRefName":"main","mergeStateStatus":"%s","statusCheckRollup":[%s]}' \
    "${4:-https://github.com/example/repo/pull/12}" "${3:-aaa111}" "${1}" "${2}"
}

ok='{"__typename":"CheckRun","name":"build","status":"COMPLETED","conclusion":"SUCCESS","detailsUrl":"https://example.test/run/1"}'
queued='{"__typename":"CheckRun","name":"deploy","status":"QUEUED","conclusion":""}'
fixture green "$(prj CLEAN "$ok")"
fixture green_new_head "$(prj CLEAN "$ok" bbb222)"
fixture green_plus_queued "$(prj BLOCKED "$ok,$queued")"
fixture cancelled "$(prj UNKNOWN '{"__typename":"CheckRun","completedAt":"2026-01-02T10:15:00Z","conclusion":"CANCELLED","detailsUrl":"https://github.com/example/repo/actions/runs/1111111111/job/2222222222","name":"ci","startedAt":"2026-01-02T10:00:00Z","status":"COMPLETED","workflowName":"ci"}')"
fixture failed "$(prj BLOCKED "$ok"',{"__typename":"CheckRun","name":"tests","status":"COMPLETED","conclusion":"FAILURE"}')"
fixture skipped "$(prj BLOCKED '{"__typename":"CheckRun","name":"tests","status":"COMPLETED","conclusion":"SKIPPED"}')"
fixture pending "$(prj BLOCKED "$queued")"
review_neutral='{"__typename":"CheckRun","name":"Optional Review Bot","status":"COMPLETED","conclusion":"NEUTRAL","detailsUrl":"https://example.test/run/2"}'
fixture green_plus_neutral "$(prj CLEAN "$ok,$review_neutral")"
fixture neutral_only "$(prj CLEAN "$review_neutral")"
fixture failed_while_pending "$(prj BLOCKED '{"__typename":"CheckRun","name":"lint","status":"COMPLETED","conclusion":"FAILURE"},'"$queued")"
fixture none "$(prj CLEAN '')"
fixture none_other_repo "$(prj CLEAN '' aaa111 https://github.com/other/thing/pull/7)"
fixture status_ok "$(prj CLEAN '{"__typename":"StatusContext","context":"ci/legacy","state":"SUCCESS","targetUrl":"https://example.test/s"}')"
fixture status_pending "$(prj BLOCKED '{"__typename":"StatusContext","context":"ci/legacy","state":"PENDING"}')"
fixture status_error "$(prj BLOCKED '{"__typename":"StatusContext","context":"ci/legacy","state":"ERROR"}')"
fixture dirty "$(prj DIRTY '')"
fixture behind "$(prj BEHIND "$ok")"
fixture unknown_state "$(prj UNKNOWN "$ok")"
fixture no_runs '{"total_count":0,"workflow_runs":[]}'
fixture run_in_progress '{"total_count":1,"workflow_runs":[{"name":"CI","event":"pull_request","status":"in_progress","conclusion":null}]}'
fixture run_done '{"total_count":1,"workflow_runs":[{"name":"CI","event":"pull_request","status":"completed","conclusion":"success"}]}'
fixture run_cancelled '{"total_count":1,"workflow_runs":[{"name":"CI","event":"pull_request","status":"completed","conclusion":"cancelled","html_url":"https://example.test/r/9"}]}'

# check NAME EXPECTED_EXIT EXPECTED_TEXT PR_FIXTURES [script args...]
# Env FAKE_* set on the call line pass through to the fake gh.
check() {
  local name=${1} want=${2} text=${3} fixtures=${4}
  shift 4
  : > "$WORK/log"
  local out rc
  out=$(FAKE_PR="$fixtures" FAKE_DIR="$WORK" FAKE_LOG="$WORK/log" \
    PR_CHECKS_GH="$WORK/gh" PR_CHECKS_INTERVAL="${TEST_INTERVAL:-0}" PR_CHECKS_NONE_GRACE="${TEST_GRACE:-0}" \
    PR_CHECKS_NONE_SETTLE="${TEST_SETTLE:-0}" PR_CHECKS_WAIT_S="${TEST_WAIT_S:-}" \
    PR_CHECKS_NET_SLEEP=0 PR_CHECKS_NET_TRIES="${TEST_NET_TRIES:-5}" \
    bash "$SUBJECT" "$@" 2> "$WORK/stderr")
  rc=$?
  printf '%s\n' "$out" > "$WORK/stdout"
  if [ "$rc" -ne "$want" ] || ! cat "$WORK/stdout" "$WORK/stderr" | grep -qF -- "$text"; then
    printf 'FAIL %s (exit %s, want %s, want text "%s")\n' "$name" "$rc" "$want" "$text"
    cat "$WORK/stdout" "$WORK/stderr"
    failures=$((failures + 1))
  else
    printf 'PASS %s\n' "$name"
  fi
}
expect_stdout() {
  if [ "$(cat "$WORK/stdout")" != "${1}" ]; then
    printf 'FAIL stdout is only the head SHA: got "%s", want "%s"\n' "$(cat "$WORK/stdout")" "${1}"
    failures=$((failures + 1))
  fi
}
expect_logged() {
  if ! grep -qF -- "${1}" "$WORK/log"; then
    printf 'FAIL gh was not called with "%s"\n' "${1}"; cat "$WORK/log"
    failures=$((failures + 1))
  fi
}

check "all checks succeeded" 0 "GREEN" "green" 12
expect_stdout aaa111
check "cancelled check is red (gh exits 0 here)" 1 "ci: CANCELLED" "cancelled" 12
check "cancelled check names the re-run" 1 "gh run rerun" "cancelled" 12
check "one failure among successes" 1 "tests: FAILURE" "failed" 12
check "skipped-only is not green" 1 "tests: SKIPPED" "skipped" 12
check "an optional NEUTRAL check counts as passed" 0 "not a required check, counted as passed" "green_plus_neutral" 12
expect_stdout aaa111
FAKE_RULES='[{"type":"required_status_checks","parameters":{"required_status_checks":[{"context":"Optional Review Bot"}]}}]' \
  check "a required NEUTRAL check is red" 1 "Optional Review Bot: NEUTRAL" "green_plus_neutral" 12
FAKE_BRANCH='{"protection":{"enabled":true,"required_status_checks":{"contexts":["Optional Review Bot"],"checks":[]}}}' \
  check "a required NEUTRAL check (classic protection) is red" 1 "Optional Review Bot: NEUTRAL" "green_plus_neutral" 12
check "only optional NEUTRAL checks is green (the repo requires none)" 0 "counted as passed" "neutral_only" 12
check "still queued at the time limit" 3 "still running" "pending" --wait-minutes 0 12
check "queued, then succeeded" 0 "GREEN" "pending pending green" 12
check "a failure stops the wait at once" 1 "lint: FAILURE" "failed_while_pending" 12
check "a check that registers late resets green" 3 "deploy: QUEUED" "green green_plus_queued" --wait-minutes 0 12
check "a new head commit must be green twice" 0 "GREEN" "green green_new_head green_new_head" 12
expect_stdout bbb222
check "status context success" 0 "GREEN" "status_ok" 12
check "status context pending" 3 "still running" "status_pending" --wait-minutes 0 12
check "status context error" 1 "ci/legacy: ERROR" "status_error" 12
check "merge conflict stops" 4 "merge conflict" "dirty" 12
check "behind a strict base stops" 4 "gh pr update-branch" "behind" 12
check "an UNKNOWN merge state is not green" 3 "merge state: UNKNOWN" "unknown_state" --wait-minutes 0 12
check "UNKNOWN, then a computed state, is green" 0 "GREEN" "unknown_state green" 12

FAKE_RUNS="run_in_progress" check "an Actions run still in progress blocks green" 3 "run CI (pull_request): in_progress" "green" --wait-minutes 0 12
FAKE_RUNS="run_in_progress run_in_progress run_done" check "green after the run completes" 0 "GREEN" "green" 12
FAKE_RUNS="run_cancelled" check "a cancelled Actions run is red" 1 "run CI (pull_request): cancelled" "green" 12

FAKE_RULES='[{"type":"required_status_checks","parameters":{"required_status_checks":[{"context":"deploy"}]}}]' \
  check "a required check (ruleset) not reported yet blocks" 3 "deploy: REQUIRED, NOT REPORTED YET" "green" --wait-minutes 0 12
FAKE_BRANCH='{"protection":{"enabled":true,"required_status_checks":{"contexts":["e2e"],"checks":[]}}}' \
  check "a required check (classic protection) not reported yet blocks" 3 "e2e: REQUIRED, NOT REPORTED YET" "green" --wait-minutes 0 12
FAKE_RULES='[{"type":"required_status_checks","parameters":{"required_status_checks":[{"context":"build"}]}}]' \
  check "a reported required check passes" 0 "GREEN" "green" 12

check "no checks is a stop" 2 "no checks registered" "none" --wait-minutes 0 12
check "--allow-none passes a repo with no CI (Dependabot does not count)" 0 "no CI workflows" "none" --allow-none 12
TEST_GRACE=600 check "--allow-none at the time limit ends the grace" 0 "no CI workflows" "none" --allow-none --wait-minutes 0 12
FAKE_WORKFLOWS=2 check "--allow-none does not pass a repo with CI" 2 "has 2 CI workflows" "none" --allow-none --wait-minutes 0 12
FAKE_WORKFLOWS=fail check "--allow-none fails closed when the lookup fails" 2 "has unknown CI workflows" "none" --allow-none --wait-minutes 0 12
FAKE_RULES='[{"type":"required_status_checks","parameters":{"required_status_checks":[{"context":"build"}]}}]' \
  check "--allow-none does not pass when a required check is missing" 3 "build: REQUIRED, NOT REPORTED YET" "none" --allow-none --wait-minutes 0 12
check "--allow-none looks up the PR's own repo" 0 "other/thing" "none_other_repo" --allow-none https://github.com/other/thing/pull/7
expect_logged "api repos/other/thing/actions/workflows"

# No checks at all, and the base requires none (a repo with no CI): green after a short settle, without --allow-none. Every negative
# case runs with a 2 second limit so it proves the gate keeps waiting rather than stops at once.
check "no checks, base requires none, CLEAN: green after the settle" 0 "GREEN: no checks configured on example/repo; base requires none" "none" 12
expect_stdout aaa111
TEST_WAIT_S=2 TEST_INTERVAL=0.2 FAKE_RULES='[{"type":"required_status_checks","parameters":{"required_status_checks":[{"context":"build"}]}}]' \
  check "no checks yet, ruleset requires one: keeps waiting" 3 "build: REQUIRED, NOT REPORTED YET" "none" 12
TEST_WAIT_S=2 TEST_INTERVAL=0.2 FAKE_BRANCH='{"protection":{"enabled":true,"required_status_checks":{"contexts":["e2e"],"checks":[]}}}' \
  check "no checks yet, classic protection requires one: keeps waiting" 3 "e2e: REQUIRED, NOT REPORTED YET" "none" 12
FAKE_FAIL="rules" check "no checks, rules API unreadable: no pass, clear message" 4 "gh api repos/example/repo/rules/branches/main failed" "none" 12
TEST_WAIT_S=2 TEST_INTERVAL=0.2 FAKE_BRANCH='{"name":"main"}' \
  check "no checks, classic protection unreadable: keeps waiting, says why" 2 "could not confirm that main requires no status checks" "none" 12
TEST_WAIT_S=2 TEST_INTERVAL=0.2 FAKE_RUNS="run_done" \
  check "no checks but an Actions run exists for the head: not the no-checks path" 2 "no checks registered" "none" 12
fixture none_blocked "$(prj BLOCKED '')"
TEST_WAIT_S=2 TEST_INTERVAL=0.2 check "no checks, merge state not CLEAN: keeps waiting" 2 "no checks registered" "none_blocked" 12
TEST_WAIT_S=2 TEST_INTERVAL=0.2 TEST_SETTLE=600 check "no checks: the settle must finish before the limit" 2 "no checks registered" "none" 12

# A private repo on a plan without protection features (for example a private repo on a free plan): the rules
# endpoint answers 403 "Upgrade to GitHub Pro", so no ruleset can exist; the plain branch endpoint
# still says whether the branch is protected.
PLAN_BRANCH='{"protected":false,"protection":{"enabled":false,"required_status_checks":{"checks":[],"contexts":[],"enforcement_level":"off"}}}'
FAKE_FAIL=rules_free_plan FAKE_BRANCH="$PLAN_BRANCH" \
  check "plan 403 on rules, branch unprotected, no checks, CLEAN: green" 0 "GREEN: no checks configured on example/repo; base requires none" "none" 12
expect_stdout aaa111
FAKE_FAIL=rules_free_plan FAKE_BRANCH='{"protected":false}' \
  check "plan 403 on rules, protected:false alone: green" 0 "base requires none" "none" 12
TEST_WAIT_S=2 TEST_INTERVAL=0.2 FAKE_FAIL=rules \
  check "a 403 with a different message still stops" 4 "HTTP 403: Forbidden" "none" 12
TEST_WAIT_S=2 TEST_INTERVAL=0.2 FAKE_FAIL=rules_free_plan \
  FAKE_BRANCH='{"protected":true,"protection":{"enabled":true,"required_status_checks":{"checks":[],"contexts":["e2e"],"enforcement_level":"everyone"}}}' \
  check "plan 403 on rules, branch protected with a required context: keeps waiting" 3 "e2e: REQUIRED, NOT REPORTED YET" "none" 12

check "missing PR argument" 4 "Usage" "green"
check "bad --wait-minutes" 4 "whole number" "green" --wait-minutes soon 12
FAKE_FAIL="pr" check "gh pr view error stops" 4 "HTTP 404" "green" 12
FAKE_FAIL="rules" check "required-check lookup error stops" 4 "HTTP 403" "green" 12
FAKE_FAIL="rules_free_plan" check "a free-plan private repo has no rulesets" 0 "GREEN" "green" 12
check "--repo is passed to gh pr view" 0 "GREEN" "green" 12 --repo example/repo
expect_logged "pr view 12 --repo example/repo --json"

# Network errors (an i/o timeout must stop as NETWORK, never read as "checks are not green").
expect_calls() {  # expect_calls PATTERN COUNT
  local n
  n=$(grep -c "${1}" "$WORK/log")
  if [ "$n" -ne "${2}" ]; then
    printf 'FAIL want %s gh calls matching "%s", got %s\n' "${2}" "${1}" "$n"; cat "$WORK/log"
    failures=$((failures + 1))
  fi
}
FAKE_NET_PR=2 check "a network error on gh pr view is retried, then green" 0 "GREEN" "green" 12
expect_stdout aaa111
if ! grep -qF "gh network error, try 1 of 5" "$WORK/stderr"; then
  printf 'FAIL the retry is not reported on stderr\n'; cat "$WORK/stderr"; failures=$((failures + 1))
fi
FAKE_NET_PR=99 check "network errors on every try stop as NETWORK, not red" 5 "STOP: NETWORK: gh pr view 12" "green" 12
expect_calls "^pr view" 5
if grep -q "^RED" "$WORK/stderr"; then printf 'FAIL a network stop printed RED\n'; failures=$((failures + 1)); fi
FAKE_NET_PR=99 TEST_NET_TRIES=2 check "PR_CHECKS_NET_TRIES sets the number of tries" 5 "failed 2 times" "green" 12
expect_calls "^pr view" 2
FAKE_NET_RULES=99 check "network errors on the rules lookup stop as NETWORK" 5 \
  "STOP: NETWORK: gh api repos/example/repo/rules/branches/main" "green" 12
FAKE_NET_RULES=1 check "one network error on the rules lookup is retried" 0 "GREEN" "green" 12
FAKE_FAIL="pr" check "a non-network gh error is not retried" 4 "HTTP 404" "green" 12
expect_calls "^pr view" 1
# gh rewrites a DNS failure to these two lines; the Go text "no such host" shows only with GH_DEBUG.
FAKE_NET_PR=1 FAKE_NET_MSG='error connecting to api.github.com\ncheck your internet connection or https://githubstatus.com' \
  check "gh's DNS-failure text is retried" 0 "GREEN" "green" 12
expect_calls "^pr view" 3
FAKE_NET_PR=99 FAKE_NET_MSG='error connecting to api.github.com\ncheck your internet connection or https://githubstatus.com' \
  check "a two-line network error gives a one-line NETWORK stop" 5 "check your internet connection or https://githubstatus.com ; checks not read" "green" 12

if [ "$failures" -ne 0 ]; then
  printf '%s test(s) failed\n' "$failures"
  exit 1
fi
echo "all pr-checks-green tests passed"
