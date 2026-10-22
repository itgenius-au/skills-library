#!/usr/bin/env bash
# fable-exec.sh - safe wrapper around headless `claude -p` for the review-with-claude / review-swarm skills.
#
# Runs a SECOND, ISOLATED, READ-ONLY Claude Code instance as an independent second-opinion
# reviewer. "Fable" is this skill's nickname for that process (point it at a deep-reasoning Claude
# model such as a Fable-tier model); the wrapper never assumes a specific model id exists on your
# account. It encodes the mandatory invocation rules in ONE place so every caller (the skill AND
# ad-hoc shell use) inherits them, and adds a hard-timeout watchdog so a wedged run can't eat your
# session.
#
# Model/effort/timeout resolve in this order (first one set wins): CLI flag > env var
# (REVIEW_WITH_CLAUDE_MODEL / REVIEW_WITH_CLAUDE_EFFORT / REVIEW_WITH_CLAUDE_TIMEOUT) >
# ~/.claude/review-with-claude.config.json > built-in default. The model default is EMPTY (no --model
# flag passed at all), so an unconfigured run just falls back to whatever model your `claude` CLI
# already defaults to. The effort default is "high". The timeout default follows effort: 1500 s at
# xhigh/max, 720 s otherwise.
#
# What it always does (flags verified on recent claude CLI versions - check `claude -p --help` if a
# flag below is rejected; CLI flags do drift across versions):
#   - --tools Read,Grep,Glob  : NO SHELL. The reviewer explores the repo ITSELF with Read/Grep/Glob
#                               (still self-exploring, NOT inline-only like GLM), but it has no Bash,
#                               Edit, Write or Agent tool, so it cannot run a script or write a file.
#                               This is the hard limit: plan mode alone is only an instruction to the
#                               model, and a plan-mode run once ran a script that emptied a file outside
#                               --dir. The OS sandbox is no substitute: it fails open without socat/bwrap.
#   - --diff-range RANGE      : the wrapper runs git FOR the reviewer in --dir (status, log, diff with no
#                               external diff tool or textconv), writes it to a temp file, adds that
#                               directory with --add-dir, and names the file in the prompt.
#   - --permission-mode plan  : kept as a second layer; a baked-in system prompt tells it to review, not plan.
#   - --strict-mcp-config     : with no --mcp-config given, loads ZERO MCP servers. No MCP latency,
#                               no interactive-auth MCP prompts wedging a headless run.
#   - --setting-sources user  : load only YOUR user settings, skipping the TARGET repo's PROJECT/LOCAL
#                               settings - so that repo's own hooks (e.g. a session-start reminder or
#                               an auto-commit hook) do NOT fire inside the nested review. Auth and
#                               model resolution still work normally.
#   - forces every sub-agent onto a cheap model: CLAUDE_CODE_SUBAGENT_MODEL=sonnet plus
#     CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1 (a backstop: with --tools the reviewer has no Agent tool).
#   - --output-format text    : plain text. NB: text mode emits the whole answer at COMPLETION, not
#                               streamed (see the watchdog note below).
#   - < /dev/null             : never blocks waiting on stdin.
#   - runs with cwd = --dir so file reads resolve against the target repo.
#
# WHY ONLY A HARD TIMEOUT, NO first-output watchdog (unlike codex-exec.sh): `claude -p --output-format
# text` produces NO output until the run completes, so "no output yet" is the NORMAL state of a healthy
# review - a first-output watchdog would false-kill every real review. We keep ONLY a hard --timeout
# ceiling for a genuinely runaway/wedged run.
#
# WHY NOT --bare: --bare skips keychain reads, which breaks auth ("Not logged in, run /login").
# --setting-sources + --strict-mcp-config give the isolation we need while auth keeps working.
# WHY NO GIT ALLOW LIST: a Bash(git ...) allow list is not a hard limit (`git diff --output=<path>`
# writes a file, and user-level allow rules or bypassPermissions still load), so the wrapper runs git.
#
# Usage:
#   fable-exec.sh [--dir DIR] [--model M] [--effort E] [--add-dir DIR]... [--timeout SECS] \
#                 [--diff-range RANGE] ( --prompt-file PATH | -- "PROMPT" )
#   --diff-range takes what `git diff` takes: `main...HEAD`, `<sha>..HEAD`, or `HEAD` (uncommitted).
#   --effort E is one of low|medium|high|xhigh|max; anything else exits 2.
#   Prefer --prompt-file: the calling command then holds only literal paths, which restrictive agent
#   harnesses allow (some refuse `-- "$(cat f)"` in a worktree session).
#   NB: with `--`, quote the PROMPT as a single argument.
#
# Env: CLAUDE_BIN overrides the `claude` binary (used by a test harness).
#      REVIEW_WITH_CLAUDE_MODEL / _EFFORT / _TIMEOUT override the config file.
#      REVIEW_WITH_CLAUDE_CONFIG points at a different config file.
# Config: ~/.claude/review-with-claude.config.json (optional): {"model": "...", "effort": "...", "timeout": N}.
#         Read with jq if present, else python3, else skipped (flags/env still work either way).
# Exit codes: claude's own rc on completion; 124 if killed by the timeout; 3 if not logged in; 2 on bad args.

set -uo pipefail

CLAUDE_BIN="${CLAUDE_BIN:-claude}"
CONFIG_FILE="${REVIEW_WITH_CLAUDE_CONFIG:-$HOME/.claude/review-with-claude.config.json}"

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

MODEL="${REVIEW_WITH_CLAUDE_MODEL:-$(config_get model)}"
EFFORT="${REVIEW_WITH_CLAUDE_EFFORT:-$(config_get effort)}"
EFFORT="${EFFORT:-high}"
SUBAGENT_MODEL="sonnet"
DIR="."
TIMEOUT="${REVIEW_WITH_CLAUDE_TIMEOUT:-$(config_get timeout)}"
TIMEOUT_SET=0
[ -z "$TIMEOUT" ] || TIMEOUT_SET=1
PROMPT=""
PROMPT_SET=0
PROMPT_FILE=""
PID=""
OUT=""
ERR=""
EXTRA_DIRS=()
DIFF_RANGE=""
CTX_DIR=""

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
    --timeout)  need "$#" "$1"; TIMEOUT="$2"; TIMEOUT_SET=1; shift 2 ;;
    --prompt-file) need "$#" "$1"; PROMPT_FILE="$2"; shift 2 ;;
    --diff-range) need "$#" "$1"; DIFF_RANGE="$2"; shift 2 ;;
    --)         shift; PROMPT="${1:-}"; PROMPT_SET=1; shift || true
                [ $# -eq 0 ] || echo "fable-exec.sh: warning: ignoring $# arg(s) after PROMPT - quote the PROMPT as one argument" >&2
                break ;;
    *)          die "unknown arg: $1 (did you forget '--' before the PROMPT, or mean --prompt-file?)" ;;
  esac
done

if [ -n "$PROMPT_FILE" ]; then
  [ "$PROMPT_SET" = 0 ] || die "give the PROMPT once: --prompt-file or '-- PROMPT', not both"
  [ -f "$PROMPT_FILE" ] || die "--prompt-file not found: $PROMPT_FILE"
  PROMPT="$(cat "$PROMPT_FILE")"; PROMPT_SET=1
fi
[ "$PROMPT_SET" = 1 ] && [ -n "$PROMPT" ] || die "no PROMPT given (pass it after '--' or via --prompt-file; an empty prompt file counts as none)"
[ -d "$DIR" ] || die "--dir does not exist: $DIR"

if [ -z "$MODEL" ]; then
  echo "fable-exec.sh: no model configured - falling back to your claude CLI's own default model." >&2
  echo "fable-exec.sh: for a deeper reasoning pass, set --model, REVIEW_WITH_CLAUDE_MODEL, or \"model\" in $CONFIG_FILE." >&2
fi

# Kill the whole process group led by PID (a negative pid signals the group), so a claude
# child can't outlive a single-pid kill. Falls back to the bare pid. PID is a group leader
# because the launch runs under `set -m`. The traps go in before any temp file or dir exists,
# so every later exit (a die, a signal) removes them.
kill_tree() { kill -9 "-$PID" 2>/dev/null || kill -9 "$PID" 2>/dev/null; }
cleanup() { [ -n "${PID:-}" ] && kill_tree; rm -f "${OUT:-}" "${ERR:-}"; [ -z "${CTX_DIR:-}" ] || rm -rf "$CTX_DIR"; }
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

# The reviewer has no shell, so the wrapper runs the git reads for it and hands over one file.
# The -c settings stop a local repo config from running a program (fsmonitor, a gpg.program).
if [ -n "$DIFF_RANGE" ]; then
  case "$DIFF_RANGE" in -*) die "--diff-range must be a revision range, not an option: $DIFF_RANGE" ;; esac
  CTX_DIR="$(mktemp -d -t fable-ctx.XXXXXX)" || die "mktemp failed (no writable temp dir?)"
  CTX="$CTX_DIR/git-context.txt"
  # No network and no lazy fetch: a partial clone's promisor remote could be an ext:: command.
  # GIT_ALLOW_PROTOCOL wins over any protocol.<name>.allow in the repo config; GIT_NO_LAZY_FETCH
  # (git 2.44+) stops the fetch outright. Each call checks its own status: `set -e` is ignored
  # inside an `if !` condition.
  GIT=(env GIT_ALLOW_PROTOCOL=none GIT_NO_LAZY_FETCH=1
       git --no-pager --no-optional-locks -c core.fsmonitor=false -c log.showSignature=false -C "$DIR")
  if ! ( echo "## git status --short"
         "${GIT[@]}" status --short || exit 1
         case "$DIFF_RANGE" in *..*) echo; echo "## git log --oneline $DIFF_RANGE"
                                   "${GIT[@]}" log --oneline -n 200 "$DIFF_RANGE" -- || exit 1 ;; esac
         echo; echo "## git diff $DIFF_RANGE"
         "${GIT[@]}" diff --no-ext-diff --no-textconv "$DIFF_RANGE" -- || exit 1
       ) > "$CTX" 2> "$CTX_DIR/git-err.txt"; then
    die "git diff failed for --diff-range '$DIFF_RANGE' in $DIR: $(cat "$CTX_DIR/git-err.txt")"
  fi
  rm -f "$CTX_DIR/git-err.txt"
  EXTRA_DIRS+=("$CTX_DIR")
  PROMPT="$PROMPT

Git context: you have no shell, so the review wrapper ran git for you. Read $CTX first. It holds \`git status --short\`, the commit list for the range, and \`git diff $DIFF_RANGE\`."
fi
# One argv string is capped at 131072 BYTES on Linux (MAX_ARG_STRLEN); fail clearly, not with E2BIG.
PROMPT_BYTES="$(LC_ALL=C; printf '%s' "${#PROMPT}")"  # bytes, not characters
[ "$PROMPT_BYTES" -le 131000 ] || die "PROMPT is $PROMPT_BYTES bytes; the limit for one argument is ~131000. Trim it (the reviewer reads the repo itself; do not inline large diffs)."

# Reject an unknown effort before launch, so a typo (e.g. XHIGH) fails fast instead of silently
# getting the shorter ceiling. These are the values `claude --help` lists for --effort.
case "$EFFORT" in
  low|medium|high|xhigh|max) ;;
  *) die "--effort must be one of low|medium|high|xhigh|max (got: '$EFFORT')" ;;
esac

# Default ceiling follows effort: xhigh/max think longer than high. An explicit timeout wins.
if [ "$TIMEOUT_SET" = 0 ]; then
  case "$EFFORT" in xhigh|max) TIMEOUT=1500 ;; *) TIMEOUT=720 ;; esac
fi

# The timeout knob must be a positive integer, else the [ "$WAITED" -ge "$TIMEOUT" ]
# test errors out and silently disables the only watchdog we have.
is_pos_int() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -gt 0 ]; }
is_pos_int "$TIMEOUT" || die "--timeout must be a positive integer (got: '$TIMEOUT')"

# Plan mode injects a five-phase "make a plan" workflow (Explore/Plan sub-agents, ExitPlanMode,
# ask-the-user). A headless REVIEWER must ignore all of that and just return findings, so bake the
# instruction in - every review carries it regardless of the caller's prompt.
REVIEWER_GUIDANCE="You are a code REVIEWER, not a planner. Ignore any plan-mode workflow instructions: do NOT spawn Explore/Plan sub-agents, do NOT call ExitPlanMode, do NOT ask the user questions, and do NOT write a plan file. You have no shell: explore the repo with Read, Grep and Glob only. If the prompt names a git context file, read it first. Then return your review as your final assistant message."

# Assemble the claude args. The array always has -p ... so "${CLAUDE_ARGS[@]}" is never an
# empty expansion (which would trip `set -u` on bash 3.2 / macOS). --model is inserted only when
# set - an empty MODEL means "let the claude CLI use its own default", never an empty --model value.
CLAUDE_ARGS=( -p "$PROMPT" )
[ -n "$MODEL" ] && CLAUDE_ARGS+=( --model "$MODEL" )
CLAUDE_ARGS+=( --effort "$EFFORT"
  --permission-mode plan --tools "Read,Grep,Glob" --strict-mcp-config --setting-sources user
  --append-system-prompt "$REVIEWER_GUIDANCE"
  --output-format text )
for d in ${EXTRA_DIRS+"${EXTRA_DIRS[@]}"}; do
  CLAUDE_ARGS+=( --add-dir "$d" )
done

OUT="$(mktemp -t fable-exec.XXXXXX)" || die "mktemp failed (no writable temp dir?)"
ERR="$(mktemp -t fable-exec-err.XXXXXX)" || die "mktemp failed (no writable temp dir?)"

# Launch in the background under job control (`set -m` -> child is its own process-group leader,
# so the watchdog can signal the whole tree; macOS ships no `setsid`). cwd = the target repo so
# file reads resolve. Turn job control back off right after.
set -m
( cd "$DIR" && CLAUDE_CODE_SUBAGENT_MODEL="$SUBAGENT_MODEL" CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1 \
    "$CLAUDE_BIN" "${CLAUDE_ARGS[@]}" < /dev/null ) > "$OUT" 2>"$ERR" &
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
