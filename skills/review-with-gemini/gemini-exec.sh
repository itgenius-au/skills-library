#!/usr/bin/env bash
# gemini-exec.sh - safe wrapper around headless `gemini -p` for the review-with-gemini / review-swarm skills.
#
# Encodes the mandatory invocation rules in ONE place so every caller (the skills AND ad-hoc shell
# use) inherits them, and so the calling agent's Bash command stays a plain, literal command. Some
# agent harnesses (Claude Code in a git-worktree session, for one) refuse `KEY=$(...)`,
# `export KEY=...`, and `-p "$(cat f)"`; this wrapper keeps all of that inside the script instead.
#
# What it always does:
#   - needs GEMINI_API_KEY in the environment (a free Google AI Studio key works). The key stays in
#     this process; the wrapper never writes it to disk.
#   - pins the model (the MODEL variable below: the ONE place model names live). If the DEFAULT pin
#     is refused (not found, no permission, no quota - e.g. a free key), re-runs once on
#     FALLBACK_MODEL, inside the same --timeout. An explicit --model is never swapped. Prints
#     "::GEMINI-MODEL:: <id>" on stderr: the model that ran.
#   - --approval-mode default + the bundled read-only --policy (review-policy.toml next to this script)
#   - -o text and --skip-trust (headless runs in an untrusted dir, e.g. a fresh worktree, misbehave)
#   - stdin = --stdin-file (review input such as a diff) or /dev/null (never blocks on stdin)
#   - runs with cwd = --dir, so Gemini's workspace is the repo under review
#   - hard ceiling: --timeout secs (no first-output watchdog: -o text can emit only at completion)
#
# Usage:
#   gemini-exec.sh [--dir DIR] [--model M] [--include-dir DIR]... [--stdin-file PATH] \
#                  [--timeout SECS] ( --prompt-file PATH | -- "PROMPT" )
#   Prefer --prompt-file (and --stdin-file for a diff): the calling command then holds only literal
#   paths, which restrictive agent harnesses allow.
#
# Env: GEMINI_API_KEY (required). GEMINI_BIN overrides the `gemini` binary (test harness).
# Exit codes: gemini's own rc on completion; 124 if killed by the timeout; 2 on bad args.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEMINI_BIN="${GEMINI_BIN:-gemini}"
POLICY="$SCRIPT_DIR/review-policy.toml"

# The only place model names are set. SKILL.md says "the default model" and "the fallback model".
MODEL="gemini-4-argon"
MODEL_DEFAULT=1
FALLBACK_MODEL="gemini-3.8-flash"
DIR="."
TIMEOUT=600
STDIN_FILE=""
PROMPT=""
PROMPT_SET=0
PROMPT_FILE_IN=""
PID=""
OUT=""
ERR=""
INCLUDE_DIRS=()

die() { echo "gemini-exec.sh: $*" >&2; exit 2; }
# Require that a value argument follows the current flag (guards the bash 3.2
# `shift 2` infinite-loop when an option is the last token).
need() { [ "$1" -ge 2 ] || die "missing value for $2"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)         need "$#" "$1"; DIR="$2"; shift 2 ;;
    --model)       need "$#" "$1"; MODEL="$2"; MODEL_DEFAULT=0; shift 2 ;;
    --include-dir) need "$#" "$1"; INCLUDE_DIRS+=("$2"); shift 2 ;;
    --stdin-file)  need "$#" "$1"; STDIN_FILE="$2"; shift 2 ;;
    --timeout)     need "$#" "$1"; TIMEOUT="$2"; shift 2 ;;
    --prompt-file) need "$#" "$1"; PROMPT_FILE_IN="$2"; shift 2 ;;
    --)            shift; PROMPT="${1:-}"; PROMPT_SET=1; shift || true
                   [ $# -eq 0 ] || echo "gemini-exec.sh: warning: ignoring $# arg(s) after PROMPT - quote the PROMPT as one argument, or use --prompt-file" >&2
                   break ;;
    *)             die "unknown arg: $1 (did you forget '--' before the PROMPT, or mean --prompt-file?)" ;;
  esac
done

if [ -n "$PROMPT_FILE_IN" ]; then
  [ "$PROMPT_SET" = 0 ] || die "give the PROMPT once: --prompt-file or '-- PROMPT', not both"
  [ -f "$PROMPT_FILE_IN" ] || die "--prompt-file not found: $PROMPT_FILE_IN"
  PROMPT="$(cat "$PROMPT_FILE_IN")"; PROMPT_SET=1
fi
[ "$PROMPT_SET" = 1 ] && [ -n "$PROMPT" ] || die "no PROMPT given (pass it after '--' or via --prompt-file; an empty prompt file counts as none)"
# One argv string is capped at 131072 BYTES on Linux (MAX_ARG_STRLEN); fail clearly, not with E2BIG.
PROMPT_BYTES="$(LC_ALL=C; printf '%s' "${#PROMPT}")"  # bytes, not characters
[ "$PROMPT_BYTES" -le 131000 ] || die "PROMPT is $PROMPT_BYTES bytes; the limit for one argument is ~131000. Put large input (a diff) in --stdin-file instead."
if [ -n "$STDIN_FILE" ]; then
  [ -f "$STDIN_FILE" ] || die "--stdin-file not found: $STDIN_FILE"
  # Absolute before the cd into --dir, so a relative path still resolves.
  case "$STDIN_FILE" in /*) ;; *) STDIN_FILE="$PWD/$STDIN_FILE" ;; esac
fi
is_pos_int() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -gt 0 ]; }
is_pos_int "$TIMEOUT" || die "--timeout must be a positive integer (got: '$TIMEOUT')"
[ -d "$DIR" ] || die "--dir does not exist: $DIR"
[ -f "$POLICY" ] || die "review policy missing: $POLICY"

[ -n "${GEMINI_API_KEY:-}" ] || die "GEMINI_API_KEY is not set. Get a key from Google AI Studio and export it (or load it from your secret manager) before calling this wrapper."
export GEMINI_API_KEY

kill_tree() { kill -9 "-$PID" 2>/dev/null || kill -9 "$PID" 2>/dev/null; }
cleanup() { [ -n "${PID:-}" ] && kill_tree; rm -f "${OUT:-}" "${ERR:-}"; }
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

OUT="$(mktemp -t gemini-exec.XXXXXX)" || die "mktemp failed (no writable temp dir?)"
ERR="$(mktemp -t gemini-exec-err.XXXXXX)" || die "mktemp failed (no writable temp dir?)"
IN="${STDIN_FILE:-/dev/null}"

# run_model <model> <seconds>: one gemini run into $OUT/$ERR. Sets STATE (ok|timeout) and RC.
run_model() {
  ARGS=( -p "$PROMPT" --approval-mode default --policy "$POLICY" -m "$1" -o text --skip-trust )
  for d in ${INCLUDE_DIRS+"${INCLUDE_DIRS[@]}"}; do
    ARGS+=( --include-directories "$d" )
  done
  # Launch in the background under job control so the timeout can kill the whole process group
  # (macOS ships no `setsid`). cwd = the repo under review.
  set -m
  ( cd "$DIR" && "$GEMINI_BIN" "${ARGS[@]}" < "$IN" ) > "$OUT" 2>"$ERR" &
  PID=$!
  set +m

  WAITED=0
  STATE="ok"
  while kill -0 "$PID" 2>/dev/null; do
    sleep 3
    WAITED=$((WAITED + 3))
    kill -0 "$PID" 2>/dev/null || break
    if [ "$WAITED" -ge "$2" ]; then
      kill_tree; wait "$PID" 2>/dev/null || true; PID=""; STATE="timeout"; RC=124; return
    fi
  done
  wait "$PID"; RC=$?
  PID=""
}

# A refusal of the MODEL itself (missing for this key, no permission, no quota, e.g. a free key on
# a pro model) - not a bad key (400) and not a busy server (503), which the skill retries instead.
# Only the CLI's stderr counts: review text on stdout can quote these tokens. CLI 0.63 reports a
# plain 503 storm as RetryableQuotaError, so only TerminalQuotaError (limit 0) counts as no quota.
model_refused() {
  grep -q -E 'ModelNotFoundError|NOT_FOUND|is not found for API version|PERMISSION_DENIED|RESOURCE_EXHAUSTED|TerminalQuotaError|(code|status): (403|404|429)([^0-9]|$)' "$ERR"
}

# One deadline for the whole call: the fallback gets only the time the first run left over.
START=$SECONDS
RAN="$MODEL"
run_model "$MODEL" "$TIMEOUT"
# Fall back once, only when the caller kept the default pin. An explicit --model is never swapped.
if [ "$STATE" = "ok" ] && [ "$RC" -ne 0 ] && [ "$MODEL_DEFAULT" = 1 ] && model_refused; then
  REMAIN=$((TIMEOUT - (SECONDS - START)))
  if [ "$REMAIN" -ge 30 ]; then
    echo "::GEMINI-FALLBACK:: $MODEL refused (not found, no permission or no quota for this key); re-running on $FALLBACK_MODEL with ${REMAIN}s left." >&2
    RAN="$FALLBACK_MODEL"
    run_model "$FALLBACK_MODEL" "$REMAIN"
  else
    echo "::GEMINI-FALLBACK:: $MODEL refused, but only ${REMAIN}s of --timeout left; not re-running on $FALLBACK_MODEL." >&2
  fi
fi
# The model that actually ran, for the report's MODEL: line.
echo "::GEMINI-MODEL:: $RAN" >&2

if [ "$STATE" = "timeout" ]; then
  echo "::GEMINI-TIMEOUT:: exceeded ${TIMEOUT}s - process killed. Scope the review smaller or raise --timeout." >&2
  cat "$ERR" >&2; cat "$OUT"; exit 124
fi

# gemini prints noisy startup warnings on stderr; forward them only on failure.
[ "$RC" -eq 0 ] || cat "$ERR" >&2
cat "$OUT"
exit "$RC"
