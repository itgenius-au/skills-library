#!/usr/bin/env bash
# session-vault full local gate: shellcheck, py_compile, pytest, bash behavior tests, the
# de-personalization scrub, and setup-vault.sh --dry-run (Checkpoint D).
set +e

SV="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rc=0

echo "===== shellcheck ====="
if find "$SV" -name '*.sh' -not -path '*/schedulers/*' -exec shellcheck {} +; then
  echo "shellcheck clean"
else
  rc=1
fi

echo "===== py_compile ====="
if find "$SV" -name '*.py' -exec python3 -m py_compile {} +; then
  echo "py_compile clean"
else
  rc=1
fi

echo "===== pytest ====="
if ( cd "$SV" && python3 -m pytest tests/ -q ); then :; else rc=1; fi

echo "===== bash behavior tests ====="
bash "$SV/tests/test_bq_timeout.sh"     || rc=1
bash "$SV/tests/test_hooks.sh"          || rc=1
bash "$SV/tests/test_disabled_noop.sh"  || rc=1

echo "===== scrub ====="
bash "$SV/scrub-check.sh" || rc=1

echo "===== setup-vault.sh --dry-run (Checkpoint D) ====="
SCRATCH="$(mktemp -d)"
printf '%s\n' '{ "gcp": {"personal_project":"agent-alex"}, "logging": {"enabled":true, "heartbeat_enabled":true, "backup_enabled":true} }' > "$SCRATCH/cfg.json"
if ITG_CONFIG="$SCRATCH/cfg.json" bash "$SV/setup-vault.sh" --dry-run; then :; else rc=1; fi
rm -rf "$SCRATCH"

echo "===== TOTAL rc=$rc ====="
exit "$rc"
