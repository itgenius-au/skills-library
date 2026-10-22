#!/usr/bin/env bash
# codex-exec.sh - safe wrapper around `codex exec` for the review-with-codex / review-debate skills.
#
# Encodes the mandatory invocation rules in ONE place so every caller (the skills AND
# ad-hoc shell use) inherits them, and adds a liveness watchdog so a wedged model/auth
# handshake can't silently eat an hour.
#
# What it always does:
#   - pins the model (default gpt-6-astra) and reasoning effort (default xhigh)
#   - `< /dev/null` so codex never blocks waiting on stdin ("Codex is hung" #1 cause)
#   - `--skip-git-repo-check` (no-op inside a git repo; required outside one)
#   - picks the sandbox by review tier (see --mode)
#   - liveness watchdog: no output within --first-output secs => kill, exit 124, tell you to relaunch attached
#   - hard ceiling: --timeout secs
#
# Sandbox tiers (matches review-with-codex SKILL.md "Sandbox decision tree"):
#   --mode review   -> -s read-only                         (DEFAULT. No execution. Safest. Can't mutate.)
#   --mode inspect  -> --sandbox workspace-write            (read repo state: git diff, file reads, no-network unit tests)
#   --mode full     -> --sandbox workspace-write + network  (run the project's full suite/build that needs the network)
#   --mode danger   -> -s danger-full-access               (last resort: tests that also write outside the workspace)
#   --net           -> add network (force sandbox_workspace_write.network_access=true); upgrades review->full
#   --add-dir DIR   -> extra writable dir (repeatable), for suites that write to a sibling path
#
# IMPORTANT: a command that fails ONLY under a tighter sandbox (Could not resolve host,
# Connection refused, Operation not permitted, Read-only file system) is a SANDBOX ARTIFACT,
# not a confirmed bug. Re-run at a looser tier before reporting it as a finding.
#
# Usage:
#   codex-exec.sh [--mode review|inspect|full|danger] [--dir DIR] [--model M] [--effort E] \
#                 [--net] [--add-dir DIR]... [--first-output SECS] [--timeout SECS] \
#                 ( --prompt-file PATH | -- "PROMPT" )
#   Prefer --prompt-file: the calling command then holds only literal paths, which restrictive agent
#   harnesses allow (some refuse `-- "$(cat f)"` in a worktree session).
#   NB: with `--`, quote the PROMPT as a single argument.
#
# Env: CODEX_BIN overrides the `codex` binary (used by the test harness). CODEX_REVIEW_MODEL changes the
#      default model pin (an explicit --model still wins).
#
# Exit codes: codex's own rc on completion; 124 if killed by the watchdog/timeout; 2 on bad args.

set -uo pipefail

CODEX_BIN="${CODEX_BIN:-codex}"
MODEL="${CODEX_REVIEW_MODEL:-gpt-6-astra}"
EFFORT="xhigh"
MODE="review"
DIR="."
NET=0
FIRST_OUTPUT=120
TIMEOUT=900
PROMPT=""
PROMPT_SET=0
PROMPT_FILE=""
PID=""
OUT=""
EXTRA_DIRS=()

die() { echo "codex-exec.sh: $*" >&2; exit 2; }
# Require that a value argument follows the current flag (guards the bash 3.2
# `shift 2` infinite-loop when an option is the last token).
need() { [ "$1" -ge 2 ] || die "missing value for $2"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --mode)         need "$#" "$1"; MODE="$2"; shift 2 ;;
    --dir)          need "$#" "$1"; DIR="$2"; shift 2 ;;
    --model)        need "$#" "$1"; MODEL="$2"; shift 2 ;;
    --effort)       need "$#" "$1"; EFFORT="$2"; shift 2 ;;
    --add-dir)      need "$#" "$1"; EXTRA_DIRS+=("$2"); shift 2 ;;
    --first-output) need "$#" "$1"; FIRST_OUTPUT="$2"; shift 2 ;;
    --timeout)      need "$#" "$1"; TIMEOUT="$2"; shift 2 ;;
    --net)          NET=1; shift ;;
    --prompt-file)  need "$#" "$1"; PROMPT_FILE="$2"; shift 2 ;;
    --)             shift; PROMPT="${1:-}"; PROMPT_SET=1; shift || true
                    [ $# -eq 0 ] || echo "codex-exec.sh: warning: ignoring $# arg(s) after PROMPT - quote the PROMPT as one argument" >&2
                    break ;;
    *)              die "unknown arg: $1 (did you forget '--' before the PROMPT, or mean --prompt-file?)" ;;
  esac
done

if [ -n "$PROMPT_FILE" ]; then
  [ "$PROMPT_SET" = 0 ] || die "give the PROMPT once: --prompt-file or '-- PROMPT', not both"
  [ -f "$PROMPT_FILE" ] || die "--prompt-file not found: $PROMPT_FILE"
  PROMPT="$(cat "$PROMPT_FILE")"; PROMPT_SET=1
fi
[ "$PROMPT_SET" = 1 ] && [ -n "$PROMPT" ] || die "no PROMPT given (pass it after '--' or via --prompt-file; an empty prompt file counts as none)"
# One argv string is capped at 131072 BYTES on Linux (MAX_ARG_STRLEN); fail clearly, not with E2BIG.
PROMPT_BYTES="$(LC_ALL=C; printf '%s' "${#PROMPT}")"  # bytes, not characters
[ "$PROMPT_BYTES" -le 131000 ] || die "PROMPT is $PROMPT_BYTES bytes; the limit for one argument is ~131000. Trim it (Codex reads the repo itself; do not inline large diffs)."

# The watchdog knobs must be positive integers. A non-numeric value makes every
# [ "$WAITED" -ge "$FIRST_OUTPUT" ] test error out, which would silently disable the
# liveness guard: the exact failure the wrapper exists to prevent.
is_pos_int() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -gt 0 ]; }
is_pos_int "$FIRST_OUTPUT" || die "--first-output must be a positive integer (got: '$FIRST_OUTPUT')"
is_pos_int "$TIMEOUT"      || die "--timeout must be a positive integer (got: '$TIMEOUT')"

# --net only makes sense with a workspace-write tier. Read-only review + --net is
# effectively the full tier (workspace-write + network), so name it honestly rather
# than mislabelling it "inspect" (which the mode table defines as no-network).
if [ "$NET" = 1 ] && [ "$MODE" = "review" ]; then
  MODE="full"
  echo "codex-exec.sh: --net needs workspace-write; upgrading --mode review -> full (workspace-write + network)" >&2
fi

# Build the sandbox flag set for the chosen tier.
SANDBOX=()
case "$MODE" in
  review)  SANDBOX=(-s read-only) ;;
  inspect) SANDBOX=(--sandbox workspace-write) ;;
  full)    SANDBOX=(--sandbox workspace-write -c 'sandbox_workspace_write.network_access=true') ;;
  danger)  SANDBOX=(-s danger-full-access) ;;
  *)       die "unknown --mode: $MODE (review|inspect|full|danger)" ;;
esac
if [ "$NET" = 1 ] && [ "$MODE" != "full" ] && [ "$MODE" != "danger" ]; then
  SANDBOX+=(-c 'sandbox_workspace_write.network_access=true')
fi
for d in ${EXTRA_DIRS+"${EXTRA_DIRS[@]}"}; do
  SANDBOX+=(--add-dir "$d")
done

# Kill the whole process group led by PID (a negative pid signals the group), so a
# Codex backend child can't outlive a single-pid kill. Falls back to the bare pid if
# the group send fails. PID is a group leader because the launch runs under `set -m`.
kill_tree() { kill -9 "-$PID" 2>/dev/null || kill -9 "$PID" 2>/dev/null; }
cleanup() { [ -n "${PID:-}" ] && kill_tree; rm -f "${OUT:-}"; }
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

OUT="$(mktemp -t codex-exec.XXXXXX)" || die "mktemp failed (no writable temp dir?)"

# Launch in the background so we can watch it for liveness. `set -m` (job control)
# places the child in its OWN process group (leader pid == PID), so the watchdog can
# signal the whole tree and no Codex backend child survives. Job control is the
# portable mechanism here: macOS ships no `setsid`. Turn it back off right after so
# the rest of the script keeps default (non-job-control) behaviour.
set -m
"$CODEX_BIN" exec -m "$MODEL" -c "model_reasoning_effort=\"$EFFORT\"" \
  --skip-git-repo-check "${SANDBOX[@]}" -C "$DIR" "$PROMPT" < /dev/null > "$OUT" 2>&1 &
PID=$!
set +m

WAITED=0
STATE="ok"   # ok | wedged | timeout
while kill -0 "$PID" 2>/dev/null; do
  sleep 3
  WAITED=$((WAITED + 3))
  # If it exited during the sleep, stop watching and let `wait` collect the real rc
  # (prevents a false 'wedged' on a fast no-output exit).
  kill -0 "$PID" 2>/dev/null || break
  if [ ! -s "$OUT" ] && [ "$WAITED" -ge "$FIRST_OUTPUT" ]; then
    kill_tree; wait "$PID" 2>/dev/null || true; PID=""; STATE="wedged"; break
  fi
  if [ "$WAITED" -ge "$TIMEOUT" ]; then
    kill_tree; wait "$PID" 2>/dev/null || true; PID=""; STATE="timeout"; break
  fi
done

if [ "$STATE" = "wedged" ]; then
  echo "::CODEX-WEDGED:: no output within ${FIRST_OUTPUT}s - process killed." >&2
  echo "::CODEX-WEDGED:: this is almost always a model/ChatGPT-auth handshake hang, NOT slow work." >&2
  echo "::CODEX-WEDGED:: relaunch ATTACHED (foreground, no background task) so the startup failure is visible. Do not wait on it." >&2
  cat "$OUT"; exit 124
fi
if [ "$STATE" = "timeout" ]; then
  echo "::CODEX-TIMEOUT:: exceeded ${TIMEOUT}s - process killed. Scope the review smaller or raise --timeout." >&2
  cat "$OUT"; exit 124
fi

wait "$PID"; rc=$?
PID=""          # reaped - don't let the EXIT trap kill an unrelated reused pid
cat "$OUT"
exit "$rc"
