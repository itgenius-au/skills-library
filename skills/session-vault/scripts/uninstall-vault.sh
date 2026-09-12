#!/usr/bin/env bash
# session-vault uninstall: remove the hooks, scheduler, installed scripts, and isolated gcloud
# config. LEAVES your BigQuery data, GCS backups, the service account, and its GSM secret in
# place (pass --purge-cloud to also remove the SA + key secret; data is never deleted).
#
# Idempotent. --dry-run prints the plan and makes no changes.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=0
ASSUME_YES=0
PURGE_CLOUD=0

usage() {
  cat <<'EOF'
Usage: uninstall-vault.sh [--dry-run] [--yes] [--purge-cloud]
  --dry-run      Print the plan and exit; make no changes.
  --yes, -y      Skip the confirmation prompt.
  --purge-cloud  Also delete the service account + its GSM key secret (data is kept).
EOF
}

for a in "$@"; do
  case "$a" in
    --dry-run) DRY_RUN=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    --purge-cloud) PURGE_CLOUD=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $a" >&2; usage; exit 2 ;;
  esac
done

log()  { printf '%s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }

# A directory is safe to `rm -rf` only if it is a non-empty absolute path UNDER $HOME and is not
# $HOME itself. Guards against a misconfigured gcloud_config_dir (e.g. "~") nuking the home dir.
safe_rm_dir() {
  local d="$1"
  # An empty/relative $HOME would make "$HOME"/?* match "/tmp", "/.claude/...", etc. Refuse.
  case "${HOME:-}" in /?*) ;; *) return 1 ;; esac
  # Collapse trailing slashes so "$HOME/" / "$HOME//" reduce to "$HOME" and are rejected.
  while [ "$d" != "${d%/}" ]; do d="${d%/}"; done
  case "$d" in
    ""|"$HOME") return 1 ;;
    *..*|*//*) return 1 ;;   # no parent traversal, no doubled separators
    "$HOME"/?*) return 0 ;;  # a real path strictly under $HOME
    *) return 1 ;;
  esac
}

# Hard stop before any mutation if HOME is not a real absolute path.
case "${HOME:-}" in /?*) ;; *) echo "HOME is not a usable absolute path; refusing to run." >&2; exit 1 ;; esac

VAULT_ENV="$(python3 "$DIR/_vault.py" --shell-env 2>/dev/null || true)"
eval "$VAULT_ENV"

INSTALL_DIR="$HOME/.claude/session-vault"
SETTINGS="$HOME/.claude/settings.json"
LABEL_PREFIX="com.itgenius.session-vault"
GCLOUD_CONFIG="${VAULT_GCLOUD_CONFIG:-$HOME/.config/gcloud-vault}"
PROJECT="${VAULT_BQ_PROJECT:-}"
SA_SECRET="${VAULT_SA_SECRET:-local-session-sync-sa-key}"
SA_NAME="local-session-sync"
OS="$(uname -s)"

step "Plan"
log "  Remove hooks from      : $SETTINGS"
log "  Remove scheduler       : $([ "$OS" = Darwin ] && echo 'launchd agents' || echo 'cron + systemd timer')"
log "  Remove install dir     : $INSTALL_DIR"
log "  Remove isolated config : $GCLOUD_CONFIG"
if [ "$PURGE_CLOUD" = 1 ]; then
  log "  Purge cloud            : delete SA ${SA_NAME}@${PROJECT} + GSM secret ${SA_SECRET}"
else
  log "  Cloud resources        : KEPT (dataset, tables, bucket, SA, secret). Use --purge-cloud to remove the SA + secret."
fi

if [ "$DRY_RUN" = 0 ] && [ "$ASSUME_YES" = 0 ]; then
  printf '\nProceed? [y/N] '
  read -r ans
  case "$ans" in y|Y|yes|YES) ;; *) log "Aborted."; exit 1 ;; esac
fi

# --- hooks ---
step "Hooks"
if [ "$DRY_RUN" = 1 ]; then
  python3 "$DIR/lib/merge-hooks.py" --settings "$SETTINGS" \
    --prompt-hook "${INSTALL_DIR}/bq-log-prompt.sh" --response-hook "${INSTALL_DIR}/bq-log-response.sh" --remove --dry-run
else
  MH="${INSTALL_DIR}/lib/merge-hooks.py"; [ -f "$MH" ] || MH="$DIR/lib/merge-hooks.py"
  python3 "$MH" --settings "$SETTINGS" \
    --prompt-hook "${INSTALL_DIR}/bq-log-prompt.sh" --response-hook "${INSTALL_DIR}/bq-log-response.sh" --remove
fi

# --- scheduler ---
step "Scheduler"
if [ "$OS" = "Darwin" ]; then
  for name in bq-sync vault-flush backup heartbeat; do
    label="${LABEL_PREFIX}.${name}"
    plist="${HOME}/Library/LaunchAgents/${label}.plist"
    if [ "$DRY_RUN" = 1 ]; then
      [ -f "$plist" ] && log "  [dry-run] bootout + rm ${label}"
    else
      launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true
      rm -f "$plist"
    fi
  done
  [ "$DRY_RUN" = 0 ] && log "  launchd agents removed"
else
  if [ "$DRY_RUN" = 1 ]; then
    log "  [dry-run] strip session-vault cron lines + disable systemd heartbeat timer"
  else
    crontab -l 2>/dev/null | awk '
      BEGIN { inblk=0; buf="" }
      /^# BEGIN session-vault$/ { if (inblk) buf=buf $0 ORS; else { inblk=1; buf=$0 ORS } next }
      /^# END session-vault$/   { if (inblk) { inblk=0; buf="" } else print; next }
      { if (inblk) buf=buf $0 ORS; else print }
      END { if (inblk) printf "%s", buf }
    ' | crontab - 2>/dev/null || true
    if command -v systemctl >/dev/null 2>&1; then
      systemctl --user disable --now session-vault-heartbeat.timer 2>/dev/null || true
      rm -f "${HOME}/.config/systemd/user/session-vault-heartbeat.timer" \
            "${HOME}/.config/systemd/user/session-vault-heartbeat.service"
      systemctl --user daemon-reload 2>/dev/null || true
    fi
    log "  cron + systemd cleaned"
  fi
fi

# --- files ---
step "Files"
if [ "$DRY_RUN" = 1 ]; then
  log "  [dry-run] rm -rf ${INSTALL_DIR} and ${GCLOUD_CONFIG}"
else
  for d in "$INSTALL_DIR" "$GCLOUD_CONFIG"; do
    if safe_rm_dir "$d"; then
      rm -rf "$d"
      log "  removed $d"
    else
      log "  REFUSING to remove unsafe path: '$d' (not under \$HOME, or is \$HOME). Remove it by hand if intended."
    fi
  done
fi

# --- optional cloud purge ---
if [ "$PURGE_CLOUD" = 1 ]; then
  step "Cloud purge (SA + secret; data kept)"
  if [ "$DRY_RUN" = 1 ]; then
    log "  [dry-run] delete SA ${SA_NAME}@${PROJECT} + GSM secret ${SA_SECRET}"
  elif [ -n "$PROJECT" ]; then
    gcloud iam service-accounts delete "${SA_NAME}@${PROJECT}.iam.gserviceaccount.com" --project="$PROJECT" --quiet 2>/dev/null || true
    gcloud secrets delete "$SA_SECRET" --project="$PROJECT" --quiet 2>/dev/null || true
    log "  SA + secret deleted (dataset/tables/bucket kept)"
  fi
fi

step "Done"
log "session-vault removed. Your logged data is untouched in BigQuery."
