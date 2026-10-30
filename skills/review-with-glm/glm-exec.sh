#!/usr/bin/env bash
# glm-exec.sh - safe wrapper around a z.ai (GLM) chat-completions call for the review-with-glm skill.
#
# z.ai ships NO headless CLI (ZCODE is a GUI app), so unlike a Codex/Gemini CLI wrapper this
# talks to the HTTP API directly (via glm_call.py, stdlib only). It encodes the invocation
# rules in ONE place so every caller inherits them:
#   - needs ZAI_API_KEY in the environment (load it from your own secret manager first)
#   - pins the model (the MODEL variable below: the ONE place the model name is set) and the
#     endpoint (default the Coding-Plan endpoint)
#   - passes the PROMPT via a temp file (diffs get large; dodges ARG_MAX and quoting)
#   - classifies failures in glm_call.py: 1113 unfunded / auth / transient - each SURFACED,
#     never mistaken for a code finding and never guessed around.
#
# This wrapper is the OpenAI-compatible (direct-HTTP) path. The agentic `claude -p`-on-z.ai
# path (Anthropic-compatible endpoint) is a separate documented recipe in the SKILL, pending
# a live smoke test - it is NOT driven by this script.
#
# Usage:
#   glm-exec.sh [--model M] [--endpoint coding|general] [--max-tokens N] [--temp T] \
#               [--system "SYS"] [--retries N] [--timeout SECS] \
#               ( -- "PROMPT"  |  --prompt-file PATH )
#   Give the PROMPT after '--' as one quoted argument, OR (preferred for large diffs)
#   pass a file with --prompt-file to dodge ARG_MAX entirely. The calling agent assembles the
#   review/coding context (git diff, file contents, plan text) INTO the prompt - GLM only sees
#   what you send.
#
# Env: ZAI_API_KEY (required). GLM_CALL_BIN overrides the python helper (test harness).
#
# Exit codes: 0 on a real answer; 1 if GLM failed (unfunded/auth/transient-exhausted, surfaced);
#             2 on bad args / missing prerequisite (e.g. python3 not installed).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLM_CALL="${GLM_CALL_BIN:-$SCRIPT_DIR/glm_call.py}"

die() { echo "glm-exec.sh: $*" >&2; exit 2; }
need() { [ "$1" -ge 2 ] || die "missing value for $2"; }
is_nonneg_int() { case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac; }

# python3 is a hard dependency (the HTTP call). Fail early and clearly.
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH - required to call GLM. Install python3."

MODEL="glm-5.2"   # the only place the model name is set; SKILL.md says "the default model"
ENDPOINT="coding"
# The default model reasons heavily (100s of tokens before the final answer); too low a cap leaves
# `content` empty or truncates the review. The default matches the canonical review call
# (--max-tokens 64000), so a caller that omits the flag does not truncate: 4096 cut off a
# diff review and 32000 cut off a plan review that completed at 64000.
MAX_TOKENS="64000"
TEMPERATURE="0.3"
RETRIES="1"
TIMEOUT="600"
SYSTEM=""
SYSTEM_SET=0
PROMPT=""
PROMPT_SET=0
PROMPT_FILE_IN=""

PROMPT_FILE=""
SYSTEM_FILE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --model)      need "$#" "$1"; MODEL="$2"; shift 2 ;;
    --endpoint)   need "$#" "$1"; ENDPOINT="$2"; shift 2 ;;
    --max-tokens) need "$#" "$1"; MAX_TOKENS="$2"; shift 2 ;;
    --temp|--temperature) need "$#" "$1"; TEMPERATURE="$2"; shift 2 ;;
    --system)     need "$#" "$1"; SYSTEM="$2"; SYSTEM_SET=1; shift 2 ;;
    --retries)    need "$#" "$1"; RETRIES="$2"; shift 2 ;;
    --timeout)    need "$#" "$1"; TIMEOUT="$2"; shift 2 ;;
    --prompt-file) need "$#" "$1"; PROMPT_FILE_IN="$2"; PROMPT_SET=1; shift 2 ;;
    --)           [ -z "$PROMPT_FILE_IN" ] || die "give the PROMPT once: --prompt-file or '-- PROMPT', not both"
                  shift; PROMPT="${1:-}"; PROMPT_SET=1; shift || true
                  [ $# -eq 0 ] || echo "glm-exec.sh: warning: ignoring $# arg(s) after PROMPT - quote the PROMPT as one argument, or use --prompt-file" >&2
                  break ;;
    *)            die "unknown arg: $1 (did you forget '--' before the PROMPT, or mean --prompt-file?)" ;;
  esac
done

# Validate numeric args so a bad value fails loudly, not silently (e.g. --retries -1).
is_nonneg_int "$MAX_TOKENS" || die "--max-tokens must be a non-negative integer (got '$MAX_TOKENS')"
is_nonneg_int "$RETRIES"    || die "--retries must be a non-negative integer (got '$RETRIES')"
is_nonneg_int "$TIMEOUT"    || die "--timeout must be a non-negative integer (got '$TIMEOUT')"

[ "$PROMPT_SET" = 1 ] || die "no PROMPT given (pass it after '--' or via --prompt-file)"
if [ -n "$PROMPT_FILE_IN" ]; then
  [ -f "$PROMPT_FILE_IN" ] || die "--prompt-file not found: $PROMPT_FILE_IN"
  [ -s "$PROMPT_FILE_IN" ] || die "--prompt-file is empty: $PROMPT_FILE_IN"
else
  [ -n "$PROMPT" ] || die "empty PROMPT"
fi

# Resolve the endpoint keyword -> full chat/completions URL. A literal URL is allowed ONLY if it
# is an https://api.z.ai/ endpoint - we attach the Bearer key, so never send it elsewhere or in
# cleartext.
case "$ENDPOINT" in
  coding)              GLM_URL="https://api.z.ai/api/coding/paas/v4/chat/completions" ;;
  general)             GLM_URL="https://api.z.ai/api/paas/v4/chat/completions" ;;
  anthropic)           die "endpoint 'anthropic' is the agentic claude -p path, not this direct-HTTP wrapper. See the SKILL's agentic recipe." ;;
  https://api.z.ai/*)  GLM_URL="$ENDPOINT" ;;
  http://*|https://*)  die "refusing to send the API key to '$ENDPOINT' - only https://api.z.ai/... is allowed (no other host, no cleartext http)." ;;
  *)                   die "unknown --endpoint: $ENDPOINT (coding|general or an https://api.z.ai/ URL)" ;;
esac

[ -n "${ZAI_API_KEY:-}" ] || die "ZAI_API_KEY is not set. Export your z.ai key (or load it from your secret manager) before calling this wrapper."
export ZAI_API_KEY

# Prompt (and optional system) go through temp files - diffs get large.
PROMPT_FILE="$(mktemp "${TMPDIR:-/tmp}/glm-exec.XXXXXX")" || die "mktemp failed (no writable temp dir?)"
cleanup() { rm -f "${PROMPT_FILE:-}" "${SYSTEM_FILE:-}"; }
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM
if [ -n "$PROMPT_FILE_IN" ]; then
  cat "$PROMPT_FILE_IN" > "$PROMPT_FILE"
else
  printf '%s' "$PROMPT" > "$PROMPT_FILE"
fi

ARGS=("$PROMPT_FILE")
if [ "$SYSTEM_SET" = 1 ] && [ -n "$SYSTEM" ]; then
  SYSTEM_FILE="$(mktemp "${TMPDIR:-/tmp}/glm-exec-sys.XXXXXX")" || die "mktemp failed"
  printf '%s' "$SYSTEM" > "$SYSTEM_FILE"
  ARGS+=("$SYSTEM_FILE")
fi

GLM_URL="$GLM_URL" GLM_MODEL="$MODEL" GLM_MAX_TOKENS="$MAX_TOKENS" \
GLM_TEMPERATURE="$TEMPERATURE" GLM_RETRIES="$RETRIES" GLM_TIMEOUT="$TIMEOUT" \
  python3 "$GLM_CALL" "${ARGS[@]}"
exit $?
