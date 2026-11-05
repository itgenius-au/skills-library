#!/usr/bin/env bash
# google-chat-update local gate: py_compile + pytest for the chat-post.py helper.
# Exits non-zero on any failure.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SCRIPTS="$(dirname "$DIR")"
rc=0

echo "== py_compile =="
if python3 -m py_compile "$SCRIPTS/chat-post.py"; then echo "compile OK"; else rc=1; fi

echo "== pytest =="
if python3 -m pytest "$DIR" -q; then :; else rc=1; fi

if [ "$rc" -ne 0 ]; then echo "TESTS FAILED" >&2; exit 1; fi
echo "ALL TESTS PASSED"
