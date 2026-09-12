#!/usr/bin/env python3
"""Shared config-loader for the session-vault skill's scripts.

Every script (the bash hooks, the python syncers, the setup installer) resolves
its BigQuery / GCS / offset settings HERE, from ~/.claude/itg.config.json (with
~/.claude/allteam-config.json still read as a fallback during the rename window),
so no personal project id, dataset, service account, or path is ever hardcoded.
See docs/config-convention.md in agent-allteam.

Usage:
  Bash callers:    eval "$(python3 "$DIR/_vault.py" --shell-env)"   # exports VAULT_*; always exits 0
  Python callers:  import _vault; cfg = _vault.resolve()
  Setup / preflight: python3 _vault.py --check                      # human-readable; non-zero if misconfigured
  Machine JSON:    python3 _vault.py --json

Stdlib only (json, os, shlex, sys) so it runs on any teammate's system python3.
"""

import json
import os
import shlex
import sys

# Config-path resolution for the rename window. itg.config.json is the new name;
# allteam-config.json is still read as a fallback. An explicit env override (set
# and non-empty) always wins and is honored unconditionally (no existence check),
# in this order:
#   ITG_CONFIG -> ALLTEAM_CONFIG_PATH -> ~/.claude/itg.config.json -> ~/.claude/allteam-config.json
# ITG_CONFIG / ALLTEAM_CONFIG_PATH are used by tests and by a scratch-dataset dry-run.
def _config_path():
    for var in ("ITG_CONFIG", "ALLTEAM_CONFIG_PATH"):
        val = os.environ.get(var)
        if val:  # set and non-empty
            return os.path.expanduser(val)
    new = os.path.expanduser("~/.claude/itg.config.json")
    old = os.path.expanduser("~/.claude/allteam-config.json")
    return new if os.path.exists(new) else old

DEFAULTS = {
    "bq_dataset": "claude_memory_vault",
    "sa_secret_name": "local-session-sync-sa-key",
    "gcloud_config_dir": "~/.config/gcloud-vault",
    "offset_state_dir": "~/.claude/hooks/.offsets",
}


def load_config():
    """Read the resolved config file (empty dict if absent/invalid)."""
    try:
        with open(_config_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _expand(path):
    return os.path.expanduser(path) if path else path


def resolve(config=None):
    """Resolve the full logging config, applying defaults and fallbacks.

    bq_project falls back to gcp.personal_project. The GCS backup bucket
    defaults to '<project>-claude-vault-backup' when unset. Paths are expanded.
    """
    cfg = config if config is not None else load_config()
    logging = cfg.get("logging", {}) or {}
    gcp = cfg.get("gcp", {}) or {}
    person = cfg.get("person", {}) or {}

    project = (logging.get("bq_project") or gcp.get("personal_project") or "").strip()
    dataset = (logging.get("bq_dataset") or DEFAULTS["bq_dataset"]).strip()
    bucket = (logging.get("gcs_backup_bucket") or "").strip()
    if not bucket and project:
        bucket = "%s-claude-vault-backup" % project

    return {
        "enabled": bool(logging.get("enabled", False)),
        "heartbeat_enabled": bool(logging.get("heartbeat_enabled", False)),
        "backup_enabled": bool(logging.get("backup_enabled", False)),
        "bq_project": project,
        "bq_dataset": dataset,
        "messages_table": "%s.messages" % dataset,
        "heartbeat_table": "%s.session_heartbeat" % dataset,
        "gcloud_config_dir": _expand(logging.get("gcloud_config_dir") or DEFAULTS["gcloud_config_dir"]),
        "offset_state_dir": _expand(logging.get("offset_state_dir") or DEFAULTS["offset_state_dir"]),
        "sa_secret_name": (logging.get("sa_secret_name") or DEFAULTS["sa_secret_name"]).strip(),
        "gcs_backup_bucket": bucket,
        "machine_name": (person.get("machine_name") or "").strip(),
    }


def missing_keys(r):
    """Required config for an ENABLED vault. Empty list = OK to run."""
    missing = []
    if not r["bq_project"]:
        missing.append("logging.bq_project (or gcp.personal_project)")
    if r["backup_enabled"] and not r["gcs_backup_bucket"]:
        missing.append("logging.gcs_backup_bucket")
    return missing


def _shell_env(r):
    def q(v):
        if isinstance(v, bool):
            return "1" if v else "0"
        return shlex.quote(str(v))

    pairs = [
        ("VAULT_ENABLED", r["enabled"]),
        ("VAULT_HEARTBEAT_ENABLED", r["heartbeat_enabled"]),
        ("VAULT_BACKUP_ENABLED", r["backup_enabled"]),
        ("VAULT_BQ_PROJECT", r["bq_project"]),
        ("VAULT_BQ_DATASET", r["bq_dataset"]),
        ("VAULT_MESSAGES_TABLE", r["messages_table"]),
        ("VAULT_HEARTBEAT_TABLE", r["heartbeat_table"]),
        ("VAULT_GCLOUD_CONFIG", r["gcloud_config_dir"]),
        ("VAULT_OFFSET_DIR", r["offset_state_dir"]),
        ("VAULT_SA_SECRET", r["sa_secret_name"]),
        ("VAULT_GCS_BUCKET", r["gcs_backup_bucket"]),
        ("VAULT_MACHINE_NAME", r["machine_name"]),
    ]
    return "\n".join("export %s=%s" % (k, q(v)) for k, v in pairs)


def main(argv):
    r = resolve()
    if "--shell-env" in argv:
        # Always succeed: bash hooks stay best-effort and must never be blocked
        # by a config problem. Enforcement lives in --check (used by setup).
        print(_shell_env(r))
        return 0
    if "--json" in argv:
        print(json.dumps(r, indent=2))
        return 0
    # default and --check: human-readable resolution + validation
    for k in sorted(r):
        print("%s: %s" % (k, r[k]))
    miss = missing_keys(r)
    if not r["enabled"]:
        print("\nlogging.enabled is false - the vault is off (nothing is written).")
        return 0
    if miss:
        print("\nMISSING required config:", file=sys.stderr)
        for m in miss:
            print("  - %s" % m, file=sys.stderr)
        print("\nEdit %s (copy templates/itg.config.example.json)." % _config_path(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
