#!/usr/bin/env bash
# Tests for stale-inventory.sh: one fixture repo with a branch per class, a fake gh on PATH.
# shellcheck disable=SC2015  # pass() cannot fail, so "A && pass || fail" is safe here.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SCRIPT="$(dirname "$DIR")/stale-inventory.sh"
T="$(mktemp -d /tmp/stale-inventory-tests.XXXXXX)"
trap 'rm -rf -- "$T"' EXIT
export HOME="$T/home" GIT_CONFIG_NOSYSTEM=1
mkdir -p "$HOME"
fails=0
pass() { echo "ok   - $1"; }
fail() { echo "FAIL - $1" >&2; fails=$((fails + 1)); }

NOW=$(date +%s)
ago() { echo $((NOW - ${1} * 86400)); }
iso() { jq -nr --argjson e "${1}" '$e | todate'; }

# commit <days-ago> <email> <message>: commit staged changes with back-dated author+committer.
commit() {
  local when; when="@$(ago "${1}") +0000"
  GIT_AUTHOR_DATE="$when" GIT_COMMITTER_DATE="$when" \
    git -c user.name=t -c user.email="${2}" commit -q -m "${3}"
}

# --- fixture repo -------------------------------------------------------------
git init -q --bare -b main "$T/origin.git"
git clone -q "$T/origin.git" "$T/work" 2>/dev/null
cd "$T/work" || exit 1
git config user.email me@example.com
git config user.name me
printf 'one\ntwo\nthree\nfour\nfive\nsix\nseven\n' > s.txt
echo base > c.txt
printf 'A\000x' > bin.dat
git add . && commit 100 me@example.com base
git push -q origin main

# old-merged: ancestor of main
git checkout -q -b old-merged
echo m > merged.txt && git add merged.txt && commit 60 me@example.com merged
git checkout -q main && git merge -q --ff-only old-merged

# old-squashed: same content as a later main commit, not an ancestor
git checkout -q -b old-squashed main
echo sq > squashed.txt && git add squashed.txt && commit 60 me@example.com squashed
git checkout -q main
echo sq > squashed.txt && git add squashed.txt && commit 59 me@example.com "squash of old-squashed"

# old-clean: new file, clean merge, has PR #11
git checkout -q -b old-clean main
echo new > clean.txt && git add clean.txt && commit 50 me@example.com clean

# old-conflict: someone else's, conflicts with main
git checkout -q -b old-conflict main
echo theirs > c.txt && git add c.txt && commit 45 other@example.com conflict

# old-superseded: edits s.txt line 1; main later edits s.txt line 7 (clean merge, same file)
git checkout -q -b old-superseded main
sed 's/^one$/ONE/' s.txt > s.tmp && mv s.tmp s.txt && git add s.txt && commit 40 me@example.com superseded

# fresh-branch: inside the window
git checkout -q -b fresh-branch main
echo f > fresh.txt && git add fresh.txt && commit 2 me@example.com fresh

# old-but-pr-active: old tip, PR #12 updated yesterday
git checkout -q -b old-but-pr-active main
echo a > active.txt && git add active.txt && commit 60 me@example.com active

# old-staging: PR #14 targets staging, not main
git checkout -q -b old-staging main
echo st > staging.txt && git add staging.txt && commit 40 me@example.com staging

# old-binary: binary file changed on both sides (a real conflict)
git checkout -q -b old-binary main~0
printf 'B\000x' > bin.dat && git add bin.dat && commit 45 me@example.com "binary branch"

# old-ahead: pushed, then a local commit never pushed
git checkout -q -b old-ahead main
echo ah > ahead.txt && git add ahead.txt && commit 40 me@example.com ahead

# old-other: someone else's branch, no PR
git checkout -q -b old-other main
echo o > other.txt && git add other.txt && commit 45 other@example.com other

# backup/old-main and sync-backup/old-main-x: backup refs, always kept
git checkout -q -b backup/old-main main
echo bk > backup.txt && git add backup.txt && commit 50 me@example.com backup
git checkout -q -b sync-backup/old-main-x main
echo sbk > sync-backup.txt && git add sync-backup.txt && commit 50 me@example.com sync-backup

# owner variants: GitHub no-reply email, case-variant email, case-variant PR login (#17)
git checkout -q -b old-noreply main
echo nr > noreply.txt && git add noreply.txt && commit 50 12345+me-login@users.noreply.github.com noreply
git checkout -q -b old-case main
echo cs > case.txt && git add case.txt && commit 50 ME@Example.COM case
git checkout -q -b old-noreply-plain main
echo np > noreply-plain.txt && git add noreply-plain.txt && commit 50 me-login@users.noreply.github.com noreply-plain
git checkout -q -b old-notme main
echo nm > notme.txt && git add notme.txt && commit 50 99999+notme-login@users.noreply.github.com notme
git checkout -q -b old-pr-case main
echo pc > pr-case.txt && git add pr-case.txt && commit 50 other@example.com pr-case

# wt-branch: checked out in a worktree
git checkout -q -b wt-branch main
echo w > wt.txt && git add wt.txt && commit 40 me@example.com wt

git checkout -q main
sed 's/^seven$/SEVEN/' s.txt > s.tmp && mv s.tmp s.txt && git add s.txt && commit 30 me@example.com "main edits s.txt"
echo c2 > c.txt && git add c.txt && commit 30 me@example.com "main edits c.txt"
printf 'C\000x' > bin.dat && git add bin.dat && commit 30 me@example.com "main edits bin.dat"

git push -q origin main old-merged old-squashed old-clean old-conflict old-superseded \
  fresh-branch old-but-pr-active old-staging wt-branch old-binary old-ahead old-other backup/old-main sync-backup/old-main-x \
  old-noreply old-case old-pr-case old-noreply-plain old-notme
git push -q origin "$(git rev-list --max-parents=0 main):refs/heads/staging"
git push -q origin "$(git rev-list --max-parents=0 main):refs/heads/develop"
git push -q origin "$(git rev-list --max-parents=0 main):refs/heads/release/2026-q3"
git push -q origin "$(git rev-list --max-parents=0 main):refs/heads/production"
# pruned-branch: known locally as origin/pruned-branch, then deleted on the remote (merged PR, branch removed)
git push -q origin "$(git rev-list --max-parents=0 main):refs/heads/pruned-branch"
git -C "$T/origin.git" branch -q -D pruned-branch
git remote set-head origin main >/dev/null

git checkout -q old-ahead
echo ah2 >> ahead.txt && git add ahead.txt && commit 35 me@example.com "ahead, unpushed"

# backup/local-only: a backup branch that was never pushed
git checkout -q -b backup/local-only main
echo bl > backup-local.txt && git add backup-local.txt && commit 50 me@example.com backup-local
git checkout -q old-ahead

# local-only: never pushed
git checkout -q -b local-only main
echo l > local.txt && git add local.txt && commit 40 me@example.com local
git checkout -q main
git worktree add -q "$T/wt" wt-branch

# --- fake gh ------------------------------------------------------------------
FAKE="$T/fakegh"; mkdir -p "$FAKE/bin"
export FAKE_GH="$FAKE"
cat > "$FAKE/bin/gh" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$FAKE_GH/calls.log"
[ -n "${FAKE_GH_FAIL:-}" ] && { echo "fake gh: not logged in" >&2; exit 1; }
case "$*" in
  "api user") cat "$FAKE_GH/user.json" ;;
  "api repos/{owner}/{repo}") cat "$FAKE_GH/repo.json" ;;
  "pr list --state open --limit 500 --json "*) cat "$FAKE_GH/prs.json" ;;
  *) echo "fake gh: unexpected call: $*" >&2; exit 1 ;;
esac
EOF
chmod +x "$FAKE/bin/gh"
export PATH="$FAKE/bin:$PATH"
echo '{"login":"me-login"}' > "$FAKE/user.json"
echo '{"permissions":{"admin":true}}' > "$FAKE/repo.json"
cat > "$FAKE/prs.json" <<EOF
[
 {"number":11,"headRefName":"old-clean","author":{"login":"me-login"},"updatedAt":"$(iso "$(ago 50)")","isCrossRepository":false,"baseRefName":"main"},
 {"number":12,"headRefName":"old-but-pr-active","author":{"login":"me-login"},"updatedAt":"$(iso "$(ago 1)")","isCrossRepository":false,"baseRefName":"main"},
 {"number":13,"headRefName":"main","author":{"login":"forker"},"updatedAt":"$(iso "$(ago 90)")","isCrossRepository":true,"baseRefName":"main"},
 {"number":14,"headRefName":"old-staging","author":{"login":"me-login"},"updatedAt":"$(iso "$(ago 40)")","isCrossRepository":false,"baseRefName":"staging"},
 {"number":16,"headRefName":"gone-branch","author":{"login":""},"updatedAt":"$(iso "$(ago 70)")","isCrossRepository":false,"baseRefName":"main"},
 {"number":17,"headRefName":"old-pr-case","author":{"login":"ME-LOGIN"},"updatedAt":"$(iso "$(ago 50)")","isCrossRepository":false,"baseRefName":"main"},
 {"number":15,"headRefName":"old-conflict","author":{"login":"other-login"},"updatedAt":"$(iso "$(ago 45)")","isCrossRepository":false,"baseRefName":"main"}
]
EOF

refs_snapshot() { { git -C "$T/work" for-each-ref --format='%(refname) %(objectname)' refs/heads refs/tags; git -C "$T/origin.git" for-each-ref --format='%(refname) %(objectname)'; } | sort; }
BEFORE="$(refs_snapshot)"

# row <output> <ref>: the TSV row for that ref (column 2).
row() { printf '%s\n' "${1}" | awk -F'\t' -v r="${2}" '$2 == r'; }
col() { printf '%s\n' "${1}" | cut -f"${2}"; }
expect_row() { # expect_row <out> <ref> <kind> <class> <scope> <label>
  local r; r="$(row "${1}" "${2}")"
  if [ -z "$r" ]; then fail "${6}: no row for ${2}"; return; fi
  if [ "$(col "$r" 1)" = "${3}" ] && [ "$(col "$r" 6)" = "${4}" ] && [ "$(col "$r" 7)" = "${5}" ]; then pass "${6}"
  else fail "${6}: got [$r], want kind=${3} class=${4} scope=${5}"; fi
}
expect_absent() { if [ -z "$(row "${1}" "${2}")" ]; then pass "${3}"; else fail "${3}: ${2} listed"; fi; }

# --- default run (mine, 30 days) ----------------------------------------------
OUT="$(bash "$SCRIPT" --repo "$T/work" 2>"$T/err1")"; rc=$?
[ "$rc" -eq 0 ] && pass "default run exits 0" || fail "default run exit $rc: $(cat "$T/err1")"
echo "$OUT" | grep -q '^# repo=.* base=main me=me-login admin=- days=30 scope=mine' && pass "header line" || fail "header line: $(echo "$OUT" | head -1)"
printf '%s\n' "$OUT" | grep -q "$(printf '^KIND\tREF\tPR\tAUTHOR\tAGE_D\tCLASS\tSCOPE\tNOTE$')" && pass "column header" || fail "column header"
expect_row "$OUT" old-merged remote already-merged mine "ancestor = already-merged"
[ "$(col "$(row "$OUT" old-merged)" 5)" = "60" ] && pass "AGE in days from the tip" || fail "AGE for old-merged: $(col "$(row "$OUT" old-merged)" 5)"
expect_row "$OUT" old-other remote mergeable-now report-only "other's branch with no PR = report-only by default"
expect_absent "$OUT" pruned-branch "branch deleted on the remote is pruned, not listed"
expect_row "$OUT" old-squashed remote already-merged mine "squash-equivalent = already-merged"
expect_row "$OUT" old-clean pr mergeable-now mine "clean merge with PR = mergeable-now"
[ "$(col "$(row "$OUT" old-clean)" 3)" = "11" ] && pass "PR number shown" || fail "PR number for old-clean"
col "$(row "$OUT" old-clean)" 8 | grep -q 'read the diff' && fail "overlap note on non-overlapping work" || pass "no overlap note on clean work"
expect_row "$OUT" old-conflict pr needs-rebase report-only "other's conflict = needs-rebase, report-only by default"
[ "$(col "$(row "$OUT" old-conflict)" 4)" = "other-login" ] && pass "PR author shown" || fail "PR author for old-conflict"
expect_row "$OUT" old-superseded remote mergeable-now mine "same files changed on main = mergeable-now"
col "$(row "$OUT" old-superseded)" 8 | grep -q 'read the diff' && pass "overlap note" || fail "overlap note missing"
expect_row "$OUT" old-binary remote needs-rebase mine "binary conflict = needs-rebase"
printf '%s\n' "$OUT" | awk -F'\t' '$1 == "remote" && $2 == "old-ahead" && $6 == "mergeable-now"' | grep -q . \
  && pass "pushed part of old-ahead listed" || fail "remote old-ahead row missing"
printf '%s\n' "$OUT" | awk -F'\t' '$1 == "local" && $2 == "old-ahead"' | grep -q '1 commit(s) not on origin/old-ahead' \
  && pass "unpushed commits past the remote branch listed" || fail "local old-ahead row missing"
expect_row "$OUT" old-staging pr needs-human mine "PR base not default = needs-human"
expect_row "$OUT" wt-branch remote mergeable-now mine "worktree branch still classified"
col "$(row "$OUT" wt-branch)" 8 | grep -q 'checked out in a worktree' && pass "worktree note" || fail "worktree note missing"
expect_row "$OUT" local-only local mergeable-now mine "local-only branch listed"
expect_row "$OUT" "#13" pr-fork needs-human report-only "fork PR = needs-human"
[ "$(col "$(row "$OUT" "#13")" 8)" = "PR from a fork" ] && pass "fork note" || fail "fork note: $(col "$(row "$OUT" "#13")" 8)"
expect_row "$OUT" staging remote needs-human mine "staging = needs-human, not already-merged"
[ "$(col "$(row "$OUT" staging)" 8)" = "long-lived branch, keep" ] && pass "staging long-lived note" || fail "staging note: $(col "$(row "$OUT" staging)" 8)"
expect_row "$OUT" develop remote needs-human mine "develop = needs-human (long-lived)"
expect_row "$OUT" release/2026-q3 remote needs-human mine "release/* = needs-human (long-lived)"
expect_row "$OUT" production remote needs-human mine "production = needs-human (long-lived)"
[ "$(col "$(row "$OUT" production)" 8)" = "long-lived branch, keep" ] && pass "long-lived note without a PR base" || fail "production note: $(col "$(row "$OUT" production)" 8)"
expect_row "$OUT" old-noreply-plain remote mergeable-now mine "plain GitHub no-reply email = mine"
expect_row "$OUT" old-notme remote mergeable-now report-only "another user's no-reply email = report-only"
expect_row "$OUT" old-noreply remote mergeable-now mine "GitHub no-reply email of the gh login = mine"
expect_row "$OUT" old-case remote mergeable-now mine "case-variant email = mine"
expect_row "$OUT" old-pr-case pr mergeable-now mine "case-variant PR login = mine"
expect_row "$OUT" gone-branch pr needs-human report-only "PR head gone = needs-human"
r="$(row "$OUT" gone-branch)"
{ [ "$(col "$r" 4)" = "-" ] && [ "$(col "$r" 5)" = "70" ]; } && pass "empty PR author keeps columns aligned" || fail "empty author row: [$r]"
expect_row "$OUT" backup/old-main remote needs-human mine "backup/ branch = needs-human"
[ "$(col "$(row "$OUT" backup/old-main)" 8)" = "backup branch, keep" ] && pass "backup note" || fail "backup note: $(col "$(row "$OUT" backup/old-main)" 8)"
expect_row "$OUT" sync-backup/old-main-x remote needs-human mine "sync-backup/ branch = needs-human"
expect_row "$OUT" backup/local-only local needs-human mine "local-only backup branch = needs-human"
expect_absent "$OUT" fresh-branch "fresh branch hidden"
expect_absent "$OUT" old-but-pr-active "recent PR activity keeps an old branch fresh"
expect_absent "$OUT" main "base branch not listed"
echo "$OUT" | grep -q '^# fresh items hidden: 2$' && pass "fresh count footer" || fail "fresh footer: $(echo "$OUT" | tail -1)"
AGES="$(printf '%s\n' "$OUT" | grep -v '^#' | tail -n +2 | cut -f5)"
[ "$AGES" = "$(printf '%s\n' "$AGES" | sort -nr)" ] && pass "oldest first" || fail "sort order: $AGES"

# --- mixed-case identity: login and git email both mixed-case ---------------------
echo '{"login":"Me-Login"}' > "$FAKE/user.json"
git config user.email Me@Example.com
OUT="$(bash "$SCRIPT" --repo "$T/work" 2>/dev/null)"
expect_row "$OUT" old-noreply remote mergeable-now mine "mixed-case login: no-reply email = mine"
expect_row "$OUT" old-case remote mergeable-now mine "mixed-case git email: case-variant email = mine"
expect_row "$OUT" old-pr-case pr mergeable-now mine "mixed-case login: case-variant PR login = mine"
expect_row "$OUT" old-notme remote mergeable-now report-only "mixed-case login: other no-reply = report-only"
echo '{"login":"me-login"}' > "$FAKE/user.json"
git config user.email me@example.com

# --- --all with admin ----------------------------------------------------------
OUT="$(bash "$SCRIPT" --repo "$T/work" --all 2>/dev/null)"
echo "$OUT" | grep -q 'admin=true .*scope=all' && pass "admin header" || fail "admin header"
expect_row "$OUT" old-conflict pr needs-rebase other "--all + admin = others actionable"
expect_row "$OUT" old-other remote mergeable-now other "--all + admin = other's PR-less branch actionable"

# --- --all without admin -------------------------------------------------------
echo '{"permissions":{"admin":false}}' > "$FAKE/repo.json"
OUT="$(bash "$SCRIPT" --repo "$T/work" --all 2>/dev/null)"
expect_row "$OUT" old-conflict pr needs-rebase report-only "--all without admin = report-only"

# --- --days -------------------------------------------------------------------
OUT="$(bash "$SCRIPT" --repo "$T/work" --days 55 2>/dev/null)"
expect_row "$OUT" old-merged remote already-merged mine "--days 55 keeps 60-day item"
expect_absent "$OUT" old-clean "--days 55 hides 50-day item"
bash "$SCRIPT" --repo "$T/work" --days abc >/dev/null 2>&1; [ $? -eq 2 ] && pass "bad --days exits 2" || fail "bad --days"

# --- gh failing (not logged in, offline): branches still listed, warning shown ---
OUT="$(FAKE_GH_FAIL=1 bash "$SCRIPT" --repo "$T/work" 2>"$T/err2")"; rc=$?
[ "$rc" -eq 0 ] && pass "gh failing: exits 0" || fail "gh failing: exit $rc"
expect_row "$OUT" old-merged remote already-merged mine "gh failing: branches still classified"
grep -q 'WARN: could not list open PRs' "$T/err2" && pass "gh failing: warning" || fail "gh failing: no PR-list warning"
OUT="$(FAKE_GH_FAIL=1 bash "$SCRIPT" --repo "$T/work" --all 2>/dev/null)"
echo "$OUT" | grep -q 'admin=unknown' && pass "gh failing + --all: admin unknown" || fail "gh failing + --all: header $(echo "$OUT" | head -1)"
expect_row "$OUT" old-other remote mergeable-now report-only "gh failing + --all: others stay report-only"

# --- 500 open PRs: cut-off warning ----------------------------------------------
cp "$FAKE/prs.json" "$FAKE/prs.keep"
jq -n '[range(500) | {number: (. + 100), headRefName: "gone-\(.)", author: {login: "z"}, updatedAt: "2020-01-01T00:00:00Z", isCrossRepository: false, baseRefName: "main"}]' > "$FAKE/prs.json"
bash "$SCRIPT" --repo "$T/work" >/dev/null 2>"$T/err3"
grep -q 'cut off' "$T/err3" && pass "500 PRs: cut-off warning" || fail "500 PRs: no warning"
mv "$FAKE/prs.keep" "$FAKE/prs.json"

# --- read-only ----------------------------------------------------------------
[ "$BEFORE" = "$(refs_snapshot)" ] && pass "refs unchanged (no tag, delete, push)" || fail "refs changed"
if ! grep -q '^pr list' "$FAKE/calls.log" 2>/dev/null; then
  fail "gh pr list was never called"
elif grep -qvE -e '^api user$' -e '^api repos/\{owner\}/\{repo\}$' -e '^pr list --state open --limit 500 --json [a-zA-Z,]+$' "$FAKE/calls.log"; then
  fail "unexpected gh call: $(grep -vE -e '^api user$' -e '^api repos/\{owner\}/\{repo\}$' -e '^pr list --state open ' "$FAKE/calls.log")"
else pass "only read-only gh calls"; fi

if [ "$fails" -ne 0 ]; then echo "$fails test(s) failed" >&2; exit 1; fi
echo "all stale-inventory tests passed"
