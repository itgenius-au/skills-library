#!/usr/bin/env bash
# Tests gate-merge.sh with a stub merge gate and a stub gh: the merge runs only
# on a green gate and only for the gated commit, a behind branch is updated (up to 3 times) and gated again,
# and the result is MERGED or a STOP. Offline: no network, no real gh.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SCRIPT="$(cd "$HERE/.." && pwd)/gate-merge.sh"

T=$(mktemp -d -t gate-merge.XXXXXX)
trap 'rm -rf "$T"' EXIT
FAILS=0
ok()  { echo "PASS: $1"; }
bad() { echo "FAIL: $1"; FAILS=$((FAILS + 1)); }

SHA=1234567890abcdef1234567890abcdef12345678
# Stub gate: reads one scripted outcome per call from $GATE_PLAN (green | behind | red).
cat > "$T/gate" <<'EOF'
#!/usr/bin/env bash
echo "gate $*" >> "$CALLS"
n=$(cat "$T_DIR/gate_n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$T_DIR/gate_n"
outcome=$(sed -n "${n}p" "$GATE_PLAN")
case "$outcome" in
  green) echo "GREEN: every check succeeded" >&2; echo "$GATE_SHA"; exit 0 ;;
  behind) echo "STOP:   the base branch requires up-to-date branches: run \`gh pr update-branch\`, then gate again" >&2; exit 4 ;;
  network) echo "STOP: NETWORK: gh pr view 42 failed 5 times: dial tcp 192.0.2.1:443: i/o timeout; checks not read" >&2; exit 5 ;;
  *) echo "RED: ci FAILURE" >&2; exit 1 ;;
esac
EOF
# Stub gh: records calls; `pr view --json mergeStateStatus` prints the next line of $MSS_PLAN
# (CLEAN when the plan runs out); `pr view --json state` prints $GH_STATE. The base-branch
# check-runs lookup runs the script's own --jq filter over $BASE_RUNS (page 1) and, only with
# --paginate, $BASE_PAGE2; it fails when $BASE_LOOKUP_FAIL is set.
cat > "$T/gh" <<'EOF'
#!/usr/bin/env bash
echo "gh $*" >> "$CALLS"
case "$*" in
  *baseRefName*) echo "https://github.com/o/r/pull/42 main" ;;
  *"commits/main --jq .sha"*)
    [ -z "${BASE_SHA_NET:-}" ] || { echo "dial tcp 192.0.2.1:443: i/o timeout" >&2; exit 1; }
    echo "${BASE_SHA:-cccccccccccccccccccccccccccccccccccccccc}" ;;
  *"actions/runs"*)
    [ -z "${BASE_WF_NET:-}" ] || { echo "dial tcp 192.0.2.1:443: i/o timeout" >&2; exit 1; }
    q="" paginate=""
    while [ "$#" -gt 0 ]; do case "$1" in --jq) q="$2"; shift ;; --paginate) paginate=1 ;; esac; shift; done
    printf '%s' "${BASE_WF:-"{\"workflow_runs\":[]}"}" | jq -r "$q"
    [ -z "$paginate" ] || [ -z "${BASE_WF_PAGE2:-}" ] || printf '%s' "$BASE_WF_PAGE2" | jq -r "$q" ;;
  *update-branch*) [ -z "${UB_NET:-}" ] || { echo "dial tcp 192.0.2.1:443: i/o timeout" >&2; exit 1; } ;;
  *check-runs*)
    [ -z "${BASE_NET:-}" ] || { echo "error connecting to api.github.com" >&2; exit 1; }
    [ -z "${BASE_LOOKUP_FAIL:-}" ] || exit 1
    q="" paginate=""
    while [ "$#" -gt 0 ]; do
      case "$1" in --jq) q="$2"; shift ;; --paginate) paginate=1 ;; esac; shift
    done
    printf '%s' "${BASE_RUNS:-"{\"check_runs\":[]}"}" | jq -r "$q"
    [ -z "$paginate" ] || [ -z "${BASE_PAGE2:-}" ] || printf '%s' "$BASE_PAGE2" | jq -r "$q" ;;
  *check-suites*)
    [ -z "${SUITE_LOOKUP_FAIL:-}" ] || exit 1
    q=""
    while [ "$#" -gt 0 ]; do case "$1" in --jq) q="$2"; shift ;; esac; shift; done
    printf '%s' "${BASE_SUITES:-"{\"check_suites\":[]}"}" | jq -r "$q" ;;
  *mergeStateStatus*)
    n=$(cat "$T_DIR/mss_n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$T_DIR/mss_n"
    s=$(sed -n "${n}p" "$MSS_PLAN" 2>/dev/null); echo "${s:-CLEAN}" ;;
  *"pr merge"*) [ -z "${MERGE_FAIL:-}" ] || { echo "${MERGE_ERR:-the base branch policy prohibits the merge}" >&2; exit 1; } ;;
  *"pr view"*)
    [ -z "${STATE_NET:-}" ] || { echo "dial tcp 192.0.2.1:443: i/o timeout" >&2; exit 1; }
    echo "$GH_STATE" ;;
esac
exit 0
EOF
chmod +x "$T/gate" "$T/gh"

run() {  # run <plan lines...>; sets OUT, RC (NO_ADMIN=1 runs without --admin)
  local admin="--admin"; [ -z "${NO_ADMIN:-}" ] || admin=""
  rm -f "$T/calls" "$T/gate_n" "$T/mss_n"
  printf '%s\n' "$@" > "$T/plan"
  printf '%s\n' "${MSS:-}" | tr ' ' '\n' > "$T/mss"
  OUT=$(env CALLS="$T/calls" T_DIR="$T" GATE_PLAN="$T/plan" GATE_SHA="$SHA" GH_STATE="${GH_STATE:-MERGED}" \
        MSS_PLAN="$T/mss" GATE_MERGE_POLL_S=0 GATE_MERGE_NET_SLEEP=0 \
        GATE_MERGE_GATE="$T/gate" GATE_MERGE_GH="$T/gh" bash "$SCRIPT" 42 --repo o/r ${admin:+"$admin"} ${EXTRA:+"$EXTRA"} 2>&1)
  RC=$?
}
calls() { cat "$T/calls" 2>/dev/null; }

run green
if [ "$RC" = 0 ] && calls | grep -q "gh pr merge 42 --repo o/r --squash --match-head-commit $SHA --admin" \
   && printf '%s' "$OUT" | grep -q "MERGED"; then
  ok "green: merges only the gated commit, reports MERGED"
else
  bad "green: rc=$RC calls=$(calls) out=$OUT"
fi

# A caller that proved one head pins it: a push between the proof and the gate must stop, not
# merge the new head.
export GATE_MERGE_EXPECT_HEAD=feedfacefeedfacefeedfacefeedfacefeedface
run green
if [ "$RC" = 1 ] && ! calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "head moved after the proof"; then
  ok "expected head differs: stops, no merge"
else
  bad "expected head differs: rc=$RC calls=$(calls) out=$OUT"
fi
export GATE_MERGE_EXPECT_HEAD="$SHA"
run green
if [ "$RC" = 0 ] && calls | grep -q "gh pr merge 42 --repo o/r --squash --match-head-commit $SHA"; then
  ok "expected head matches: merges"
else
  bad "expected head matches: rc=$RC calls=$(calls) out=$OUT"
fi
# A short or upper-case SHA can never equal the gate's full head: refuse it before any gate run.
export GATE_MERGE_EXPECT_HEAD=1234567
run green
if [ "$RC" = 4 ] && ! calls | grep -q "^gate " && printf '%s' "$OUT" | grep -q "full 40-character"; then
  ok "short expected head: usage stop before the gate"
else
  bad "short expected head: rc=$RC calls=$(calls) out=$OUT"
fi
unset GATE_MERGE_EXPECT_HEAD

run behind green
if [ "$RC" = 0 ] && calls | grep -q "gh pr update-branch 42 --repo o/r" \
   && [ "$(calls | grep -c '^gate ')" = 2 ] && calls | grep -q "gh pr merge"; then
  ok "behind once: updates the branch, gates again, merges"
else
  bad "behind once: rc=$RC calls=$(calls)"
fi

# GitHub needs a moment after `update-branch`: it reports BEHIND / UNKNOWN before CLEAN. The script
# must wait for that before it gates again (otherwise the re-gate runs at once and sees the old state).
MSS="BEHIND UNKNOWN CLEAN" run behind green
if [ "$RC" = 0 ] && [ "$(calls | grep -c 'mergeStateStatus')" = 3 ] \
   && calls | awk '/update-branch/{u=NR} /mergeStateStatus/{m=NR} /^gate /{g=NR} END{exit !(u<m && m<g)}'; then
  ok "after the update: waits until GitHub stops reporting BEHIND, then gates again"
else
  bad "wait after update: rc=$RC calls=$(calls)"
fi

# A busy main moves again while the restarted checks run (a single update can lose that race).
run behind behind behind green
if [ "$RC" = 0 ] && [ "$(calls | grep -c 'update-branch')" = 3 ] && [ "$(calls | grep -c '^gate ')" = 4 ] \
   && calls | grep -q "gh pr merge"; then
  ok "behind three times: three updates, then merges"
else
  bad "behind three times: rc=$RC calls=$(calls)"
fi

run behind behind behind behind green
if [ "$RC" != 0 ] && ! calls | grep -q "gh pr merge" && [ "$(calls | grep -c 'update-branch')" = 3 ] \
   && printf '%s' "$OUT" | grep -q "kept moving"; then
  ok "behind past the cap: three updates only, no merge, STOP"
else
  bad "behind past the cap: rc=$RC calls=$(calls) out=$OUT"
fi

run behind red
if [ "$RC" != 0 ] && ! calls | grep -q "gh pr merge" && [ "$(calls | grep -c 'update-branch')" = 1 ] \
   && printf '%s' "$OUT" | grep -q "not green after the update"; then
  ok "red after an update: no further update, no merge, STOP"
else
  bad "red after update: rc=$RC calls=$(calls) out=$OUT"
fi

run red
if [ "$RC" != 0 ] && ! calls | grep -q "gh pr merge" && ! calls | grep -q "update-branch" \
   && printf '%s' "$OUT" | grep -q "STOP"; then
  ok "red: no update, no merge, STOP"
else
  bad "red: rc=$RC calls=$(calls) out=$OUT"
fi

# Strict up-to-date checks are off on a repo: a PR can be green against an
# older main and still land on a main that has since gone red. Check the base right before the merge.
runs() {  # runs <name>=<conclusion>...: a check-runs page; "null" = still running
  local out="" r c
  for r in "$@"; do
    c=${r#*=}; [ "$c" = null ] || c="\"$c\""
    out="$out${out:+,}{\"name\":\"${r%%=*}\",\"conclusion\":$c}"
  done
  printf '{"check_runs":[%s]}' "$out"
}
RED_MAIN=$(runs lint=success ci=failure)

BASE_RUNS="$RED_MAIN" run green
if [ "$RC" != 0 ] && ! calls | grep -q "gh pr merge" \
   && calls | grep -q "repos/o/r/commits/cccccccccccccccccccccccccccccccccccccccc/check-runs" \
   && printf '%s' "$OUT" | grep -q "STOP: the base branch main is red (ci)"; then
  ok "red base: no merge, STOP names the failed check"
else
  bad "red base: rc=$RC calls=$(calls) out=$OUT"
fi

for c in timed_out startup_failure; do
  BASE_RUNS=$(runs ci="$c") run green
  if [ "$RC" != 0 ] && ! calls | grep -q "gh pr merge"; then ok "base check $c: red, no merge"
  else bad "base check $c: rc=$RC out=$OUT"; fi
done

for c in success cancelled null; do
  BASE_RUNS=$(runs ci="$c") run green
  if [ "$RC" = 0 ] && calls | grep -q "gh pr merge"; then ok "base check $c: not red, merges"
  else bad "base check $c: rc=$RC out=$OUT"; fi
done

BASE_RUNS=$(runs lint=success) BASE_PAGE2=$(runs ci=failure) run green
if [ "$RC" != 0 ] && ! calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "red (ci)"; then
  ok "failed check on page 2: red, no merge"
else
  bad "page 2: rc=$RC calls=$(calls) out=$OUT"
fi

BASE_RUNS=$(runs a=failure b=timed_out) BASE_PAGE2=$(runs a=failure) run green
if printf '%s' "$OUT" | grep -q "red (a, b)"; then ok "several failed checks: each named once"
else bad "several failed: out=$OUT"; fi

# A workflow that fails before it starts a job (an invalid workflow file, a startup failure)
# leaves no failed check run, only a failed check suite (an automated review flagged this).
suites() {  # suites <app>=<conclusion>...; "null" = not run
  local out="" r c
  for r in "$@"; do
    c=${r#*=}; [ "$c" = null ] || c="\"$c\""
    out="$out${out:+,}{\"app\":{\"name\":\"${r%%=*}\"},\"conclusion\":$c}"
  done
  printf '{"check_suites":[%s]}' "$out"
}

BASE_SUITES=$(suites "Travis CI=null" "GitHub Actions=startup_failure") run green
if [ "$RC" != 0 ] && ! calls | grep -q "gh pr merge" && calls | grep -q "repos/o/r/commits/cccccccccccccccccccccccccccccccccccccccc/check-suites" \
   && printf '%s' "$OUT" | grep -q "red (GitHub Actions)"; then
  ok "failed check suite with no check run: red, no merge"
else
  bad "suite only: rc=$RC calls=$(calls) out=$OUT"
fi

BASE_SUITES=$(suites "Travis CI=null" "GitHub Actions=success") run green
if [ "$RC" = 0 ] && calls | grep -q "gh pr merge"; then ok "suites never run or green: merges"
else bad "suites green: rc=$RC out=$OUT"; fi

SUITE_LOOKUP_FAIL=1 run green
if [ "$RC" = 0 ] && calls | grep -q "gh pr merge" \
   && printf '%s' "$OUT" | grep -q "could not read the checks of the base branch"; then
  ok "suite lookup fails: warns, still merges"
else
  bad "suite lookup fail: rc=$RC out=$OUT"
fi

BASE_RUNS="$RED_MAIN" EXTRA="--allow-red-base" run green
if [ "$RC" = 0 ] && calls | grep -q "gh pr merge 42 --repo o/r --squash --match-head-commit $SHA --admin" \
   && printf '%s' "$OUT" | grep -q "allowed by --allow-red-base"; then
  ok "red base with --allow-red-base: merges, says why"
else
  bad "allow red base: rc=$RC calls=$(calls) out=$OUT"
fi

run green
if calls | awk '/^gate /{g=NR} /check-runs/{c=NR} /gh pr merge/{m=NR} END{exit !(g<c && c<m)}'; then
  ok "green base: the base check runs after the gate and before the merge"
else
  bad "base check order: calls=$(calls)"
fi

BASE_LOOKUP_FAIL=1 run green
if [ "$RC" = 0 ] && calls | grep -q "gh pr merge" \
   && printf '%s' "$OUT" | grep -q "could not read the checks of the base branch"; then
  ok "base lookup fails: warns, still merges"
else
  bad "base lookup fail: rc=$RC calls=$(calls) out=$OUT"
fi

MERGE_FAIL=1 NO_ADMIN=1 run green
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q "STOP: gh pr merge refused" \
   && printf '%s' "$OUT" | grep -q "HINT: .*re-run with --admin" \
   && printf '%s' "$OUT" | grep -q "base branch policy prohibits"; then
  ok "policy refusal without --admin: STOP plus the --admin hint, gh error shown"
else
  bad "refused no-admin: rc=$RC out=$OUT"
fi

MERGE_FAIL=1 run green
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q "STOP: gh pr merge refused" \
   && ! printf '%s' "$OUT" | grep -q "HINT:"; then
  ok "merge refused with --admin: STOP, no hint"
else
  bad "refused admin: rc=$RC out=$OUT"
fi

MERGE_FAIL=1 NO_ADMIN=1 MERGE_ERR="Pull request is not mergeable: the merge commit cannot be cleanly created" run green
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q "STOP: gh pr merge refused" \
   && ! printf '%s' "$OUT" | grep -q "HINT:"; then
  ok "conflict refusal without --admin: STOP, no hint"
else
  bad "refused conflict: rc=$RC out=$OUT"
fi

rm -f "$T/calls" "$T/gate_n" "$T/mss_n"; printf 'green\n' > "$T/plan"; : > "$T/mss"
OUT=$(env CALLS="$T/calls" T_DIR="$T" GATE_PLAN="$T/plan" GATE_SHA="$SHA" GH_STATE=MERGED MSS_PLAN="$T/mss" \
      GATE_MERGE_POLL_S=0 MERGE_FAIL=1 GATE_MERGE_GATE="$T/gate" GATE_MERGE_GH="$T/gh" \
      bash "$SCRIPT" 42 --repo o/r 2>/dev/null | tail -n 1)
case "$OUT" in
  "STOP: gh pr merge refused"*) ok "policy refusal: STOP is the last stdout line" ;;
  *) bad "last stdout line: $OUT" ;;
esac

# End to end with the REAL pr-checks-green.sh: a repo with no CI whose base requires no checks
# (otherwise the gate waits out its timeout).
# Stub gh: NC_RULES = the branch rules JSON ("fail" = the API errors), NC_BRANCH = branch JSON.
cat > "$T/gh_nc" <<'EOF'
#!/usr/bin/env bash
echo "gh $*" >> "$CALLS"
case "$*" in
  *"--json state"*) echo MERGED ;;
  *"--json url,baseRefName"*) echo "https://github.com/o/r/pull/42 main" ;;
  *"--json url,headRefOid"*)
    [ -z "${NC_NET:-}" ] || { echo 'Post "https://api.github.com/graphql": dial tcp 192.0.2.1:443: i/o timeout' >&2; exit 1; }
    printf '{"url":"https://github.com/o/r/pull/42","headRefOid":"%s","baseRefName":"main","mergeStateStatus":"CLEAN","statusCheckRollup":[]}\n' "$GATE_SHA" ;;
  *check-runs*) echo ;;
  *check-suites*) echo ;;
  *"actions/runs"*) echo '{"workflow_runs":[]}' ;;
  *"rules/branches"*) [ "${NC_RULES:-[]}" != fail ] || { echo "HTTP 500: boom" >&2; exit 1; }; echo "${NC_RULES:-[]}" ;;
  *"repos/o/r/branches/main"*) if [ -n "${NC_BRANCH:-}" ]; then echo "$NC_BRANCH"; else echo '{"protection":{"enabled":false}}'; fi ;;
esac
exit 0
EOF
chmod +x "$T/gh_nc"
nc_run() {  # nc_run [wait seconds]; sets OUT, RC; real gate, 2 second limit
  rm -f "$T/calls"
  OUT=$(env CALLS="$T/calls" GATE_SHA="$SHA" GATE_MERGE_GH="$T/gh_nc" PR_CHECKS_GH="$T/gh_nc" \
        PR_CHECKS_INTERVAL=0.2 PR_CHECKS_NONE_SETTLE=0 PR_CHECKS_WAIT_S="${1:-2}" PR_CHECKS_NET_SLEEP=0 \
        bash "$SCRIPT" 42 --repo o/r 2>&1)
  RC=$?
}

nc_run 20
if [ "$RC" = 0 ] && calls | grep -q "gh pr merge 42 --repo o/r --squash --match-head-commit $SHA" \
   && ! calls | grep -q -- "--admin" \
   && printf '%s' "$OUT" | grep -q "GREEN: no checks configured on o/r; base requires none" \
   && printf '%s' "$OUT" | grep -q "MERGED 42"; then
  ok "no checks, base requires none, CLEAN: merges the gated commit, no --admin"
else
  bad "no checks, none required: rc=$RC calls=$(calls) out=$OUT"
fi

NC_RULES='[{"type":"required_status_checks","parameters":{"required_status_checks":[{"context":"build"}]}}]' nc_run
if [ "$RC" != 0 ] && ! calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "build: REQUIRED, NOT REPORTED YET"; then
  ok "no checks yet but the base requires one: keeps waiting, no merge"
else
  bad "required check missing: rc=$RC calls=$(calls) out=$OUT"
fi

NC_RULES=fail nc_run
if [ "$RC" != 0 ] && ! calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "rules/branches/main failed"; then
  ok "rules API error: no merge, clear message"
else
  bad "rules API error: rc=$RC calls=$(calls) out=$OUT"
fi

GH_STATE=OPEN run green
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q "STOP"; then ok "merge not confirmed: STOP, non-zero"; else bad "unconfirmed: rc=$RC out=$OUT"; fi

OUT=$(env GATE_MERGE_GATE="$T/gate" GATE_MERGE_GH="$T/gh" bash "$SCRIPT" 2>&1); RC=$?
if [ "$RC" = 4 ]; then ok "no PR argument: usage, exit 4"; else bad "usage rc=$RC"; fi

# Network errors: exit 5, never "checks are not green", never a blind merge.
run network
if [ "$RC" = 5 ] && ! calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "^STOP: NETWORK" \
   && ! printf '%s' "$OUT" | grep -q "checks are not green"; then
  ok "gate network stop: exit 5, NETWORK, no merge"
else
  bad "gate network stop: rc=$RC calls=$(calls) out=$OUT"
fi
MERGE_FAIL=1 MERGE_ERR="dial tcp 192.0.2.1:443: i/o timeout" GH_STATE=MERGED run green
if [ "$RC" = 0 ] && printf '%s' "$OUT" | grep -q "^MERGED 42" \
   && [ "$(calls | grep -c "gh pr merge")" = 1 ] \
   && calls | grep -q "gh pr merge 42 --repo o/r --squash --match-head-commit $SHA"; then
  ok "merge call network error, PR is MERGED: reports MERGED"
else
  bad "merge network, merged: rc=$RC out=$OUT"
fi
MERGE_FAIL=1 MERGE_ERR="dial tcp 192.0.2.1:443: i/o timeout" GH_STATE=MERGED EXTRA=--delete-branch run green
if [ "$RC" = 0 ] && printf '%s' "$OUT" | grep -q "check that the head branch was deleted"; then
  ok "merged after a network error with --delete-branch: warns to check the branch"
else
  bad "merge network, delete-branch: rc=$RC out=$OUT"
fi
unset EXTRA
MERGE_FAIL=1 MERGE_ERR="dial tcp 192.0.2.1:443: i/o timeout" GH_STATE=OPEN run green
if [ "$RC" = 5 ] && printf '%s' "$OUT" | grep -q "the PR is 'OPEN', not merged"; then
  ok "merge call network error, PR still OPEN: exit 5"
else
  bad "merge network, open: rc=$RC out=$OUT"
fi
MERGE_FAIL=1 MERGE_ERR="the base branch policy prohibits the merge" GH_STATE=OPEN run green
if [ "$RC" = 1 ] && printf '%s' "$OUT" | grep -q "gh pr merge refused"; then
  ok "a policy refusal is not treated as a network error"
else
  bad "policy refusal: rc=$RC out=$OUT"
fi
STATE_NET=1 run green
if [ "$RC" = 5 ] && printf '%s' "$OUT" | grep -q "state could not be read" \
   && [ "$(calls | grep -c -- '--json state')" = 5 ]; then
  ok "MERGED read-back network error: 5 tries, then exit 5"
else
  bad "state network: rc=$RC calls=$(calls) out=$OUT"
fi
unset STATE_NET MERGE_FAIL MERGE_ERR
BASE_NET=1 run green
if [ "$RC" = 5 ] && ! calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "reading the checks of the base branch"; then
  ok "base-branch checks unreadable on the network: exit 5, no merge (never skips the red-base check)"
else
  bad "base network: rc=$RC calls=$(calls) out=$OUT"
fi
unset BASE_NET
UB_NET=1 run behind green
if [ "$RC" = 5 ] && ! calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "update-branch hit a network error" \
   && [ "$(calls | grep -c "update-branch")" = 1 ]; then
  ok "update-branch network error: exit 5, not retried, no merge"
else
  bad "update-branch network: rc=$RC calls=$(calls) out=$OUT"
fi
unset UB_NET
NC_NET=1 nc_run
if [ "$RC" = 5 ] && ! calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "STOP: NETWORK: gh pr view 42" \
   && printf '%s' "$OUT" | grep -q "^STOP: NETWORK: GitHub could not be reached while gating"; then
  ok "end to end: the real gate's NETWORK stop reaches gate-merge as exit 5"
else
  bad "end to end network: rc=$RC calls=$(calls) out=$OUT"
fi
unset NC_NET


# A crashed Dependabot updater run on the base commit is not CI (a failed dependency update can make
# main read red as "Dependabot, GitHub Actions" while ci is green).
DEP_WF='{"workflow_runs":[{"name":"pip in /app for examplepkg - Update #1","event":"dynamic","path":"dynamic/dependabot/dependabot-updates","check_suite_id":111}]}'
DEP_RUN='{"name":"Dependabot","conclusion":"failure","check_suite":{"id":111}}'
DEP_SUITE='{"id":111,"conclusion":"failure","app":{"name":"GitHub Actions"}}'
CI_RUN='{"name":"ci","conclusion":"failure","check_suite":{"id":222}}'
CI_SUITE='{"id":222,"conclusion":"failure","app":{"name":"GitHub Actions"}}'
BASE_WF="$DEP_WF" BASE_RUNS="{\"check_runs\":[$DEP_RUN]}" BASE_SUITES="{\"check_suites\":[$DEP_SUITE]}" run green
if [ "$RC" = 0 ] && calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "ignored 1 Dependabot updater run"; then
  ok "a failed Dependabot updater run only: not a red base, merges, says so"
else
  bad "dependabot only: rc=$RC calls=$(calls) out=$OUT"
fi
BASE_WF="$DEP_WF" BASE_RUNS="{\"check_runs\":[$DEP_RUN,$CI_RUN]}" BASE_SUITES="{\"check_suites\":[$DEP_SUITE,$CI_SUITE]}" run green
if [ "$RC" = 1 ] && ! calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "is red (GitHub Actions, ci)"; then
  ok "Dependabot updater plus a real CI failure: still red, names only the CI check"
else
  bad "dependabot plus CI: rc=$RC calls=$(calls) out=$OUT"
fi
OTHER_WF='{"workflow_runs":[{"name":"Dependabot","event":"push","path":".github/workflows/dependabot.yml","check_suite_id":111}]}'
BASE_WF="$OTHER_WF" BASE_RUNS="{\"check_runs\":[$DEP_RUN]}" BASE_SUITES="{\"check_suites\":[$DEP_SUITE]}" run green
if [ "$RC" = 1 ] && ! calls | grep -q "gh pr merge"; then
  ok "a repo workflow named Dependabot is CI: a failure stays red"
else
  bad "workflow named Dependabot: rc=$RC calls=$(calls) out=$OUT"
fi
BASE_WF_NET=1 BASE_WF="$DEP_WF" run green
if [ "$RC" = 5 ] && ! calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "^STOP: NETWORK"; then
  ok "base Actions runs unreadable on the network: exit 5, no merge"
else
  bad "runs network: rc=$RC calls=$(calls) out=$OUT"
fi
unset BASE_WF_NET
PAGE1_WF='{"workflow_runs":[{"name":"CI","event":"push","path":".github/workflows/ci.yml","check_suite_id":333}]}'
BASE_WF="$PAGE1_WF" BASE_WF_PAGE2="$DEP_WF" BASE_RUNS="{\"check_runs\":[$DEP_RUN]}" BASE_SUITES="{\"check_suites\":[$DEP_SUITE]}" run green
if [ "$RC" = 0 ] && calls | grep -q "gh pr merge" && printf '%s' "$OUT" | grep -q "ignored 1 Dependabot updater run"; then
  ok "a Dependabot updater run on page 2 of the Actions runs is still left out"
else
  bad "page 2 updater: rc=$RC calls=$(calls) out=$OUT"
fi
BASE_SHA=dddddddddddddddddddddddddddddddddddddddd run green
if calls | grep -q "commits/dddddddddddddddddddddddddddddddddddddddd/check-runs" \
   && calls | grep -q "commits/dddddddddddddddddddddddddddddddddddddddd/check-suites" \
   && calls | grep -q "actions/runs?head_sha=dddddddddddddddddddddddddddddddddddddddd"; then
  ok "the base checks and runs are read for one commit (the base SHA)"
else
  bad "base sha: calls=$(calls)"
fi
unset BASE_SHA

echo ""
if [ "$FAILS" = 0 ]; then echo "gate-merge: PASS"; exit 0; fi
echo "gate-merge: $FAILS FAILED"; exit 1
