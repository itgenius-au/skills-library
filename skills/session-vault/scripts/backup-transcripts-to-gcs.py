#!/usr/bin/env python3
"""backup-transcripts-to-gcs.py - off-machine tarball backup of Claude Code + Codex
transcripts to Google Cloud Storage.

Claude Code rolling-deletes ~/.claude/projects/*.jsonl after ~30 days. The vault hooks
insert each turn into BigQuery in real time, so the vault itself is durable, but if the
hooks ever break we would lose any session not synced before cleanup ran. This script is
the off-machine safety net: it tars the raw transcript trees and uploads one dated
archive per day.

Tars these dirs (each kept HOME-relative inside the archive so it extracts cleanly
anywhere):
  ~/.claude/projects/
  ~/.codex/sessions/
  ~/.codex/archived_sessions/

Uploads to:
  gs://<gcs_backup_bucket>/<machine>/<YYYY-MM-DD>.tgz

Auth: whatever `gcloud` resolves from CLOUDSDK_CONFIG - the isolated, least-privilege
vault service-account config that setup provisions. No domain-wide delegation, no Drive,
no service-account impersonation.

Retention: handled by a GCS object-lifecycle rule set once at setup time, so this script
NEVER prunes. It is idempotent: if today's archive already exists it skips the work (pass
--force to rebuild and overwrite).

Config: every target comes from ~/.claude/itg.config.json via _vault.py - nothing is
hardcoded. NO-OP unless logging.enabled AND logging.backup_enabled are true and a bucket
is configured.

Deps: the `gcloud` CLI (for `gcloud storage`) + Python stdlib only.

Usage:
  ./backup-transcripts-to-gcs.py [--dry-run] [--force]
  VAULT_DRY_RUN=1 ./backup-transcripts-to-gcs.py
"""
import argparse
import datetime as dt
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _vault  # noqa: E402  (path is set up on the line above)

CFG = _vault.resolve()
if not CFG["enabled"] or not CFG["bq_project"]:
    sys.exit(0)
# Authenticate as the isolated least-privilege vault SA. Setting it here means a manual
# run and a headless scheduler both hit the same config the scheduled agent uses.
os.environ["CLOUDSDK_CONFIG"] = CFG["gcloud_config_dir"]

SOURCES = [
    Path.home() / ".claude/projects",
    Path.home() / ".codex/sessions",
    Path.home() / ".codex/archived_sessions",
]


def log(msg):
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("[%s] %s" % (ts, msg), flush=True)


def machine_name():
    """Machine id: config override, else scutil (macOS), else short hostname.

    A stable per-machine name namespaces each host's archives under its own prefix so
    two machines never overwrite each other's daily backup.
    """
    configured = CFG["machine_name"]
    if configured:
        return configured
    scutil = "/usr/sbin/scutil"
    if os.path.exists(scutil):
        try:
            r = subprocess.run(
                [scutil, "--get", "LocalHostName"],
                capture_output=True, text=True,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except OSError:
            pass
    return socket.gethostname().split(".")[0]


def iter_sources():
    """Yield (src_path, arcname, exists) for each backup source.

    arcname keeps each tree HOME-relative (".claude/projects", ".codex/sessions", ...)
    so the archive has no absolute or user-specific path baked in.
    """
    for src in SOURCES:
        arcname = str(src.relative_to(src.parent.parent))  # -> ".claude/projects" etc.
        yield src, arcname, src.exists()


def build_tarball(out_path):
    """Compress the sources that exist into out_path. Returns bytes written."""
    log("Building tarball: %s" % out_path)
    with tarfile.open(out_path, "w:gz") as tar:
        for src, arcname, exists in iter_sources():
            if not exists:
                log("  skip (missing): %s" % src)
                continue
            log("  add: %s -> %s" % (src, arcname))
            tar.add(str(src), arcname=arcname)
    return out_path.stat().st_size


def gcs_exists(gs_uri):
    """True if the object already exists. Read-only `gcloud storage ls`."""
    r = subprocess.run(
        ["gcloud", "storage", "ls", gs_uri],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def upload(local_path, gs_uri):
    """Upload local_path to gs_uri via `gcloud storage cp` (auth from CLOUDSDK_CONFIG).

    Output is left inherited so gcloud's own progress and any error land in the log.
    """
    res = subprocess.run(["gcloud", "storage", "cp", str(local_path), gs_uri])
    if res.returncode != 0:
        raise RuntimeError("gcloud storage cp failed (rc=%d)" % res.returncode)


def main():
    parser = argparse.ArgumentParser(
        description="Back up Claude Code + Codex transcripts to GCS."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the tar members and gs:// target; make no bq/gcs writes.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Rebuild and overwrite even if today's archive already exists.",
    )
    args = parser.parse_args()

    dry_run = args.dry_run or os.environ.get("VAULT_DRY_RUN") == "1"

    # NO-OP unless the backup is explicitly turned on and a bucket is configured.
    if not CFG["backup_enabled"]:
        if dry_run:
            log("[dry-run] logging.backup_enabled is false - backup is a no-op")
        return 0
    bucket = CFG["gcs_backup_bucket"]
    if not bucket:
        if dry_run:
            log("[dry-run] logging.gcs_backup_bucket is unset - nothing to upload to")
        return 0

    machine = machine_name()
    today = dt.date.today().isoformat()
    archive_name = "%s.tgz" % today
    gs_uri = "gs://%s/%s/%s" % (bucket, machine, archive_name)

    log("Machine: %s" % machine)
    log("Target:  %s" % gs_uri)

    if dry_run:
        log("[dry-run] tar members:")
        for src, arcname, exists in iter_sources():
            if not exists:
                log("  skip (missing): %s" % src)
                continue
            try:
                n = sum(1 for _ in src.rglob("*"))
                log("  %s -> %s (%d entries)" % (src, arcname, n))
            except OSError:
                log("  %s -> %s" % (src, arcname))
        log("[dry-run] would upload to %s (skipped if present; --force overwrites)" % gs_uri)
        log("[dry-run] no writes performed")
        return 0

    # Idempotent skip-if-present: a run that already completed today leaves the object in
    # place, so a re-trigger does no work. --force rebuilds to capture later-in-the-day
    # sessions. Retention/expiry is a bucket lifecycle rule, never this script's job.
    if not args.force and gcs_exists(gs_uri):
        log("Already present, skipping (use --force to overwrite): %s" % gs_uri)
        return 0

    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / archive_name
        size = build_tarball(out_path)
        log("Tarball size: %.1f MB" % (size / 1_048_576))
        upload(out_path, gs_uri)
        log("Uploaded: %s" % gs_uri)
    return 0


if __name__ == "__main__":
    sys.exit(main())
