#!/usr/bin/env bash
# session-vault setup: provision your BigQuery vault + install the hooks and scheduler.
#
# Idempotent (safe to re-run). --dry-run prints the full plan and makes NO changes and needs
# no cloud credentials. The real run is confirm-gated. Everything targets YOUR OWN Google
# Cloud project, read from ~/.claude/session-vault.config.json (or $SESSION_VAULT_CONFIG)
# via _vault.py. If that file does not exist yet, this script writes it for you (interactive
# prompt for your project id; non-interactively it points you at the template and exits).
#
# What it does (real run):
#   - ensures the BigQuery dataset + messages table (+ session_heartbeat if heartbeat is on)
#   - creates a least-privilege service account, its key (stored in your GSM), and BigQuery IAM
#   - activates that SA into an isolated gcloud config so non-interactive jobs never hit the
#     Google session-control reauth wall
#   - (if backup enabled) creates a GCS bucket with a 35-day lifecycle rule + storage IAM
#   - copies the scripts to ~/.claude/session-vault, wires the two Claude Code hooks, and
#     installs the OS scheduler (launchd on macOS; cron + optional systemd timer on Linux)
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=0
ASSUME_YES=0

usage() {
  cat <<'EOF'
Usage: setup-vault.sh [--dry-run] [--yes]
  --dry-run   Print the plan and exit; make no changes; no credentials needed.
  --yes, -y   Skip the confirmation prompt (for a real, mutating run).
EOF
}

for a in "$@"; do
  case "$a" in
    --dry-run) DRY_RUN=1 ;;
    -y|--yes)  ASSUME_YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $a" >&2; usage; exit 2 ;;
  esac
done

log()  { printf '%s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }
fail_exit() { log "  FAILED: $1 - stopping (no success reported for later steps). Fix and re-run (idempotent)."; exit 1; }

# Refuse a path we would create/activate/remove if it is empty, root, or the home dir itself.
safe_dir() {
  case "${HOME:-}" in /?*) ;; *) return 1 ;; esac
  case "$1" in
    ""|"/"|"$HOME"|"$HOME/") return 1 ;;
    /*) return 0 ;;
    *) return 1 ;;
  esac
}

# HOME must be a real absolute path: all install paths and rendered unit files derive from it.
case "${HOME:-}" in /?*) ;; *) log "HOME is not a usable absolute path; refusing to run."; exit 1 ;; esac

# --- config ---------------------------------------------------------------
CONFIG_PATH="${SESSION_VAULT_CONFIG:-$HOME/.claude/session-vault.config.json}"

step "Config (${CONFIG_PATH})"
if [ ! -f "$CONFIG_PATH" ]; then
  if [ "$DRY_RUN" = 1 ]; then
    log "  no config file found at ${CONFIG_PATH}"
    log "  [dry-run] would prompt for bq_project and write a flat config there"
  elif [ -t 0 ]; then
    log "  no config file found at ${CONFIG_PATH}"
    printf '  Google Cloud project for your BigQuery vault (bq_project): '
    read -r NEW_BQ_PROJECT
    if [ -z "$NEW_BQ_PROJECT" ]; then
      log "  no project entered; aborting."
      exit 1
    fi
    mkdir -p "$(dirname "$CONFIG_PATH")" || fail_exit "create $(dirname "$CONFIG_PATH")"
    cat > "$CONFIG_PATH" <<CFGEOF
{
  "enabled": true,
  "bq_project": "${NEW_BQ_PROJECT}",
  "bq_dataset": "claude_memory_vault",
  "heartbeat_enabled": false,
  "backup_enabled": false,
  "gcs_backup_bucket": "",
  "sa_secret_name": "local-session-sync-sa-key",
  "gcloud_config_dir": "~/.config/gcloud-vault",
  "offset_state_dir": "~/.claude/hooks/.offsets",
  "machine_name": ""
}
CFGEOF
    chmod 600 "$CONFIG_PATH" 2>/dev/null || true
    log "  wrote ${CONFIG_PATH}"
  else
    log "  no config file found at ${CONFIG_PATH} and no terminal to prompt on."
    log "  Copy templates/session-vault.config.example.json to ${CONFIG_PATH}, set bq_project, and re-run."
    exit 0
  fi
fi

VAULT_ENV="$(python3 "$DIR/_vault.py" --shell-env 2>/dev/null || true)"
eval "$VAULT_ENV"

if ! python3 "$DIR/_vault.py" --check; then
  log ""
  log "Fix the missing keys above, then re-run."
  exit 1
fi
if [ "${VAULT_ENABLED:-0}" != "1" ]; then
  log ""
  log "enabled is false. Set it to true in ${CONFIG_PATH}, then re-run."
  exit 1
fi
if [ -z "${VAULT_BQ_PROJECT:-}" ]; then
  log "No BigQuery project resolved (set bq_project in ${CONFIG_PATH})."
  exit 1
fi

# --- preflight tools ------------------------------------------------------
for t in gcloud bq jq python3; do
  if ! command -v "$t" >/dev/null 2>&1; then
    log "Missing required tool: $t (install the Google Cloud SDK + jq)."
    exit 1
  fi
done

# --- derived values -------------------------------------------------------
PROJECT="$VAULT_BQ_PROJECT"
DATASET="$VAULT_BQ_DATASET"
SA_NAME="local-session-sync"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
GCLOUD_CONFIG="$VAULT_GCLOUD_CONFIG"
SA_SECRET="$VAULT_SA_SECRET"
BUCKET="$VAULT_GCS_BUCKET"
INSTALL_DIR="$HOME/.claude/session-vault"
SETTINGS="$HOME/.claude/settings.json"
LABEL_PREFIX="com.itgenius.session-vault"
OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
  LOG_DIR="$HOME/Library/Logs"
  PATH_VALUE="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:$HOME/.local/bin"
else
  LOG_DIR="$HOME/.local/state/session-vault"
  PATH_VALUE="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin"
fi

if ! safe_dir "$GCLOUD_CONFIG"; then
  log "Refusing unsafe gcloud_config_dir: '$GCLOUD_CONFIG' (must be an absolute path, not / or \$HOME)."
  exit 1
fi
# This value is substituted into cron/launchd/systemd unit files. Restrict it to safe path
# characters so it can never inject shell metacharacters, whitespace, or newlines into them.
case "$GCLOUD_CONFIG" in
  *[!A-Za-z0-9_./-]*)
    log "Refusing gcloud_config_dir with unsafe characters: '$GCLOUD_CONFIG' (allowed: A-Z a-z 0-9 _ . / -)."
    exit 1 ;;
esac

# --- plan -----------------------------------------------------------------
step "Plan"
log "  OS               : $OS"
log "  BigQuery project : $PROJECT"
log "  Dataset          : $DATASET  (tables: messages$([ "${VAULT_HEARTBEAT_ENABLED:-0}" = 1 ] && printf ', session_heartbeat'))"
log "  Service account  : $SA_EMAIL  (roles: bigquery.jobUser, bigquery.dataEditor)"
log "  SA key secret    : $SA_SECRET  (in your GSM project $PROJECT)"
log "  Isolated config  : $GCLOUD_CONFIG"
log "  Install dir      : $INSTALL_DIR"
log "  Hooks            : UserPromptSubmit + Stop -> $SETTINGS"
log "  Heartbeat        : $([ "${VAULT_HEARTBEAT_ENABLED:-0}" = 1 ] && echo ON || echo off)"
log "  GCS backup       : $([ "${VAULT_BACKUP_ENABLED:-0}" = 1 ] && echo "ON -> gs://$BUCKET (35d lifecycle)" || echo off)"
log "  Scheduler        : $([ "$OS" = Darwin ] && echo launchd || echo 'cron + systemd (heartbeat)')"

if [ "$DRY_RUN" = 1 ]; then
  log ""
  log "(dry-run) The steps below would run. No changes were made."
fi

if [ "$DRY_RUN" = 0 ] && [ "$ASSUME_YES" = 0 ]; then
  printf '\nProceed? This creates cloud resources in %s. [y/N] ' "$PROJECT"
  read -r ans
  case "$ans" in
    y|Y|yes|YES) ;;
    *) log "Aborted."; exit 1 ;;
  esac
fi

# --- helpers --------------------------------------------------------------
render_template() {
  # render_template SRC DST  - fill the __TOKENS__ from the derived values
  sed -e "s#__INSTALL_DIR__#${INSTALL_DIR}#g" \
      -e "s#__HOME__#${HOME}#g" \
      -e "s#__PATH__#${PATH_VALUE}#g" \
      -e "s#__GCLOUD_CONFIG__#${GCLOUD_CONFIG}#g" \
      -e "s#__LABEL_PREFIX__#${LABEL_PREFIX}#g" \
      -e "s#__LOG_DIR__#${LOG_DIR}#g" \
      "$1" > "$2"
}

# --- provisioning steps (each is a no-op print under --dry-run) ------------
ensure_dataset() {
  step "BigQuery dataset"
  if [ "$DRY_RUN" = 1 ]; then log "  [dry-run] ensure dataset ${PROJECT}:${DATASET}"; return; fi
  if bq --project_id="$PROJECT" show --dataset "${PROJECT}:${DATASET}" >/dev/null 2>&1; then
    log "  dataset ${DATASET} exists"
  else
    bq --project_id="$PROJECT" mk --dataset "${PROJECT}:${DATASET}" || fail_exit "create dataset"
    log "  created dataset ${DATASET}"
  fi
}

ensure_table() {
  local tbl="$1" schema="$2"
  if [ "$DRY_RUN" = 1 ]; then log "  [dry-run] ensure table ${DATASET}.${tbl} (schema $schema)"; return; fi
  if bq --project_id="$PROJECT" show "${PROJECT}:${DATASET}.${tbl}" >/dev/null 2>&1; then
    log "  table ${tbl} exists"
  else
    bq --project_id="$PROJECT" mk --table "${PROJECT}:${DATASET}.${tbl}" "$DIR/schema/${schema}" \
      || fail_exit "create table ${tbl}"
    log "  created table ${tbl}"
  fi
}

ensure_sa() {
  step "Service account"
  if [ "$DRY_RUN" = 1 ]; then log "  [dry-run] ensure SA ${SA_EMAIL}"; return; fi
  if gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT" >/dev/null 2>&1; then
    log "  SA exists"
  else
    gcloud iam service-accounts create "$SA_NAME" --project="$PROJECT" \
      --display-name="session-vault local session sync (least-priv)" \
      || fail_exit "create service account"
    log "  created SA ${SA_EMAIL}"
  fi
}

grant_bq_iam() {
  step "BigQuery IAM"
  if [ "$DRY_RUN" = 1 ]; then log "  [dry-run] grant bigquery.jobUser (project) + bigquery.dataEditor (dataset ${DATASET})"; return; fi
  # jobUser must be project-level (to run load/query jobs). dataEditor is scoped to the vault
  # DATASET only (via the dataset ACL), so the laptop-resident SA key cannot read or modify any
  # other dataset in the project.
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${SA_EMAIL}" --role="roles/bigquery.jobUser" --condition=None >/dev/null \
    || fail_exit "grant bigquery.jobUser"
  local acl updated
  acl="$(mktemp)"; updated="$(mktemp)"
  bq --project_id="$PROJECT" show --format=prettyjson "${PROJECT}:${DATASET}" > "$acl" \
    || { rm -f "$acl" "$updated"; fail_exit "read dataset ACL"; }
  python3 "$DIR/lib/dataset-acl.py" "$SA_EMAIL" < "$acl" > "$updated" \
    || { rm -f "$acl" "$updated"; fail_exit "compute dataset ACL"; }
  bq update --source "$updated" "${PROJECT}:${DATASET}" >/dev/null \
    || { rm -f "$acl" "$updated"; fail_exit "apply dataset ACL"; }
  rm -f "$acl" "$updated"
  log "  granted bigquery.jobUser (project) + bigquery.dataEditor (dataset ${DATASET})"
}

ensure_key_and_activate() {
  step "SA key + isolated gcloud config"
  if [ "$DRY_RUN" = 1 ]; then
    log "  [dry-run] ensure GSM secret ${SA_SECRET} holds an SA key; activate SA into ${GCLOUD_CONFIG}"
    return
  fi
  mkdir -p "$GCLOUD_CONFIG" || fail_exit "create ${GCLOUD_CONFIG}"
  local keyfile="${GCLOUD_CONFIG}/${SA_NAME}.json"
  if gcloud secrets describe "$SA_SECRET" --project="$PROJECT" >/dev/null 2>&1; then
    log "  GSM secret ${SA_SECRET} exists; pulling key"
    ( umask 177; gcloud secrets versions access latest --secret="$SA_SECRET" --project="$PROJECT" > "$keyfile" ) \
      || fail_exit "pull SA key from GSM"
  else
    log "  creating SA key + GSM secret ${SA_SECRET}"
    local tmpkey
    tmpkey="$(mktemp)"
    ( umask 177; gcloud iam service-accounts keys create "$tmpkey" --iam-account="$SA_EMAIL" --project="$PROJECT" ) \
      || { rm -f "$tmpkey"; fail_exit "create SA key"; }
    gcloud secrets create "$SA_SECRET" --project="$PROJECT" --replication-policy="automatic" --data-file="$tmpkey" >/dev/null \
      || { rm -f "$tmpkey"; fail_exit "create GSM secret ${SA_SECRET}"; }
    ( umask 177; cp "$tmpkey" "$keyfile" ) || { rm -f "$tmpkey"; fail_exit "write keyfile"; }
    rm -f "$tmpkey"
  fi
  chmod 600 "$keyfile" || fail_exit "chmod keyfile"
  # If activation fails the stored key may be stale (rotated/deleted in IAM): deleting the GSM
  # secret and re-running takes the create-key branch and re-mints.
  CLOUDSDK_CONFIG="$GCLOUD_CONFIG" gcloud auth activate-service-account --key-file="$keyfile" >/dev/null \
    || fail_exit "activate SA (if the key is stale, delete GSM secret ${SA_SECRET} and re-run)"
  CLOUDSDK_CONFIG="$GCLOUD_CONFIG" gcloud config set project "$PROJECT" >/dev/null 2>&1 \
    || log "  (note: could not set default project in the isolated config; scripts pass --project_id anyway)"
  CLOUDSDK_CONFIG="$GCLOUD_CONFIG" gcloud config set disable_usage_reporting True >/dev/null 2>&1 || true
  log "  SA activated in ${GCLOUD_CONFIG}"
}

ensure_bucket() {
  [ "${VAULT_BACKUP_ENABLED:-0}" = "1" ] || return 0
  step "GCS backup bucket"
  if [ "$DRY_RUN" = 1 ]; then log "  [dry-run] ensure gs://${BUCKET} + 35d lifecycle + storage.objectAdmin to ${SA_EMAIL}"; return; fi
  if gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
    log "  bucket exists"
  else
    gcloud storage buckets create "gs://${BUCKET}" --project="$PROJECT" --uniform-bucket-level-access \
      || fail_exit "create bucket gs://${BUCKET}"
    log "  created gs://${BUCKET}"
  fi
  local lc
  lc="$(mktemp)"
  printf '%s\n' '{"rule":[{"action":{"type":"Delete"},"condition":{"age":35}}]}' > "$lc"
  gcloud storage buckets update "gs://${BUCKET}" --lifecycle-file="$lc" >/dev/null \
    || { rm -f "$lc"; fail_exit "set bucket lifecycle"; }
  rm -f "$lc"
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
    --member="serviceAccount:${SA_EMAIL}" --role="roles/storage.objectAdmin" >/dev/null \
    || fail_exit "grant storage.objectAdmin on gs://${BUCKET}"
  log "  lifecycle (35d) + storage.objectAdmin set"
}

install_scripts() {
  step "Install scripts -> ${INSTALL_DIR}"
  if [ "$DRY_RUN" = 1 ]; then log "  [dry-run] copy scripts + lib to ${INSTALL_DIR}, chmod +x"; return; fi
  mkdir -p "${INSTALL_DIR}/lib" "${INSTALL_DIR}/schema" || fail_exit "create ${INSTALL_DIR}"
  cp "$DIR"/_vault.py \
     "$DIR"/bq-log-prompt.sh "$DIR"/bq-log-response.sh "$DIR"/session-heartbeat.sh \
     "$DIR"/sync-transcripts-to-bq.sh "$DIR"/vault-flush-offsets.py \
     "$DIR"/sync-subagents-to-bq.py "$DIR"/sync-codex-transcripts-to-bq.py \
     "$DIR"/backup-transcripts-to-gcs.py \
     "$DIR"/setup-vault.sh "$DIR"/uninstall-vault.sh "${INSTALL_DIR}/" \
     || fail_exit "copy scripts"
  cp "$DIR"/lib/bq-timeout.sh "$DIR"/lib/merge-hooks.py "$DIR"/lib/dataset-acl.py "${INSTALL_DIR}/lib/" \
     || fail_exit "copy lib"
  cp "$DIR"/schema/*.json "${INSTALL_DIR}/schema/" || fail_exit "copy schema"
  chmod +x "${INSTALL_DIR}"/*.sh "${INSTALL_DIR}"/*.py 2>/dev/null || fail_exit "make installed scripts executable"
  log "  installed"
}

install_hooks() {
  step "Claude Code hooks -> ${SETTINGS}"
  local ph="${INSTALL_DIR}/bq-log-prompt.sh" rh="${INSTALL_DIR}/bq-log-response.sh"
  if [ "$DRY_RUN" = 1 ]; then
    python3 "$DIR/lib/merge-hooks.py" --settings "$SETTINGS" --prompt-hook "$ph" --response-hook "$rh" --dry-run
    return
  fi
  python3 "${INSTALL_DIR}/lib/merge-hooks.py" --settings "$SETTINGS" --prompt-hook "$ph" --response-hook "$rh" \
    || fail_exit "wire Claude Code hooks into ${SETTINGS}"
}

install_one_launchd() {
  local name="$1"
  local label="${LABEL_PREFIX}.${name}"
  local tmpl="${DIR}/schedulers/launchd/${label}.plist.template"
  local dst="${HOME}/Library/LaunchAgents/${label}.plist"
  if [ "$DRY_RUN" = 1 ]; then log "  [dry-run] install launchd ${label}"; return; fi
  render_template "$tmpl" "$dst" || fail_exit "render launchd ${label}"
  launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$dst" 2>/dev/null || launchctl load "$dst" 2>/dev/null \
    || log "  (note: launchctl could not load ${label}; run 'launchctl bootstrap gui/$(id -u) ${dst}' or re-login)"
  log "  launchd ${label} installed"
}

install_schedulers_mac() {
  step "Scheduler (launchd)"
  [ "$DRY_RUN" = 1 ] || mkdir -p "${HOME}/Library/LaunchAgents" "$LOG_DIR" 2>/dev/null || true
  install_one_launchd bq-sync
  install_one_launchd vault-flush
  [ "${VAULT_BACKUP_ENABLED:-0}" = "1" ] && install_one_launchd backup
  [ "${VAULT_HEARTBEAT_ENABLED:-0}" = "1" ] && install_one_launchd heartbeat
  return 0
}

install_schedulers_linux() {
  step "Scheduler (cron + systemd)"
  if [ "$DRY_RUN" = 1 ]; then
    log "  [dry-run] merge cron jobs (flush, bq-sync$([ "${VAULT_BACKUP_ENABLED:-0}" = 1 ] && printf ', backup'))"
    [ "${VAULT_HEARTBEAT_ENABLED:-0}" = 1 ] && log "  [dry-run] install systemd --user heartbeat timer"
    return 0
  fi
  mkdir -p "$LOG_DIR"
  local rendered existing
  rendered="$(mktemp)"
  render_template "${DIR}/schedulers/cron/crontab.template" "$rendered" \
    || { rm -f "$rendered"; fail_exit "render cron template"; }
  if [ "${VAULT_BACKUP_ENABLED:-0}" != "1" ]; then
    grep -v 'backup-transcripts-to-gcs.py' "$rendered" > "${rendered}.f" && mv "${rendered}.f" "$rendered"
  fi
  existing="$(crontab -l 2>/dev/null || true)"
  # Remove our block, then append a fresh one. The awk drops only a well-formed BEGIN..END pair;
  # an orphan END or an unterminated/mis-ordered BEGIN is preserved (flushed at EOF), so no
  # unrelated cron line is ever lost even if a prior run left malformed markers.
  {
    printf '%s\n' "$existing" | awk '
      BEGIN { inblk=0; buf="" }
      /^# BEGIN session-vault$/ { if (inblk) buf=buf $0 ORS; else { inblk=1; buf=$0 ORS } next }
      /^# END session-vault$/   { if (inblk) { inblk=0; buf="" } else print; next }
      { if (inblk) buf=buf $0 ORS; else print }
      END { if (inblk) printf "%s", buf }
    '
    echo "# BEGIN session-vault"
    grep -vE '^#|^[[:space:]]*$' "$rendered"
    echo "# END session-vault"
  } | crontab - || { rm -f "$rendered"; fail_exit "install cron block"; }
  rm -f "$rendered"
  log "  cron jobs installed"
  if [ "${VAULT_HEARTBEAT_ENABLED:-0}" = "1" ]; then
    if command -v systemctl >/dev/null 2>&1; then
      local ud="${HOME}/.config/systemd/user"
      mkdir -p "$ud"
      render_template "${DIR}/schedulers/systemd/session-vault-heartbeat.service.template" "${ud}/session-vault-heartbeat.service" \
        || fail_exit "render heartbeat.service"
      render_template "${DIR}/schedulers/systemd/session-vault-heartbeat.timer.template" "${ud}/session-vault-heartbeat.timer" \
        || fail_exit "render heartbeat.timer"
      # Linger keeps the --user manager (and the 15s timer) running after logout, e.g. on a
      # headless/SSH Linux box. Best-effort: it needs privilege and is a no-op where already on.
      loginctl enable-linger "$USER" >/dev/null 2>&1 || log "  (note: could not enable linger; timer pauses when you log out)"
      systemctl --user daemon-reload || fail_exit "systemd daemon-reload"
      systemctl --user enable --now session-vault-heartbeat.timer \
        || fail_exit "enable systemd heartbeat timer"
      log "  systemd heartbeat timer enabled"
    else
      log "  systemd not present; heartbeat unavailable on this host (the rest works)."
    fi
  fi
  return 0
}

verify() {
  step "Verify"
  if [ "$DRY_RUN" = 1 ]; then log "  [dry-run] would run a probe query as the vault SA"; return; fi
  if CLOUDSDK_CONFIG="$GCLOUD_CONFIG" bq --project_id="$PROJECT" query --nouse_legacy_sql --format=csv \
       "SELECT COUNT(*) FROM \`${PROJECT}.${DATASET}.messages\`" >/dev/null 2>&1; then
    log "  BigQuery reachable as the vault SA."
  else
    log "  Probe query FAILED. IAM can take ~1 min to propagate - wait and re-run setup-vault.sh (idempotent)."
    exit 1
  fi
}

# --- run ------------------------------------------------------------------
ensure_dataset
step "BigQuery tables"
ensure_table messages messages.schema.json
[ "${VAULT_HEARTBEAT_ENABLED:-0}" = "1" ] && ensure_table session_heartbeat session_heartbeat.schema.json
ensure_sa
grant_bq_iam
ensure_key_and_activate
ensure_bucket
install_scripts
install_hooks
if [ "$OS" = "Darwin" ]; then
  install_schedulers_mac
else
  install_schedulers_linux
fi
verify

step "Done"
if [ "$DRY_RUN" = 1 ]; then
  log "Dry-run complete. No changes were made. Re-run without --dry-run to apply."
else
  log "session-vault installed. New Claude Code sessions now log to ${PROJECT}.${DATASET}.messages."
  log "Uninstall any time with: ${INSTALL_DIR}/uninstall-vault.sh"
fi
