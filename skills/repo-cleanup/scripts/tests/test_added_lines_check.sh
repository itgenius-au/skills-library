#!/usr/bin/env bash
# Tests for added-lines-check.sh: squash-merged work, a missing line, a moved line.
# shellcheck disable=SC2015  # pass() cannot fail, so "A && pass || fail" is safe here.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SCRIPT="$(dirname "$DIR")/added-lines-check.sh"
T="$(mktemp -d /tmp/added-lines-tests.XXXXXX)"
trap 'rm -rf -- "$T"' EXIT
export HOME="$T/home" GIT_CONFIG_NOSYSTEM=1
mkdir -p "$HOME"
fails=0
pass() { echo "ok   - $1"; }
fail() { echo "FAIL - $1" >&2; fails=$((fails + 1)); }
g() { git -c user.name=t -c user.email=t@example.com "$@"; }

git init -q --bare -b main "$T/origin.git"
git clone -q "$T/origin.git" "$T/work" 2>/dev/null
cd "$T/work" || exit 1
printf 'alpha\nbeta\ngamma\n' > a.txt
printf 'keep\n' > old.txt
g add . && g commit -q -m base && git push -q origin main
git remote set-head origin main >/dev/null

# squashed: two commits, one with a change that a later commit reverts in part
git checkout -q -b squashed main
printf 'alpha\nbeta\ngamma\n  new indented line\nsecond new line\n' > a.txt
g commit -q -am one
echo 'extra' > b.txt && git add b.txt && g commit -q -m two
# lost: one line never reaches main
git checkout -q -b lost main
printf 'only on the branch\nshared line\n' > c.txt && git add c.txt && g commit -q -m lost
# moved: its line ends up in another file on main
git checkout -q -b moved main
echo 'moved line' > m.txt && git add m.txt && g commit -q -m moved
# deleted: the file is deleted on main afterwards
git checkout -q -b deleted main
echo 'doomed line' > d.txt && git add d.txt && g commit -q -m deleted

# main: squash of `squashed` (different commit), `lost` minus one line, moved line elsewhere, d.txt removed
git checkout -q main
printf 'alpha\nbeta\ngamma\nnew indented line\nsecond new line\n' > a.txt
echo extra > b.txt
g add . && g commit -q -m "squash: squashed"
echo 'shared line' > c.txt
echo 'moved line' > elsewhere.txt
g add . && g commit -q -m "partial lost, moved elsewhere"
git push -q origin main
git fetch -q origin

out="$(bash "$SCRIPT" --repo "$T/work" squashed 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && grep -q 'squashed: added 3, missing 0, verdict landed' <<< "$out" && pass "squash-merged branch is landed (indentation ignored)" || fail "squashed: rc=$rc $out"

out="$(bash "$SCRIPT" --repo "$T/work" --show-missing lost 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q 'lost: added 2, missing 1, verdict MISSING' <<< "$out" && grep -q 'MISSING in c.txt: only on the branch' <<< "$out" \
  && pass "a line not on main is MISSING, exit 1, shown" || fail "lost: rc=$rc $out"

out="$(bash "$SCRIPT" --repo "$T/work" lost 2>&1)"
grep -q 'MISSING in' <<< "$out" && fail "missing lines shown without --show-missing" || pass "missing lines hidden without --show-missing"

out="$(bash "$SCRIPT" --repo "$T/work" moved 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && grep -q 'moved: added 1, missing 0, verdict landed' <<< "$out" && pass "a line moved to another file is landed" || fail "moved: rc=$rc $out"

out="$(bash "$SCRIPT" --repo "$T/work" deleted 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q 'deleted: added 1, missing 1, verdict MISSING' <<< "$out" && pass "a file absent on main counts as missing" || fail "deleted: rc=$rc $out"

out="$(bash "$SCRIPT" --repo "$T/work" --base origin/main squashed moved lost 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && [ "$(grep -c verdict <<< "$out")" -eq 3 ] && pass "several refs: one line each, exit 1 if any is missing" || fail "multi: rc=$rc $out"

out="$(bash "$SCRIPT" --repo "$T/work" no-such-ref 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && grep -q 'no-such-ref: ERROR cannot resolve ref' <<< "$out" && pass "unknown ref is an error, exit 2" || fail "bad ref: rc=$rc $out"

# a ref with no shared history, and a base that cannot be resolved
git checkout -q --orphan orphan && git rm -rfq . && echo unrelated > o.txt && git add o.txt && g commit -q -m orphan && git checkout -q main
out="$(bash "$SCRIPT" --repo "$T/work" orphan 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && grep -q 'orphan: ERROR no common history' <<< "$out" && ! grep -q landed <<< "$out" && pass "unrelated history: ERROR, exit 2" || fail "orphan: rc=$rc $out"
git init -q "$T/nobase" && ( cd "$T/nobase" && echo x > x.txt && git add . && g commit -q -m x )
out="$(bash "$SCRIPT" --repo "$T/nobase" HEAD 2>&1)"; rc=$?
[ "$rc" -ne 0 ] && grep -q 'cannot resolve the base branch' <<< "$out" && ! grep -q landed <<< "$out" && pass "no resolvable base: nonzero exit, nothing reported as landed" || fail "nobase: rc=$rc $out"
out="$(bash "$SCRIPT" --repo "$T/work" --base origin/nope squashed 2>&1)"; rc=$?
[ "$rc" -ne 0 ] && ! grep -q landed <<< "$out" && pass "--base that does not exist: nonzero exit" || fail "bad --base: rc=$rc $out"

# trivial lines: a lone fence or brace is not evidence either way
git checkout -q -b fenceonly main
printf '%s\n' '```' '}' '});' '];' '  ' > fence.md && git add fence.md && g commit -q -m fence
git checkout -q -b fenceplus main
printf '%s\n' '```' 'a real line that is not on main' > fence2.md && git add fence2.md && g commit -q -m fence2
git checkout -q main
out="$(bash "$SCRIPT" --repo "$T/work" --show-missing fenceonly fenceplus 2>&1)"; rc=$?
grep -q 'fenceonly: added 0, missing 0, verdict landed' <<< "$out" && grep -q 'fenceplus: added 1, missing 1, verdict MISSING' <<< "$out" && ! grep -q 'MISSING in fence2.md: ```' <<< "$out" \
  && pass "bare fence/brace lines are ignored; a real line still counts" || fail "trivial lines: rc=$rc $out"

# a --repo that is a subdirectory gives the same verdicts as the root
mkdir -p "$T/work/some/deeper/dir"
for r in squashed lost moved; do
  root="$(bash "$SCRIPT" --repo "$T/work" --show-missing "$r" 2>&1; echo "rc=$?")"
  sub="$(bash "$SCRIPT" --repo "$T/work/some/deeper/dir" --show-missing "$r" 2>&1; echo "rc=$?")"
  [ "$root" = "$sub" ] && pass "subdirectory --repo gives the root verdict for $r" || fail "subdir differs for $r: root=[$root] sub=[$sub]"
done
bash "$SCRIPT" --repo "$T/work/some/deeper/dir" lost >/dev/null 2>&1; [ $? -eq 1 ] && pass "subdirectory --repo still reports MISSING (exit 1)" || fail "subdir lost exit"
out="$(bash "$SCRIPT" --repo "$T" lost 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && pass "--repo outside any work tree: exit 2" || fail "outside repo: rc=$rc $out"

# changes with no added text line cannot be verified: never "landed"
git checkout -q -b binadd main
printf 'A\000B\000C' > blob.bin && git add blob.bin && g commit -q -m "binary"
git checkout -q -b modeonly main
chmod +x a.txt && git add a.txt && g commit -q -m "chmod +x"
git checkout -q -b delonly main
sed '/beta/d' a.txt > a.tmp && mv a.tmp a.txt && git add a.txt && g commit -q -m "delete a line"
git checkout -q main
for r in binadd:blob.bin modeonly:a.txt delonly:a.txt; do
  ref="${r%%:*}"; f="${r##*:}"
  out="$(bash "$SCRIPT" --repo "$T/work" --show-missing "$ref" 2>&1)"; rc=$?
  [ "$rc" -eq 1 ] && grep -q "$ref: added 0, missing 0, unverified 1, verdict UNVERIFIED" <<< "$out" && grep -q "UNVERIFIED $f" <<< "$out" && ! grep -q landed <<< "$out" \
    && pass "$ref: UNVERIFIED, exit 1, file listed, never landed" || fail "$ref: rc=$rc $out"
done
out="$(bash "$SCRIPT" --repo "$T/work" binadd 2>&1)"
grep -q 'UNVERIFIED a' <<< "$out" && fail "files listed without --show-missing" || pass "UNVERIFIED files are listed only with --show-missing"

# short lines still count: only lines with no letter or digit are ignored
git checkout -q -b shortline main
printf 'x=1\n' > short.txt && git add short.txt && g commit -q -m short
git checkout -q main
out="$(bash "$SCRIPT" --repo "$T/work" --show-missing shortline 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q 'shortline: added 1, missing 1, verdict MISSING' <<< "$out" && grep -q 'MISSING in short.txt: x=1' <<< "$out" \
  && pass "a short line (x=1) not on main is MISSING" || fail "short line: rc=$rc $out"

# git failures must never read as landed: a wrapper makes one subcommand fail
mkdir -p "$T/gitwrap"
REAL_GIT="$(command -v git)"; export REAL_GIT
cat > "$T/gitwrap/git" <<'EOS'
#!/usr/bin/env bash
for a in "$@"; do [ "$a" = "${FAIL_SUBCMD:-}" ] && { echo "wrapper: $a failed" >&2; exit 128; }; done
exec "$REAL_GIT" "$@"
EOS
chmod +x "$T/gitwrap/git"
for sub_ref in diff:squashed show:squashed ls-tree:squashed grep:moved merge-base:squashed; do
  sub="${sub_ref%%:*}"; r="${sub_ref##*:}"
  out="$(FAIL_SUBCMD="$sub" PATH="$T/gitwrap:$PATH" bash "$SCRIPT" --repo "$T/work" "$r" 2>&1)"; rc=$?
  [ "$rc" -eq 2 ] && grep -q 'ERROR' <<< "$out" && ! grep -q 'landed' <<< "$out" && pass "failing git $sub: ERROR, exit 2, never landed" || fail "git $sub failing: rc=$rc $out"
done
# an unreadable object (a branch blob removed from the object store) is an error too
BL="$(git rev-parse lost:c.txt)"; mv "$T/work/.git/objects/${BL:0:2}/${BL:2}" "$T/blob.saved"
out="$(bash "$SCRIPT" --repo "$T/work" lost 2>&1)"; rc=$?
mv "$T/blob.saved" "$T/work/.git/objects/${BL:0:2}/${BL:2}"
[ "$rc" -eq 2 ] && ! grep -q 'landed' <<< "$out" && pass "missing object: exit 2, never landed" || fail "missing object: rc=$rc $out"

[ -z "$(git status --porcelain)" ] && pass "working tree untouched" || fail "working tree changed"

if [ "$fails" -ne 0 ]; then echo "$fails test(s) failed" >&2; exit 1; fi
echo "all added-lines-check tests passed"
