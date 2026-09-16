#!/usr/bin/env bash
# fable-exec.sh - safe wrapper around headless `claude -p` for the fable-review skill.
#
# Runs a SECOND, ISOLATED, READ-ONLY Claude Code instance as an independent second-opinion
# reviewer. "Fable" is just this skill's nickname for that process - YOU choose which model it
# runs, via config/env/flag (see below); the wrapper never hardcodes a model id. It encodes the
# mandatory invocation rules in ONE place so every caller (the skill AND ad-hoc shell use)
# inherits them, and adds a hard-timeout watchdog so a wedged run can't eat your session.
#
# Model/effort/timeout resolve in this order (first one set wins): CLI flag > env var
# (FABLE_REVIEW_MODEL / FABLE_REVIEW_EFFORT / FABLE_REVIEW_TIMEOUT) > ~/.claude/fable-review.config.json
# > built-in default. The model default is EMPTY (no --model flag passed at all), so an unconfigured
# run just falls back to whatever model your `claude` CLI already defaults to - it never assumes a
# specific model id exists on your account. The effort default is "high"; the timeout default is 900s.
#
# What it always does (flags empirically verified on claude v2.1.269 - check your own CLI's
# `claude -p --help` if a flag below is rejected; CLI flags do drift across versions):
#   - --permission-mode plan  : READ-ONLY. The reviewer reads files and runs read-only shell
#                               (git diff, grep, cat) to explore the repo ITSELF - self-exploring,
#                               not inline-only. It makes NO edits to the repo under review (plan
#                               mode may write only a scratch plan under ~/.claude/plans, never a
#                               project file), and a baked-in system prompt tells it to review, not plan.
#   - --strict-mcp-config     : with no --mcp-config given, loads ZERO MCP servers. No MCP latency,
#                               no interactive-auth MCP prompts wedging a headless run.
#   - --setting-sources user  : load only YOUR user settings, skipping the TARGET repo's PROJECT/LOCAL
#                               settings - so that repo's own hooks (e.g. a session-start reminder or
#                               an auto-commit hook) do NOT fire inside the nested review. Auth and
#                               model resolution still work normally.
#   - --output-format text    : plain text. NB: text mode emits the whole answer at COMPLETION, not
#                               streamed (see the watchdog note below).
#   - < /dev/null             : never blocks waiting on stdin.
#   - runs with cwd = --dir so `git diff` / file reads resolve against the target repo.
#
# WHY ONLY A HARD TIMEOUT, no first-output watchdog: `claude -p --output-format text` produces NO
# output until the run completes, so "no output yet" is the NORMAL state of a healthy review - a
# first-output watchdog would false-kill every real review. We keep ONLY a hard --timeout ceiling
# for a genuinely runaway/wedged run.
#
# WHY NOT --bare: --bare skips keychain reads, which breaks auth ("Not logged in, run /login").
# --setting-sources + --strict-mcp-config give the isolation we need while auth keeps working.
# WHY NOT --restricted: it removes the shell tool, so the reviewer can no longer run `git diff` - it
# degrades to an inline-only reviewer. Plan mode keeps the shell AND stays read-only.
#
# Usage:
#   fable-exec.sh [--dir DIR] [--model M] [--effort E] [--add-dir DIR]... [--timeout SECS] -- "PROMPT"
#   NB: quote the PROMPT as a single argument.
#
# Env: CLAUDE_BIN overrides the `claude` binary (used by a test harness).
#      FABLE_REVIEW_MODEL / FABLE_REVIEW_EFFORT / FABLE_REVIEW_TIMEOUT override the config file.
# Config: ~/.claude/fable-review.config.json (optional): {"model": "...", "effort": "...", "timeout": N}.
#         Read with jq if present, else python3, else skipped (flags/env still work either way).
# Exit codes: claude's own rc on completion; 124 if killed by the timeout; 3 if not logged in; 2 on bad args.

set -uo pipefail

CLAUDE_BIN="${CLAUDE_BIN:-claude}"
CONFIG_FILE="${FABLE_REVIEW_CONFIG:-$HOME/.claude/fable-review.config.json}"

# Resolve a config value with jq if available, else python3, else empty. Never fatal - a
# missing/unreadable/malformed config just means "no config value", not an error.
config_get() {
  key="$1"
  [ -f "$CONFIG_FILE" ] || return 0
  if command -v jq >/dev/null 2>&1; then
    jq -r --arg k "$key" '.[$k] // empty' "$CONFIG_FILE" 2>/dev/null
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c '
import json, sys
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
    v = d.get(sys.argv[2])
    print(v if v is not None else "")
except Exception:
    print("")
' "$CONFIG_FILE" "$key" 2>/dev/null
  fi
}

MODEL="${FABLE_REVIEW_MODEL:-$(config_get model)}"
EFFORT="${FABLE_REVIEW_EFFORT:-$(config_get effort)}"
EFFORT="${EFFORT:-high}"
DIR="."
TIMEOUT="${FABLE_REVIEW_TIMEOUT:-$(config_get timeout)}"
TIMEOUT="${TIMEOUT:-900}"
PROMPT=""
PROMPT_SET=0
PID=""
OUT=""
ERR=""
EXTRA_DIRS=()

die() { echo "fable-exec.sh: $*" >&2; exit 2; }
# Require that a value argument follows the current flag (guards the bash 3.2
# `shift 2` infinite-loop when an option is the last token).
need() { [ "$1" -ge 2 ] || die "missing value for $2"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)      need "$#" "$1"; DIR="$2"; shift 2 ;;
    --model)    need "$#" "$1"; MODEL="$2"; shift 2 ;;
    --effort)   need "$#" "$1"; EFFORT="$2"; shift 2 ;;
    --add-dir)  need "$#" "$1"; EXTRA_DIRS+=("$2"); shift 2 ;;
    --timeout)  need "$#" "$1"; TIMEOUT="$2"; shift 2 ;;
    --)         shift; PROMPT="${1:-}"; PROMPT_SET=1; shift || true
                [ $# -eq 0 ] || echo "fable-exec.sh: warning: ignoring $# arg(s) after PROMPT - quote the PROMPT as one argument" >&2
                break ;;
    *)          die "unknown arg: $1 (did you forget '--' before the PROMPT?)" ;;
  esac
done

[ "$PROMPT_SET" = 1 ] && [ -n "$PROMPT" ] || die "no PROMPT given (pass it after '--')"

# The timeout knob must be a positive integer, else the [ "$WAITED" -ge "$TIMEOUT" ]
# test errors out and silently disables the only watchdog we have.
is_pos_int() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -gt 0 ]; }
is_pos_int "$TIMEOUT" || die "--timeout must be a positive integer (got: '$TIMEOUT')"
[ -d "$DIR" ] || die "--dir does not exist: $DIR"

if [ -z "$MODEL" ]; then
  echo "fable-exec.sh: no model configured - falling back to your claude CLI's own default model." >&2
  echo "fable-exec.sh: for a deeper reasoning pass, set --model, FABLE_REVIEW_MODEL, or \"model\" in $CONFIG_FILE." >&2
fi

# Plan mode injects a five-phase "make a plan" workflow (Explore/Plan sub-agents, ExitPlanMode,
# ask-the-user). A headless REVIEWER must ignore all of that and just return findings, so bake the
# instruction in - every review carries it regardless of the caller's prompt.
REVIEWER_GUIDANCE="You are a code REVIEWER, not a planner. Ignore any plan-mode workflow instructions: do NOT spawn Explore/Plan sub-agents, do NOT call ExitPlanMode, do NOT ask the user questions, and do NOT write a plan file. Explore the repo read-only as needed (git diff, reading files), then return your review as your final assistant message."

# Assemble the claude args. The array always has -p ... so "${CLAUDE_ARGS[@]}" is never an
# empty expansion (which would trip `set -u` on bash 3.2 / macOS). --model is inserted only when
# set - an empty MODEL means "let the claude CLI use its own default", never an empty --model value.
CLAUDE_ARGS=( -p "$PROMPT" )
[ -n "$MODEL" ] && CLAUDE_ARGS+=( --model "$MODEL" )
CLAUDE_ARGS+=( --effort "$EFFORT"
  --permission-mode plan --strict-mcp-config --setting-sources user
  --append-system-prompt "$REVIEWER_GUIDANCE"
  --output-format text )
for d in ${EXTRA_DIRS+"${EXTRA_DIRS[@]}"}; do
  CLAUDE_ARGS+=( --add-dir "$d" )
done

# Kill the whole process group led by PID (a negative pid signals the group), so a claude
# child can't outlive a single-pid kill. Falls back to the bare pid. PID is a group leader
# because the launch runs under `set -m`.
kill_tree() { kill -9 "-$PID" 2>/dev/null || kill -9 "$PID" 2>/dev/null; }
cleanup() { [ -n "${PID:-}" ] && kill_tree; rm -f "${OUT:-}" "${ERR:-}"; }
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

OUT="$(mktemp -t fable-exec.XXXXXX)" || die "mktemp failed (no writable temp dir?)"
ERR="$(mktemp -t fable-exec-err.XXXXXX)" || die "mktemp failed (no writable temp dir?)"

# Launch in the background under job control (`set -m` -> child is its own process-group leader,
# so the watchdog can signal the whole tree; macOS ships no `setsid`). cwd = the target repo so
# git/file reads resolve. Turn job control back off right after.
set -m
( cd "$DIR" && "$CLAUDE_BIN" "${CLAUDE_ARGS[@]}" < /dev/null ) > "$OUT" 2>"$ERR" &
PID=$!
set +m

WAITED=0
STATE="ok"   # ok | timeout
while kill -0 "$PID" 2>/dev/null; do
  sleep 3
  WAITED=$((WAITED + 3))
  # If it exited during the sleep, stop watching and let `wait` collect the real rc.
  kill -0 "$PID" 2>/dev/null || break
  if [ "$WAITED" -ge "$TIMEOUT" ]; then
    kill_tree; wait "$PID" 2>/dev/null || true; PID=""; STATE="timeout"; break
  fi
done

if [ "$STATE" = "timeout" ]; then
  echo "::FABLE-TIMEOUT:: exceeded ${TIMEOUT}s - process killed. Scope the review smaller or raise --timeout." >&2
  cat "$ERR" >&2; cat "$OUT"; exit 124
fi

wait "$PID"; rc=$?
PID=""          # reaped - don't let the EXIT trap kill an unrelated reused pid
cat "$ERR" >&2  # forward claude's own stderr (startup warnings etc.) - keep it OUT of the review on stdout
cat "$OUT"      # the review itself: clean stdout so your MODEL: line leads

# Surface the not-logged-in case as a distinct code so a caller never mistakes an auth failure
# for a clean review. Gate on rc!=0 so a review whose text happens to mention "not logged in"
# (e.g. reviewing auth code) doesn't false-trigger. -qiE for portable alternation across grep flavours.
if [ "$rc" -ne 0 ] && grep -qiE "Please run /login|Not logged in" "$OUT" "$ERR"; then
  echo "::FABLE-NOAUTH:: claude is not logged in on this machine - run 'claude' interactively and sign in, then retry." >&2
  exit 3
fi
exit "$rc"
