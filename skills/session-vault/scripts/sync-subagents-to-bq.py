#!/usr/bin/env python3
"""sync-subagents-to-bq.py - Sync local Claude Code subagent (sidechain) transcripts to BigQuery.

Companion to the main transcript syncer. That path only handles main session files
(~/.claude/projects/{cache-key}/{session-uuid}.jsonl); this script handles the
sidechain agents nested under each session UUID dir at
~/.claude/projects/{cache-key}/{session-uuid}/subagents/agent-{id}.jsonl.

Sidechain events were never captured by the real-time hooks and were skipped by
the original bulk sync - so without this script, all the research/tool fan-outs
spawned by Task() / Agent() calls are lost.

Dedup: pulls all existing sidechain UUIDs from the vault once, filters them out
of the candidate set. Inserts only new events with is_sidechain=true and
event_type='vault_backfill_subagent'.

All targets (BQ project, dataset, tables, gcloud config) come from
~/.claude/itg.config.json via _vault.py - nothing is hardcoded. Auth is via
CLOUDSDK_CONFIG (the vault's dedicated gcloud config); no service account is named
here. No-op unless the vault is enabled.

Usage:
  ./scripts/sync-subagents-to-bq.py [--dry-run]

  --dry-run (or VAULT_DRY_RUN=1) prints the resolved target and what it WOULD
  load, and makes no BigQuery writes.

Safe to re-run.
"""
from __future__ import annotations  # PEP 604 `X | None` annotations must not evaluate on py3.8/3.9

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _vault  # noqa: E402

CFG = _vault.resolve()
if not CFG["enabled"] or not CFG["bq_project"]:
    sys.exit(0)
os.environ["CLOUDSDK_CONFIG"] = CFG["gcloud_config_dir"]

DRY_RUN = "--dry-run" in sys.argv or os.environ.get("VAULT_DRY_RUN") == "1"

PROJECT_ID = CFG["bq_project"]
BQ_TABLE = CFG["messages_table"]
CLAUDE_PROJECTS = Path.home() / ".claude/projects"

# Machine identifier, matching the bash syncer's convention: config override first,
# else scutil (macOS), else the short hostname (Linux). Absolute path to scutil: it
# lives in /usr/sbin, which a scheduled job (LaunchAgent / systemd / cron) may not
# carry on PATH, so a bare name raises FileNotFoundError and falls through to the
# short hostname - a second identity for the same box in the same table.
machine = CFG["machine_name"]
if not machine:
    try:
        machine = subprocess.check_output(
            ["/usr/sbin/scutil", "--get", "LocalHostName"], text=True
        ).strip()
    except Exception:
        machine = socket.gethostname().split(".")[0]


def fetch_existing_uuids() -> set:
    """Pull all sidechain uuids already in the vault."""
    print("=== Fetching existing sidechain uuids from BQ ===")
    res = subprocess.run(
        ["bq", "query", "--nouse_legacy_sql", "--format=csv", "--max_rows=1000000",
         "--project_id=" + PROJECT_ID,
         f"SELECT uuid FROM `{PROJECT_ID}.{BQ_TABLE}` WHERE is_sidechain = true AND uuid IS NOT NULL"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        print(f"  bq query failed: {res.stderr}", file=sys.stderr)
        sys.exit(1)
    uids = {line.strip() for line in res.stdout.splitlines()[1:] if line.strip()}
    print(f"  Vault already has {len(uids):,} sidechain uuids")
    return uids


def parse_event(evt: dict, project_dir: str) -> dict | None:
    """Convert one JSONL event into a vault row, or None to skip."""
    sid = evt.get("sessionId")
    ts = evt.get("timestamp", "")
    if not sid or not ts:
        return None

    msg = evt.get("message", {}) or {}
    role = msg.get("role") or evt.get("type", "unknown")

    content_text = ""
    tool_calls: list = []
    tool_results: list = []

    mc = msg.get("content")
    if isinstance(mc, str):
        content_text = mc
    elif isinstance(mc, list):
        text_parts = []
        for blk in mc:
            if not isinstance(blk, dict):
                continue
            t = blk.get("type")
            if t == "text":
                text_parts.append(blk.get("text", ""))
            elif t == "tool_use":
                tool_calls.append(blk)
            elif t == "tool_result":
                tool_results.append(blk)
        content_text = "\n".join(text_parts)

    if not content_text and not tool_calls and not tool_results:
        return None

    usage = msg.get("usage", {}) or {}

    row = {
        "session_id": sid,
        "timestamp": ts,
        "role": role,
        "content": content_text or None,
        "tool_calls": json.dumps(tool_calls) if tool_calls else None,
        "tool_results": json.dumps(tool_results) if tool_results else None,
        "project_dir": project_dir,
        "machine": machine,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "git_branch": evt.get("gitBranch"),
        "is_sidechain": True,
        "cc_version": evt.get("version"),
        "uuid": evt.get("uuid"),
        "parent_uuid": evt.get("parentUuid"),
        "request_id": evt.get("requestId"),
        "stop_reason": msg.get("stop_reason"),
        "service_tier": usage.get("service_tier"),
        "user_type": evt.get("userType"),
        "event_type": "vault_backfill_subagent",
        "message_id": msg.get("id"),
    }
    return {k: v for k, v in row.items() if v is not None}


def main():
    print(f"Resolved target: {PROJECT_ID}:{BQ_TABLE}")
    if DRY_RUN:
        print("[dry-run] no BigQuery writes will be made")
    print()

    existing = fetch_existing_uuids()

    print()
    print("=== Scanning subagent transcripts ===")
    subagent_files = list(CLAUDE_PROJECTS.rglob("subagents/agent-*.jsonl"))
    print(f"  Found {len(subagent_files):,} subagent files")

    new_rows = []
    files_processed = 0
    skipped_no_uuid = 0
    skipped_already = 0

    for f in subagent_files:
        files_processed += 1
        project_cache_key = f.parts[-4]
        project_dir = "/" + "/".join(project_cache_key.lstrip("-").split("-"))
        try:
            with f.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    uid = evt.get("uuid")
                    if not uid:
                        skipped_no_uuid += 1
                        continue
                    if uid in existing:
                        skipped_already += 1
                        continue
                    row = parse_event(evt, project_dir)
                    if row is not None:
                        new_rows.append(row)
                        existing.add(uid)
        except Exception as e:
            print(f"  Error on {f}: {e}", file=sys.stderr)
            continue

    print(f"  Files processed: {files_processed:,}")
    print(f"  Events skipped (no uuid): {skipped_no_uuid:,}")
    print(f"  Events skipped (already in vault): {skipped_already:,}")
    print(f"  New rows: {len(new_rows):,}")

    if not new_rows:
        print()
        print("All subagent events already in BQ. Nothing to sync.")
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False) as tmp:
        for r in new_rows:
            tmp.write(json.dumps(r) + "\n")
        path = tmp.name
    size_mb = os.path.getsize(path) / 1_048_576

    print()
    print(f"=== Uploading {len(new_rows):,} rows ({size_mb:.1f} MB) to {PROJECT_ID}:{BQ_TABLE} ===")
    if DRY_RUN:
        print(f"DRY RUN - skipping upload. NDJSON: {path}")
        return 0

    res = subprocess.run(
        ["bq", "load", "--source_format=NEWLINE_DELIMITED_JSON",
         "--project_id=" + PROJECT_ID,
         "--max_bad_records=100",
         BQ_TABLE, path],
        capture_output=True, text=True,
    )
    if res.returncode == 0:
        print(f"Done. Uploaded {len(new_rows):,} subagent rows.")
        os.unlink(path)
        return 0
    print(f"bq load failed:\n{res.stderr}", file=sys.stderr)
    print(f"NDJSON preserved at: {path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
