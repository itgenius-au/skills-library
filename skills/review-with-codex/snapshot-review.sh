#!/usr/bin/env bash
# snapshot-review.sh - review ONE checkpoint commit with Codex, read-only, from a plain copy.
#
#   snapshot-review.sh --repo <repo> --sha <checkpoint> --prompt-file <file> --out <file>
#                      [--base origin/main] [--ref <dir>]... [--effort high] [--timeout 600]
#
# It copies the checkpoint's tree into a new temp folder (`git archive`, so the reviewer can never
# touch your branch), writes `change.diff` against the MERGE-BASE with --base (a three-dot diff,
# so commits that landed on the base after you branched are not shown as yours), copies each
# --ref dir under `ref/` (for example the shared skills a change calls), puts the prompt at
# `REVIEW_PROMPT.md`, and runs `codex-exec.sh --mode review --dir <copy>` with the output in
# --out. Every argument is a literal path, so it runs in a worktree-bound session. It prints the
# copy path. It never writes the repo.
#
# Exit: codex-exec.sh's code (0 done, 124 watchdog or timeout); 2 bad arguments or a git error.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="" SHA="" PROMPT="" OUT="" BASE="origin/main" EFFORT="high" TIMEOUT="600"
REFS=()
die() { echo "snapshot-review: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --sha) SHA="${2:-}"; shift 2 ;;
    --prompt-file) PROMPT="${2:-}"; shift 2 ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --base) BASE="${2:-}"; shift 2 ;;
    --ref) REFS+=("${2:-}"); shift 2 ;;
    --effort) EFFORT="${2:-}"; shift 2 ;;
    --timeout) TIMEOUT="${2:-}"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[ -n "$REPO" ] && [ -n "$SHA" ] && [ -n "$PROMPT" ] && [ -n "$OUT" ] \
  || die "usage: --repo <repo> --sha <sha> --prompt-file <file> --out <file> [--base <ref>] [--ref <dir>]..."
[ -s "$PROMPT" ] || die "prompt file missing or empty: $PROMPT"
git -C "$REPO" rev-parse --verify -q "$SHA^{commit}" >/dev/null || die "not a commit in $REPO: $SHA"
git -C "$REPO" rev-parse --verify -q "$BASE^{commit}" >/dev/null || die "base not found in $REPO: $BASE"

COPY="$(mktemp -d "${TMPDIR:-/tmp}/snapshot-review.XXXXXX")"
git -C "$REPO" archive "$SHA" | tar -x -C "$COPY" || die "git archive failed"
git -C "$REPO" diff "$BASE...$SHA" > "$COPY/change.diff" || die "git diff failed"
for r in "${REFS[@]}"; do
  [ -d "$r" ] || die "--ref is not a directory: $r"
  mkdir -p "$COPY/ref"
  cp -R "$r" "$COPY/ref/"
done
cp "$PROMPT" "$COPY/REVIEW_PROMPT.md"
echo "snapshot-review: copy at $COPY ($(wc -l < "$COPY/change.diff") diff lines vs merge-base with $BASE)"

"$HERE/codex-exec.sh" --mode review --dir "$COPY" --effort "$EFFORT" --timeout "$TIMEOUT" \
  --prompt-file "$COPY/REVIEW_PROMPT.md" > "$OUT" 2>&1
rc=$?
echo "snapshot-review: codex exit $rc, output in $OUT"
exit "$rc"
