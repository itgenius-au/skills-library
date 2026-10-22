#!/usr/bin/env bash
# Tests for stale-archive.sh and stale-archive-verify.sh: local bare "origin" repos, a stub gcloud
# whose bucket is a local directory, and a git wrapper that can break the bundle restore test.
# shellcheck disable=SC2015  # pass() cannot fail, so "A && pass || fail" is safe here.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SCRIPTS="$(dirname "$DIR")"
ARCH="$SCRIPTS/stale-archive.sh"
VERIFY="$SCRIPTS/stale-archive-verify.sh"
T="$(mktemp -d /tmp/stale-archive-tests.XXXXXX)"
trap 'rm -rf -- "$T"' EXIT
export HOME="$T/home" GIT_CONFIG_NOSYSTEM=1
mkdir -p "$HOME"
fails=0
pass() { echo "ok   - $1"; }
fail() { echo "FAIL - $1" >&2; fails=$((fails + 1)); }
g() { git -c user.name=t -c user.email=t@example.com "$@"; }
D="$(date +%F)"
BUCKET=gs://test-bucket/backups/branch-archive-bundles

# --- stubs: gcloud (bucket = $GCS_STUB_DIR) and a git that can fail bundle fetches ---------------
STUB="$T/stub"; mkdir -p "$STUB"
export GCS_STUB_DIR="$T/gcs"; mkdir -p "$GCS_STUB_DIR"
cat > "$STUB/gcloud" <<'EOS'
#!/usr/bin/env bash
# Stub: `gcloud storage cp SRC DEST` and `gcloud storage ls PATH`; gs://X maps to $GCS_STUB_DIR/X.
echo "$*" >> "$GCS_STUB_DIR/../gcloud.log"
[ "${1:-}" = storage ] || { echo "stub gcloud: unsupported: $*" >&2; exit 1; }
cmd="${2:-}"; shift 2
args=(); for a in "$@"; do case "$a" in -*) ;; *) args+=("$a") ;; esac; done
map() { case "$1" in gs://*) printf '%s/%s' "$GCS_STUB_DIR" "${1#gs://}" ;; *) printf '%s' "$1" ;; esac; }
case "$cmd" in
  cp)
    [ -z "${GCS_STUB_FAIL_CP:-}" ] || { echo "stub gcloud: cp failed" >&2; exit 1; }
    src="$(map "${args[0]}")"; dest="$(map "${args[1]}")"
    # A copy that dies half way: a truncated object is left behind and the exit status is non-zero.
    if [ -n "${GCS_STUB_PARTIAL_CP:-}" ]; then mkdir -p "$(dirname "$dest")"; head -c 10 "$src" > "$dest"; echo "stub gcloud: cp interrupted" >&2; exit 1; fi
    case "${args[1]}" in */) mkdir -p "$dest"; cp "$src" "$dest" ;; *) mkdir -p "$(dirname "$dest")"; if [ -d "$dest" ]; then cp "$src" "$dest/"; else cp "$src" "$dest"; fi ;; esac
    # Test hook: right after the bundle is copied, move a branch on the remote (a push mid-run).
    if [ -n "${GCS_HOOK_BRANCH:-}" ]; then case "$src" in *.bundle) "$REAL_GIT" -C "$GCS_HOOK_ORIGIN" update-ref "refs/heads/$GCS_HOOK_BRANCH" "$GCS_HOOK_SHA" ;; esac; fi ;;
  ls)
    [ -z "${GCS_STUB_LS_FAIL:-}" ] || { echo "stub gcloud: ls failed" >&2; exit 1; }
    p="$(map "${args[0]}")"
    if [ -f "$p" ]; then echo "${args[0]}"; elif [ -d "$p" ]; then ls "$p"; else echo "stub gcloud: not found: ${args[0]}" >&2; exit 1; fi ;;
  *) echo "stub gcloud: unsupported: $cmd" >&2; exit 1 ;;
esac
EOS
chmod +x "$STUB/gcloud"
REAL_GIT="$(command -v git)"; export REAL_GIT
mkdir -p "$T/gitwrap"
cat > "$T/gitwrap/git" <<'EOS'
#!/usr/bin/env bash
# Wrapper around git for fault injection, driven by environment variables:
#   GIT_WRAP_FAIL=1         a `fetch` from a .bundle fails, like a bundle that does not restore
#   WRAP_RETAG=<sha>        after a .bundle fetch, every restored tag is moved to <sha>
#   RACE_BRANCH=<b>         just before the lease-protected delete push of branch <b>:
#     RACE_REMOTE_SHA/RACE_ORIGIN   advance the branch on the remote to that SHA
#     RACE_LOCAL_SHA/RACE_WORK      move the local branch to that SHA
#   WRAP_PRETAG*            just before a tag push, create tag WRAP_PRETAG at WRAP_PRETAG_SHA on WRAP_PRETAG_ORIGIN
#   WRAP_PUSH_NOOP=1        a tag push "succeeds" (exit 0) but sends nothing
#   WRAP_BUNDLE_DROP=1      `git bundle create` silently leaves out its last ref
#   GIT_WRAP_LOG=<file>     append every git command line to the file
[ -z "${GIT_WRAP_LOG:-}" ] || echo "$*" >> "$GIT_WRAP_LOG"
if [ -n "${WRAP_PUSH_NOOP:-}" ]; then
  case " $* " in *" push "*refs/tags/*) exit 0 ;; esac
fi
if [ -n "${WRAP_BUNDLE_DROP:-}" ]; then
  case " $* " in *" bundle create "*) args=("$@"); unset 'args[${#args[@]}-1]'; exec "$REAL_GIT" "${args[@]}" ;; esac
fi
if [ -n "${GIT_WRAP_FAIL:-}" ]; then
  case " $* " in *" fetch "*.bundle*) echo "wrapper: bundle is corrupt" >&2; exit 1 ;; esac
fi
if [ -n "${WRAP_RETAG:-}" ]; then
  case " $* " in *" fetch "*.bundle*)
    "$REAL_GIT" "$@" || exit $?
    for r in $("$REAL_GIT" -C "$2" for-each-ref --format='%(refname)' refs/tags); do "$REAL_GIT" -C "$2" update-ref "$r" "$WRAP_RETAG"; done
    exit 0 ;; esac
fi
if [ -n "${RACE_BRANCH:-}" ]; then
  case "$*" in *"--force-with-lease=refs/heads/$RACE_BRANCH:"*)
    [ -z "${RACE_REMOTE_SHA:-}" ] || "$REAL_GIT" -C "$RACE_ORIGIN" update-ref "refs/heads/$RACE_BRANCH" "$RACE_REMOTE_SHA"
    [ -z "${RACE_LOCAL_SHA:-}" ] || "$REAL_GIT" -C "$RACE_WORK" update-ref "refs/heads/$RACE_BRANCH" "$RACE_LOCAL_SHA" ;; esac
fi
if [ -n "${WRAP_PRETAG:-}" ]; then
  case " $* " in *" push "*refs/tags/*) "$REAL_GIT" -C "$WRAP_PRETAG_ORIGIN" update-ref "refs/tags/$WRAP_PRETAG" "$WRAP_PRETAG_SHA" ;; esac
fi
exec "$REAL_GIT" "$@"
EOS
chmod +x "$T/gitwrap/git"
export PATH="$STUB:$PATH"
gcs_clear() { rm -rf "$GCS_STUB_DIR" "$T/gcloud.log"; mkdir -p "$GCS_STUB_DIR"; }

# --- fixture: origin (bare) + work clone, branches a, feature/x, c, all pushed -------------------
# mk <name> [default-branch]: sets W (clone), O (origin), P (plan), REC, and SHA_<branch>.
mk() {
  local n="$1" def="${2:-main}" b
  O="$T/$n/myrepo.git"; W="$T/$n/work"; P="$T/$n/plan.tsv"; REC="$T/$n/record.tsv"
  mkdir -p "$T/$n"
  git init -q --bare -b "$def" "$O"
  git clone -q "$O" "$W" 2>/dev/null
  ( cd "$W" || exit 1
    git checkout -q -b "$def" 2>/dev/null || true
    echo base > base.txt && git add . && g commit -q -m base && git push -q origin "$def"
    for b in a feature/x c; do
      git checkout -q -b "$b" "$def"
      echo "$b" | tr / _ > "f-$(echo "$b" | tr / _).txt" && git add . && g commit -q -m "$b"
      git push -q origin "$b"
    done
    git checkout -q "$def"
    # The stale branches are already merged (the usual case), so plain `git branch -d` accepts them.
    for b in a feature/x c; do g merge -q --no-ff -m "merge $b" "$b"; done
    git push -q origin "$def"
    git remote set-head origin "$def" >/dev/null )
  : > "$P"
  { echo "# approved plan"; echo
    for b in a feature/x c; do printf '%s\t%s\n' "$b" "$(git -C "$O" rev-parse "refs/heads/$b")"; done; } > "$P"
}
run() { bash "$ARCH" --repo "$W" --plan "$P" --bucket "$BUCKET" --out "$REC" "$@"; }
remote_heads() { git -C "$O" for-each-ref --format='%(refname)' refs/heads | sort | tr '\n' ' '; }
remote_tags() { git -C "$O" for-each-ref --format='%(refname:lstrip=2)' refs/tags | sort; }
state_of() { awk -F'\t' -v b="$1" '$2 == b {print $6}' "$REC"; }
snapshot() { { git -C "$W" for-each-ref --format='%(refname) %(objectname)'; git -C "$O" for-each-ref --format='%(refname) %(objectname)'; } | grep -v 'refs/remotes/' | sort; }

# === 1. dry run changes nothing ===============================================================
mk dry; gcs_clear
before="$(snapshot)"
out="$(run 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && pass "dry run exits 0" || fail "dry run rc=$rc: $out"
[ "$before" = "$(snapshot)" ] && pass "dry run: no tag, push or delete" || fail "dry run changed refs"
{ [ ! -e "$T/gcloud.log" ] && [ -z "$(ls -A "$GCS_STUB_DIR")" ]; } && pass "dry run: no gcloud call, no bundle" || fail "dry run touched the bucket"
[ "$(grep -c DRY-RUN "$REC")" -eq 3 ] && head -1 "$REC" | grep -q $'^repo\tbranch\tsha\tarchive_tag\tbundle\tstate' \
  && pass "dry run record: header and 3 DRY-RUN rows" || fail "dry run record: $(cat "$REC")"
grep -q "archive/$D/feature/x" <<< "$out" && pass "dry run prints the planned tags" || fail "dry run output: $out"

# === 2. --exec happy path =====================================================================
mk ok; gcs_clear
SHA_A="$(git -C "$O" rev-parse refs/heads/a)"
out="$(run --exec 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && pass "exec happy path exits 0" || fail "exec rc=$rc: $out"
[ -z "$(remote_heads | tr -d ' ' | sed 's|refs/heads/main||')" ] && pass "exec: branches deleted on origin, main kept" || fail "heads left: $(remote_heads)"
[ "$(remote_tags)" = "$(printf 'archive/%s/a\narchive/%s/c\narchive/%s/feature/x' "$D" "$D" "$D")" ] && pass "exec: three tags on origin" || fail "tags: $(remote_tags)"
[ "$(git -C "$O" rev-parse "refs/tags/archive/$D/a")" = "$SHA_A" ] && pass "exec: tag at the approved SHA" || fail "tag a SHA wrong"
BUNDLE="$GCS_STUB_DIR/test-bucket/backups/branch-archive-bundles/myrepo/myrepo-branch-archive-$D.bundle"
[ -f "$BUNDLE" ] && pass "exec: bundle in the bucket under <repo>/" || fail "no bundle at $BUNDLE"
RT="$T/restore-check"; git init -q "$RT"
git -C "$RT" fetch -q "$BUNDLE" 'refs/tags/*:refs/tags/*' && [ "$(git -C "$RT" tag -l 'archive/*' | wc -l)" -eq 3 ] \
  && pass "exec: bundle restores all 3 tags in an empty repo" || fail "bundle restore"
git bundle list-heads "$BUNDLE" 2>/dev/null | grep -q 'refs/remotes/origin/main' && pass "exec: bundle holds origin/<default>" || fail "bundle lacks origin/main"
[ "$(git -C "$W" branch --list a c feature/x | wc -l)" -eq 3 ] && pass "exec: local branches are never deleted" || fail "a local branch was deleted"
[ "$(grep -c 'DELETED-REMOTE+LOCAL-KEPT' "$REC")" -eq 3 ] && pass "exec record: 3 DELETED-REMOTE+LOCAL-KEPT rows" || fail "record: $(cat "$REC")"
grep -q 'Local copies kept (delete by hand after checking)' <<< "$out" && grep -q 'git branch -d -- feature/x' <<< "$out" && pass "exec: the kept local copies are listed with the command" || fail "no kept list: $out"
[ -f "$GCS_STUB_DIR/test-bucket/backups/branch-archive-bundles/myrepo/myrepo-branch-archive-$D.record.tsv" ] && pass "exec: record copied next to the bundle" || fail "record not in bucket"
vout="$(bash "$VERIFY" --repo "$W" --record "$REC" --restore 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && grep -q 'checked 3, ok 3, fail 0' <<< "$vout" && pass "verifier passes with --restore" || fail "verifier rc=$rc: $vout"

# --- verifier FAIL cases (on the finished run above) ---
git -C "$O" update-ref refs/heads/a "$SHA_A"
vout="$(bash "$VERIFY" --repo "$W" --record "$REC" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q 'FAIL  a: branch still on origin' <<< "$vout" && pass "verifier FAILs when a branch still exists" || fail "verifier (branch back) rc=$rc: $vout"
git -C "$O" update-ref -d refs/heads/a
sed "s|$SHA_A|$(git -C "$O" rev-parse refs/heads/main)|" "$REC" > "$T/bad.tsv"
vout="$(bash "$VERIFY" --repo "$W" --record "$T/bad.tsv" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q 'FAIL  a: tag archive/.*/a is at' <<< "$vout" && pass "verifier FAILs when the tag SHA differs" || fail "verifier (tag sha) rc=$rc: $vout"
rm -f "$BUNDLE"
vout="$(bash "$VERIFY" --repo "$W" --record "$REC" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q 'bundle .* not found' <<< "$vout" && pass "verifier FAILs when the bundle is gone" || fail "verifier (no bundle) rc=$rc: $vout"

# === 3. remote tip moved after planning =======================================================
mk moved; gcs_clear
( cd "$W" && git checkout -q feature/x && echo more > more.txt && git add . && g commit -q -m "moved on" && git push -q origin feature/x && git checkout -q main )
NEWTIP="$(git -C "$O" rev-parse refs/heads/feature/x)"
out="$(run --exec 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && [ "$(state_of feature/x)" = SKIPPED-TIP-MOVED ] && pass "moved tip: skipped with SKIPPED-TIP-MOVED, run still exits 0" || fail "moved: rc=$rc $(cat "$REC") $out"
[ "$(git -C "$O" rev-parse refs/heads/feature/x)" = "$NEWTIP" ] && pass "moved tip: branch kept on origin" || fail "moved branch was touched"
{ [ "$(state_of a)" = DELETED-REMOTE+LOCAL-KEPT ] && [ "$(state_of c)" = DELETED-REMOTE+LOCAL-KEPT ]; } && pass "moved tip: other branches still archived and deleted" || fail "others not done: $(cat "$REC")"
remote_tags | grep -q 'feature/x' && fail "moved tip: a tag was made for the moved branch" || pass "moved tip: no tag for the moved branch"

# === 4. existing tag at another SHA is never overwritten ======================================
mk tagclash; gcs_clear
MAIN_SHA="$(git -C "$O" rev-parse refs/heads/main)"
git -C "$W" tag "archive/$D/a" "$MAIN_SHA" && git -C "$W" push -q origin "refs/tags/archive/$D/a"
SHA_A="$(git -C "$O" rev-parse refs/heads/a)"
out="$(run --exec 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && pass "tag clash: exits 0" || fail "tag clash rc=$rc $out"
[ "$(git -C "$O" rev-parse "refs/tags/archive/$D/a")" = "$MAIN_SHA" ] && pass "tag clash: existing tag untouched" || fail "existing tag was overwritten"
[ "$(git -C "$O" rev-parse "refs/tags/archive/$D/a--${SHA_A:0:8}")" = "$SHA_A" ] && pass "tag clash: suffixed tag at the new SHA" || fail "no suffixed tag: $(remote_tags)"
bash "$VERIFY" --repo "$W" --record "$REC" >/dev/null 2>&1 && pass "tag clash: verifier passes" || fail "tag clash verifier failed"

# === 5. local tip differs from the remote tip =================================================
mk localtip; gcs_clear
( cd "$W" && git checkout -q c && echo unpushed > unpushed.txt && git add . && g commit -q -m "local only" && git checkout -q main )
LSHA="$(git -C "$W" rev-parse refs/heads/c)"; RSHA="$(git -C "$O" rev-parse refs/heads/c)"
out="$(run --exec 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && [ "$(git -C "$O" rev-parse "refs/tags/archive/$D/c--local-${LSHA:0:8}")" = "$LSHA" ] && pass "local tip: extra --local- tag at the local SHA, pushed" || fail "local tag: rc=$rc $(remote_tags) $out"
[ "$(git -C "$O" rev-parse "refs/tags/archive/$D/c")" = "$RSHA" ] && pass "local tip: normal tag at the remote SHA" || fail "remote tag for c wrong"
{ [ -n "$(git -C "$W" branch --list c)" ] && [ "$(git -C "$W" rev-parse refs/heads/c)" = "$LSHA" ] && [ "$(state_of c)" = DELETED-REMOTE+LOCAL-KEPT ]; } \
  && pass "local tip: unpushed local commit is kept (git branch -d refuses), remote deleted" || fail "local c: $(cat "$REC")"
RT="$T/restore-check2"; git init -q "$RT"
git -C "$RT" fetch -q "$GCS_STUB_DIR/test-bucket/backups/branch-archive-bundles/myrepo/myrepo-branch-archive-$D.bundle" 'refs/tags/*:refs/tags/*' \
  && git -C "$RT" rev-parse -q --verify "refs/tags/archive/$D/c--local-${LSHA:0:8}" >/dev/null && pass "local tip: bundle holds the local tag" || fail "bundle lacks the local tag"

# === 6. workflow that runs on tags stops the run before any push ===============================
mk trig; gcs_clear
( cd "$W" && git checkout -q a && mkdir -p .github/workflows && printf 'on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps: [{run: "true"}]\n' > .github/workflows/ci.yml \
    && git add . && g commit -q -m "ci" && git push -q origin a && git checkout -q main )
printf '%s\t%s\n' a "$(git -C "$O" rev-parse refs/heads/a)" > "$P"
before_tags="$(remote_tags)"
out="$(run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && [ "$(remote_tags)" = "$before_tags" ] && [ -n "$(git -C "$O" rev-parse -q --verify refs/heads/a)" ] && [ ! -e "$T/gcloud.log" ]; } \
  && pass "tag trigger: exit 1 before any push, delete or bundle" || fail "trigger: rc=$rc tags=$(remote_tags) $out"
grep -q 'NOT-DELETED-TAG-TRIGGER' "$REC" && pass "tag trigger: record says NOT-DELETED-TAG-TRIGGER" || fail "trigger record: $(cat "$REC")"
out="$(run --exec --allow-triggers 2>&1)"; rc=$?
{ [ "$rc" -eq 0 ] && [ -z "$(git -C "$O" ls-remote --heads origin a 2>/dev/null)" ] && [ "$(state_of a)" = DELETED-REMOTE+LOCAL-KEPT ]; } \
  && pass "tag trigger: --allow-triggers proceeds" || fail "allow-triggers rc=$rc $out"

# === 7. a failed gate deletes nothing ============================================================
mk badrestore; gcs_clear
out="$(GIT_WRAP_FAIL=1 PATH="$T/gitwrap:$PATH" run --exec 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && [ "$(remote_heads)" = "refs/heads/a refs/heads/c refs/heads/feature/x refs/heads/main " ] \
  && grep -q 'restore test: fetch from the bundle failed' <<< "$out" && pass "failing restore test: exit 1, nothing deleted, says why" || fail "restore fail: rc=$rc heads=$(remote_heads) $out"
{ [ -z "$(find "$GCS_STUB_DIR" -type f)" ] && grep -q 'NOT-DELETED-RESTORE' "$REC" && [ "$(git -C "$W" branch --list a c feature/x | wc -l)" -eq 3 ]; } \
  && pass "failing restore test: nothing copied, local branches kept, record says so" || fail "restore fail leftovers"
mk badcopy; gcs_clear
out="$(GCS_STUB_FAIL_CP=1 run --exec 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && [ "$(remote_heads)" = "refs/heads/a refs/heads/c refs/heads/feature/x refs/heads/main " ] && grep -q 'NOT-DELETED-BUNDLE-COPY' "$REC" && grep -q 'copy to .* failed' <<< "$out" \
  && pass "failing bundle copy: exit 1, nothing deleted, says why" || fail "copy fail: rc=$rc heads=$(remote_heads) $out"

# === 8. identical tips share a tag; default and protected branches are never archived ===========
mk shared; gcs_clear
git -C "$O" update-ref refs/heads/a2 "$(git -C "$O" rev-parse refs/heads/a)"
git -C "$O" update-ref refs/heads/backup/old "$(git -C "$O" rev-parse refs/heads/a)"
{ printf 'a2\t%s\n' "$(git -C "$O" rev-parse refs/heads/a)"; printf 'main\t%s\n' "$(git -C "$O" rev-parse refs/heads/main)"
  printf 'backup/old\t%s\n' "$(git -C "$O" rev-parse refs/heads/a)"; printf 'a\t%s\n' "$(git -C "$O" rev-parse refs/heads/a)"; } > "$P"
out="$(run --exec 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && [ "$(remote_tags | wc -l)" -eq 1 ] && pass "shared tip: two branches, one tag" || fail "shared: rc=$rc tags=$(remote_tags) $out"
{ [ "$(state_of main)" = SKIPPED-DEFAULT-BRANCH ] && [ "$(state_of backup/old)" = SKIPPED-PROTECTED ] && git -C "$O" rev-parse -q --verify refs/heads/main >/dev/null \
  && git -C "$O" rev-parse -q --verify refs/heads/backup/old >/dev/null; } && pass "default and backup branches skipped and kept" || fail "protected: $(cat "$REC")"

# === 9. default branch comes from origin/HEAD, not a hard-coded main ============================
mk trunk trunk; gcs_clear
out="$(run --exec 2>&1)"; rc=$?
BUNDLE="$GCS_STUB_DIR/test-bucket/backups/branch-archive-bundles/myrepo/myrepo-branch-archive-$D.bundle"
{ [ "$rc" -eq 0 ] && git bundle list-heads "$BUNDLE" 2>/dev/null | grep -q 'refs/remotes/origin/trunk'; } && pass "default branch trunk is bundled" || fail "trunk: rc=$rc $out"

# === 10. the branch moves between the pre-delete check and the delete push (lease) ===============
mk lease; gcs_clear
( cd "$W" && git checkout -q feature/x && echo racing > racing.txt && git add . && g commit -q -m "racing push" && git push -q origin "HEAD:refs/pending/x" && git checkout -q main )
RACE_SHA="$(git -C "$W" rev-parse refs/heads/feature/x)"
out="$(RACE_BRANCH=feature/x RACE_ORIGIN="$O" RACE_REMOTE_SHA="$RACE_SHA" PATH="$T/gitwrap:$PATH" run --exec 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && [ "$(git -C "$O" rev-parse refs/heads/feature/x)" = "$RACE_SHA" ] && pass "lease: a push landing just before the delete survives with its new SHA" || fail "lease race: rc=$rc $out"
[ "$(state_of feature/x)" = SKIPPED-TIP-MOVED ] && pass "lease: record says SKIPPED-TIP-MOVED" || fail "lease record: $(cat "$REC")"
{ [ "$(state_of a)" = DELETED-REMOTE+LOCAL-KEPT ] && [ "$(state_of c)" = DELETED-REMOTE+LOCAL-KEPT ]; } && pass "lease: the run continues with the other branches" || fail "lease others: $(cat "$REC")"
[ -n "$(git -C "$W" branch --list feature/x)" ] && pass "lease: the local copy of the kept branch is kept" || fail "lease: local branch deleted"

# === 11. local branch advanced after tagging, or checked out in a worktree: local kept ==========
mk localadv; gcs_clear
( cd "$W" && git checkout -q -b tmp-adv c && echo adv > adv.txt && git add . && g commit -q -m "unmerged local work" && git checkout -q main )
LADV="$(git -C "$W" rev-parse refs/heads/tmp-adv)"
out="$(RACE_BRANCH=c RACE_WORK="$W" RACE_LOCAL_SHA="$LADV" PATH="$T/gitwrap:$PATH" run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 0 ] && [ "$(state_of c)" = DELETED-REMOTE+LOCAL-KEPT ] && [ "$(git -C "$W" rev-parse refs/heads/c)" = "$LADV" ]; } \
  && pass "local advanced after tagging (unmerged commits): remote deleted, local kept at its new tip" || fail "local adv: rc=$rc $(cat "$REC") $out"
mk wtree; gcs_clear
git -C "$W" worktree add -q "$T/wtree/wt" c
out="$(run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 0 ] && [ "$(state_of c)" = DELETED-REMOTE+LOCAL-KEPT ] && [ -n "$(git -C "$W" branch --list c)" ] && [ "$(state_of a)" = DELETED-REMOTE+LOCAL-KEPT ]; } \
  && pass "checked out in a worktree: remote deleted, local kept" || fail "worktree: rc=$rc $(cat "$REC") $out"

# === 12. default branch comes from the server, not the stale origin/HEAD =========================
mk srvdef; gcs_clear
git -C "$O" update-ref refs/heads/trunk "$(git -C "$O" rev-parse refs/heads/main)"
git -C "$O" symbolic-ref HEAD refs/heads/trunk
[ "$(git -C "$W" symbolic-ref --short refs/remotes/origin/HEAD)" = origin/main ] || fail "fixture: local origin/HEAD should still say main"
{ printf 'trunk\t%s\n' "$(git -C "$O" rev-parse refs/heads/trunk)"; printf 'a\t%s\n' "$(git -C "$O" rev-parse refs/heads/a)"; } > "$P"
out="$(run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 0 ] && [ "$(state_of trunk)" = SKIPPED-DEFAULT-BRANCH ] && git -C "$O" rev-parse -q --verify refs/heads/trunk >/dev/null && [ "$(state_of a)" = DELETED-REMOTE+LOCAL-KEPT ]; } \
  && pass "server default (trunk) is never deleted even when local origin/HEAD says main" || fail "srvdef: rc=$rc $(cat "$REC") $out"
git bundle list-heads "$GCS_STUB_DIR/test-bucket/backups/branch-archive-bundles/myrepo/myrepo-branch-archive-$D.bundle" 2>/dev/null | grep -q 'refs/remotes/origin/trunk' \
  && pass "server default: the bundle holds origin/trunk" || fail "bundle lacks origin/trunk"
mk nohead; gcs_clear
git -C "$O" symbolic-ref HEAD refs/heads/does-not-exist
before="$(remote_heads)"
out="$(run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && [ "$before" = "$(remote_heads)" ] && [ -z "$(remote_tags)" ]; } && pass "no server default branch: abort with exit 1, nothing changed" || fail "nohead: rc=$rc $out"

# === 13. the trigger check judges the real tag names =============================================
mk realtag; gcs_clear
( cd "$W" && git checkout -q feature/x && mkdir -p .github/workflows && printf "on:\n  push:\n    tags: ['archive/*/feature/*']\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps: [{run: 'true'}]\n" > .github/workflows/t.yml \
    && git add . && g commit -q -m "tags workflow" && git push -q origin feature/x && git checkout -q main )
{ for b in a feature/x c; do printf '%s\t%s\n' "$b" "$(git -C "$O" rev-parse "refs/heads/$b")"; done; } > "$P"
out="$(run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && [ -z "$(remote_tags)" ] && grep -q 'NOT-DELETED-TAG-TRIGGER' "$REC"; } && pass "filter archive/*/feature/* stops the run (real tag names are checked)" || fail "realtag: rc=$rc $out"

# === 14. gates that must stop the run before any delete ==========================================
mk retag; gcs_clear
out="$(WRAP_RETAG="$(git -C "$O" rev-parse refs/heads/main)" PATH="$T/gitwrap:$PATH" run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'restores at the wrong SHA' <<< "$out" && [ "$(remote_heads)" = "refs/heads/a refs/heads/c refs/heads/feature/x refs/heads/main " ] && [ -z "$(find "$GCS_STUB_DIR" -type f)" ]; } \
  && pass "restored tag at the wrong SHA: stop, nothing deleted or copied" || fail "retag: rc=$rc $out"
mk lsmiss; gcs_clear
out="$(GCS_STUB_LS_FAIL=1 run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'NOT-DELETED-BUNDLE-COPY' "$REC" && [ "$(remote_heads)" = "refs/heads/a refs/heads/c refs/heads/feature/x refs/heads/main " ]; } \
  && pass "copy succeeds but the object is not visible: stop, nothing deleted" || fail "lsmiss: rc=$rc $out"
mk pretag; gcs_clear
out="$(WRAP_PRETAG="archive/$D/a" WRAP_PRETAG_ORIGIN="$O" WRAP_PRETAG_SHA="$(git -C "$O" rev-parse refs/heads/main)" PATH="$T/gitwrap:$PATH" run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'NOT-DELETED-TAG-PUSH' "$REC" && [ "$(remote_heads)" = "refs/heads/a refs/heads/c refs/heads/feature/x refs/heads/main " ] \
  && [ "$(git -C "$O" rev-parse "refs/tags/archive/$D/a")" = "$(git -C "$O" rev-parse refs/heads/main)" ]; } \
  && grep -q 'tag push failed' <<< "$out" && pass "a tag taken on origin after planning: tag push rejected, stop, nothing deleted, tag not overwritten" || fail "pretag: rc=$rc $out"

# === 15. every protected pattern is skipped and kept ==============================================
mk prot; gcs_clear
ASHA="$(git -C "$O" rev-parse refs/heads/a)"
: > "$P"
for b in sync-backup/x backup/y staging develop production release/x; do git -C "$O" update-ref "refs/heads/$b" "$ASHA"; printf '%s\t%s\n' "$b" "$ASHA" >> "$P"; done
out="$(run --exec 2>&1)"; rc=$?
okp=1; for b in sync-backup/x backup/y staging develop production release/x; do
  [ "$(state_of "$b")" = SKIPPED-PROTECTED ] && git -C "$O" rev-parse -q --verify "refs/heads/$b" >/dev/null || { okp=0; echo "  not protected: $b" >&2; }
done
{ [ "$rc" -eq 0 ] && [ "$okp" -eq 1 ] && [ -z "$(remote_tags)" ]; } && pass "backup/, sync-backup/, staging, develop, production, release/*: skipped, kept, no tag" || fail "protected: rc=$rc $(cat "$REC")"

# === 16. verifier: record parsing, local tag SHA, restore failures ================================
mk vrf; gcs_clear
( cd "$W" && git checkout -q c && echo unpushed > unpushed.txt && git add . && g commit -q -m "local only" && git checkout -q main )
LSHA="$(git -C "$W" rev-parse refs/heads/c)"
run --exec >/dev/null 2>&1 || fail "vrf: setup run failed"
VB="$GCS_STUB_DIR/test-bucket/backups/branch-archive-bundles/myrepo/myrepo-branch-archive-$D.bundle"
head -1 "$REC" | grep -q $'local_tag\tlocal_sha$' && pass "record header ends with local_tag, local_sha" || fail "record header: $(head -1 "$REC")"
awk -F'\t' '$2 == "c" && $7 ~ /--local-/ && $8 == "'"$LSHA"'"' "$REC" | grep -q . && pass "record holds the local tag and its SHA" || fail "local_sha missing: $(cat "$REC")"
vout="$(bash "$VERIFY" --repo "$W" --record "$REC" --restore 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && grep -q 'checked 3, ok 3, fail 0' <<< "$vout" && pass "verifier: local tag at its SHA passes, also with --restore" || fail "vrf ok: rc=$rc $vout"
awk 'BEGIN{FS=OFS="\t"} NR>1 && $2=="c"{$8="0000000000000000000000000000000000000000"} {print}' "$REC" > "$T/vrf-badlocal.tsv"
vout="$(bash "$VERIFY" --repo "$W" --record "$T/vrf-badlocal.tsv" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q 'FAIL  c: local tag .* is at' <<< "$vout" && pass "verifier FAILs when the local tag is at another SHA" || fail "vrf badlocal: rc=$rc $vout"
awk 'BEGIN{FS=OFS="\t"} NR>1{$1="repo"} {print}' "$REC" > "$T/vrf-repo.tsv"
vout="$(bash "$VERIFY" --repo "$W" --record "$T/vrf-repo.tsv" 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && grep -q 'checked 3, ok 3' <<< "$vout" && pass "verifier: rows whose repo column is literally 'repo' are checked" || fail "vrf repo: rc=$rc $vout"
printf '%s' "$(cat "$REC")" > "$T/vrf-nonl.tsv"
vout="$(bash "$VERIFY" --repo "$W" --record "$T/vrf-nonl.tsv" 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && grep -q 'checked 3, ok 3' <<< "$vout" && pass "verifier: a final row without a trailing newline is checked" || fail "vrf nonl: rc=$rc $vout"
{ cat "$REC"; printf 'myrepo\tx\tabc\n'; } > "$T/vrf-short.tsv"
vout="$(bash "$VERIFY" --repo "$W" --record "$T/vrf-short.tsv" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q 'FAIL  row 4: malformed' <<< "$vout" && pass "verifier FAILs a row with the wrong column count" || fail "vrf short: rc=$rc $vout"
{ cat "$REC"; printf 'myrepo\tx\t\tt\tb\tDELETED-REMOTE\t-\t-\n'; } > "$T/vrf-empty.tsv"
vout="$(bash "$VERIFY" --repo "$W" --record "$T/vrf-empty.tsv" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q 'FAIL  row 4: malformed' <<< "$vout" && pass "verifier FAILs a row with an empty field" || fail "vrf empty: rc=$rc $vout"
{ head -1 "$REC"; printf 'myrepo\tx\t%s\t-\t-\tSKIPPED-TIP-MOVED\t-\t-\n' "$LSHA"; } > "$T/vrf-nodel.tsv"
vout="$(bash "$VERIFY" --repo "$W" --record "$T/vrf-nodel.tsv" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q 'none is a DELETED' <<< "$vout" && pass "verifier: rows but no DELETED-* row is a FAIL" || fail "vrf nodel: rc=$rc $vout"
{ printf 'a\tb\tc\n'; tail -n +2 "$REC"; } > "$T/vrf-hdr.tsv"
bash "$VERIFY" --repo "$W" --record "$T/vrf-hdr.tsv" >/dev/null 2>&1; rc=$?
[ "$rc" -eq 1 ] && pass "verifier: a wrong header is a FAIL" || fail "vrf header: rc=$rc"
# bundle without the tags: --restore must FAIL, plain check still passes
cp "$VB" "$T/good.bundle"
git -C "$W" bundle create "$VB" main >/dev/null 2>&1
vout="$(bash "$VERIFY" --repo "$W" --record "$REC" --restore 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q 'restore: tag .* not in bundle' <<< "$vout" && pass "verifier --restore FAILs when the bundle lacks a tag" || fail "vrf restore: rc=$rc $vout"
bash "$VERIFY" --repo "$W" --record "$REC" >/dev/null 2>&1 && pass "verifier without --restore does not open the bundle" || fail "vrf plain"
# bundle holds the main tags but not the local one
cp "$T/good.bundle" "$VB"
git -C "$W" bundle create "$VB" "refs/tags/archive/$D/c" "refs/tags/archive/$D/a" "refs/tags/archive/$D/feature/x" >/dev/null 2>&1
vout="$(bash "$VERIFY" --repo "$W" --record "$REC" --restore 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && grep -q "restore: tag archive/$D/c--local-.* not in bundle" <<< "$vout" && pass "verifier --restore FAILs when the bundle lacks the local tag" || fail "vrf local restore: rc=$rc $vout"

# === 17. gates found by mutation testing ===========================================================
HEADS4="refs/heads/a refs/heads/c refs/heads/feature/x refs/heads/main "
# a bundle that silently lacks a tag: the tag-set check names it
mk dropref; gcs_clear
out="$(WRAP_BUNDLE_DROP=1 PATH="$T/gitwrap:$PATH" run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'does not hold every tag' <<< "$out" && [ "$(remote_heads)" = "$HEADS4" ]; } \
  && pass "bundle lacking one tag: stop with the tag-set message, nothing deleted" || fail "dropref: rc=$rc $out"
# a copy that dies half way leaves a truncated object that ls can see: the cp exit status must stop the run
mk partial; gcs_clear
out="$(GCS_STUB_PARTIAL_CP=1 run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'copy to .* failed' <<< "$out" && grep -q 'NOT-DELETED-BUNDLE-COPY' "$REC" && [ "$(remote_heads)" = "$HEADS4" ]; } \
  && pass "interrupted copy (object visible, exit non-zero): stop, nothing deleted" || fail "partial cp: rc=$rc $out"
# the branch moves after the bundle copy: kept, and no delete push is even attempted for it
mk afterbundle; gcs_clear
( cd "$W" && git checkout -q feature/x && echo late > late.txt && git add . && g commit -q -m "late push" && git push -q origin "HEAD:refs/pending/x" && git checkout -q main )
LATE="$(git -C "$W" rev-parse refs/heads/feature/x)"
: > "$T/wrap.log"
out="$(GCS_HOOK_ORIGIN="$O" GCS_HOOK_BRANCH=feature/x GCS_HOOK_SHA="$LATE" GIT_WRAP_LOG="$T/wrap.log" PATH="$T/gitwrap:$PATH" run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 0 ] && [ "$(git -C "$O" rev-parse refs/heads/feature/x)" = "$LATE" ] && [ "$(state_of feature/x)" = SKIPPED-TIP-MOVED ]; } \
  && pass "branch moved after the bundle copy: kept, SKIPPED-TIP-MOVED" || fail "afterbundle: rc=$rc $(cat "$REC") $out"
grep -q -- '--force-with-lease=refs/heads/feature/x:' "$T/wrap.log" && fail "a delete push was attempted for the moved branch" || pass "branch moved after the bundle copy: no delete push attempted for it"
grep -q -- '--force-with-lease=refs/heads/a:' "$T/wrap.log" && pass "other branches still get their delete push" || fail "no delete push for a"
# the trigger check cannot run (exit 2): --allow-triggers must not override that
mk trigerr; gcs_clear
printf '#!/usr/bin/env bash\necho "py stub: cannot run" >&2\nexit 2\n' > "$T/py2"; chmod +x "$T/py2"
out="$(PYTHON="$T/py2" run --exec --allow-triggers 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'NOT-DELETED-TRIGGER-CHECK-ERROR' "$REC" && [ -z "$(remote_tags)" ] && [ "$(remote_heads)" = "$HEADS4" ]; } \
  && pass "trigger check error (exit 2) stops the run even with --allow-triggers" || fail "trigerr: rc=$rc $out"
# a tag push that exits 0 but sends nothing: the check that the tags are on origin stops the run
mk pushnoop; gcs_clear
out="$(WRAP_PUSH_NOOP=1 PATH="$T/gitwrap:$PATH" run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'is not on origin at the right SHA' <<< "$out" && grep -q 'NOT-DELETED-TAG-PUSH' "$REC" && [ "$(remote_heads)" = "$HEADS4" ] && [ -z "$(find "$GCS_STUB_DIR" -type f)" ]; } \
  && pass "tag push that sends nothing: stop before the bundle, nothing deleted" || fail "pushnoop: rc=$rc $out"

# verifier: a bundle whose tag points at another commit, and a bundle that cannot be downloaded
mk vrf2; gcs_clear
run --exec >/dev/null 2>&1 || fail "vrf2: setup run failed"
VB2="$GCS_STUB_DIR/test-bucket/backups/branch-archive-bundles/myrepo/myrepo-branch-archive-$D.bundle"
cp "$VB2" "$T/vrf2-good.bundle"
git clone -q "$W" "$T/vrf2-alt" 2>/dev/null
git -C "$T/vrf2-alt" -c user.name=t -c user.email=t@example.com tag -f "archive/$D/a" "$(git -C "$O" rev-parse refs/heads/main)" >/dev/null 2>&1
git -C "$T/vrf2-alt" tag "archive/$D/c" "$(git -C "$O" rev-parse "refs/tags/archive/$D/c")" 2>/dev/null; git -C "$T/vrf2-alt" fetch -q "$O" 'refs/tags/*:refs/tags/*' 2>/dev/null || true
git -C "$T/vrf2-alt" tag -f "archive/$D/a" "$(git -C "$O" rev-parse refs/heads/main)" >/dev/null 2>&1
git -C "$T/vrf2-alt" bundle create "$VB2" "refs/tags/archive/$D/a" "refs/tags/archive/$D/c" "refs/tags/archive/$D/feature/x" >/dev/null 2>&1
vout="$(bash "$VERIFY" --repo "$W" --record "$REC" --restore 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q "FAIL  a: .*restore: tag archive/$D/a restores at the wrong SHA" <<< "$vout"; } \
  && pass "verifier --restore FAILs when the bundle's tag is at another SHA" || fail "vrf wrong-sha bundle: rc=$rc $vout"
cp "$T/vrf2-good.bundle" "$VB2"
vout="$(GCS_STUB_FAIL_CP=1 bash "$VERIFY" --repo "$W" --record "$REC" --restore 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'bundle download failed' <<< "$vout" && ! grep -q '^OK' <<< "$vout"; } \
  && pass "verifier --restore FAILs when the bundle cannot be downloaded" || fail "vrf download: rc=$rc $vout"

# === 18. local symref, unmerged work, new verifier checks ==========================================
mk symref; gcs_clear
git -C "$O" update-ref refs/heads/topic "$(git -C "$O" rev-parse refs/heads/a)"
git -C "$W" symbolic-ref refs/heads/topic refs/heads/main
MAINB="$(git -C "$W" rev-parse refs/heads/main)"
printf 'topic\t%s\n' "$(git -C "$O" rev-parse refs/heads/topic)" > "$P"
out="$(run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 0 ] && [ "$(git -C "$W" rev-parse refs/heads/main)" = "$MAINB" ] && [ "$(git -C "$O" rev-parse refs/heads/main)" = "$(git -C "$W" rev-parse origin/main)" ] \
  && [ -z "$(git -C "$O" for-each-ref refs/heads/topic)" ] && [ "$(state_of topic)" = DELETED-REMOTE+LOCAL-KEPT ] && git -C "$W" symbolic-ref -q refs/heads/topic >/dev/null; } \
  && pass "local symref topic -> main: remote topic deleted, main untouched, the symref kept" || fail "symref: rc=$rc $(cat "$REC") $out"
git -C "$W" log --oneline -1 main >/dev/null && pass "local symref: main still resolves" || fail "main broken"

mk badstate; gcs_clear
run --exec >/dev/null 2>&1 || fail "badstate: setup run failed"
sed 's/DELETED-REMOTE+LOCAL-KEPT\t/DELETD-REMOTE+LOCAL-KEPT\t/' "$REC" > "$T/badstate.tsv"
vout="$(bash "$VERIFY" --repo "$W" --record "$T/badstate.tsv" 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q "unknown state 'DELETD-REMOTE+LOCAL-KEPT'" <<< "$vout"; } && pass "verifier FAILs an unknown state (typo)" || fail "badstate: rc=$rc $vout"
# local_tag set but local_sha missing or short
mk vlsha; gcs_clear
( cd "$W" && git checkout -q c && echo unpushed > unpushed.txt && git add . && g commit -q -m "local only" && git checkout -q main )
run --exec >/dev/null 2>&1 || fail "vlsha: setup run failed"
awk 'BEGIN{FS=OFS="\t"} NR>1 && $2=="c"{$8="-"} {print}' "$REC" > "$T/vlsha1.tsv"
vout="$(bash "$VERIFY" --repo "$W" --record "$T/vlsha1.tsv" 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'local_sha is not a full 40-character SHA' <<< "$vout"; } && pass "verifier FAILs a local tag recorded without its SHA" || fail "vlsha '-': rc=$rc $vout"
awk 'BEGIN{FS=OFS="\t"} NR>1 && $2=="c"{$8=substr($8,1,8)} {print}' "$REC" > "$T/vlsha2.tsv"
vout="$(bash "$VERIFY" --repo "$W" --record "$T/vlsha2.tsv" 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'local_sha is not a full 40-character SHA' <<< "$vout"; } && pass "verifier FAILs a short local_sha" || fail "vlsha short: rc=$rc $vout"

# === 19. final round: local copies are never deleted, checker exit codes, 7-column records ========
mk keep; gcs_clear
( cd "$W" && git checkout -q c && echo unmerged > unmerged.txt && git add . && g commit -q -m "unmerged local work" && git checkout -q main )
git -C "$O" update-ref refs/heads/topic "$(git -C "$O" rev-parse refs/heads/a)"
git -C "$W" symbolic-ref refs/heads/topic refs/heads/main
git -C "$W" worktree add -q "$T/keep/wt" feature/x
{ for b in a feature/x c topic; do printf '%s\t%s\n' "$b" "$(git -C "$O" rev-parse "refs/heads/$b")"; done; } > "$P"
BEFORE_LOCAL="$(git -C "$W" for-each-ref --format='%(refname) %(objectname) %(symref)' refs/heads | sort)"
out="$(run --exec 2>&1)"; rc=$?
{ [ "$rc" -eq 0 ] && [ "$BEFORE_LOCAL" = "$(git -C "$W" for-each-ref --format='%(refname) %(objectname) %(symref)' refs/heads | sort)" ]; } \
  && pass "local copies (merged, unmerged, symref, checked out) are all untouched" || fail "local changed: rc=$rc $out"
okk=1; for b in a feature/x c topic; do [ "$(state_of "$b")" = DELETED-REMOTE+LOCAL-KEPT ] || okk=0; done
[ "$okk" -eq 1 ] && [ "$(remote_heads)" = "refs/heads/main " ] && pass "all four remote branches deleted, each recorded as LOCAL-KEPT" || fail "keep records: $(cat "$REC") heads=$(remote_heads)"
{ grep -q 'git branch -d -- a' <<< "$out" && grep -q 'git branch -d -- topic' <<< "$out"; } && pass "the final list names every kept local copy" || fail "kept list: $out"

# only exit 0 and 1 are verdicts of the trigger check: 127 (command not found) is not overridable
mk py127; gcs_clear
mkdir -p "$T/stubs"; printf '#!/usr/bin/env bash\nexit 127\n' > "$T/stubs/py127"; chmod +x "$T/stubs/py127"
out="$(PYTHON="$T/stubs/py127" run --exec --allow-triggers 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q '(exit 127)' <<< "$out" && grep -q 'NOT-DELETED-TRIGGER-CHECK-ERROR' "$REC" && [ -z "$(remote_tags)" ] && [ "$(remote_heads)" = "$HEADS4" ]; } \
  && pass "trigger check exit 127 stops the run even with --allow-triggers" || fail "py127: rc=$rc $out"
printf '#!/usr/bin/env bash\nkill -TERM $$\n' > "$T/pysig"; chmod +x "$T/pysig"
out="$(PYTHON="$T/pysig" run --exec --allow-triggers 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'NOT-DELETED-TRIGGER-CHECK-ERROR' "$REC" && [ -z "$(remote_tags)" ]; } \
  && pass "trigger check killed by a signal stops the run even with --allow-triggers" || fail "pysig: rc=$rc $out"

# a 7-column record (no local_sha column) with a populated local_tag
mk col7; gcs_clear
( cd "$W" && git checkout -q c && echo unpushed > unpushed.txt && git add . && g commit -q -m "local only" && git checkout -q main )
run --exec >/dev/null 2>&1 || fail "col7: setup run failed"
cut -f1-7 "$REC" > "$T/col7.tsv"
vout="$(bash "$VERIFY" --repo "$W" --record "$T/col7.tsv" 2>&1)"; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'FAIL  c: local_tag is set but local_sha is not a full 40-character SHA' <<< "$vout"; } \
  && pass "verifier FAILs a 7-column row that has a local_tag" || fail "col7: rc=$rc $vout"
cut -f1-7 "$REC" | awk 'BEGIN{FS=OFS="\t"} NR>1 && $2=="c"{next} {print}' > "$T/col7b.tsv"
bash "$VERIFY" --repo "$W" --record "$T/col7b.tsv" >/dev/null 2>&1 && pass "verifier still accepts a 7-column row without a local_tag" || fail "col7b rejected"

if [ "$fails" -ne 0 ]; then echo "$fails test(s) failed" >&2; exit 1; fi
echo "all stale-archive tests passed"
