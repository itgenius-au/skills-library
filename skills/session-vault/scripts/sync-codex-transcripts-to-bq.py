#!/usr/bin/env python3
"""sync-codex-transcripts-to-bq.py - Sync local Codex transcripts to BigQuery.

Companion to the Claude Code transcript loggers (bq-log-*.sh). Claude Code stores
its transcripts under ~/.claude/projects and is covered by the Stop/prompt hooks.
Codex stores session JSONL files under:

  ~/.codex/sessions/
  ~/.codex/archived_sessions/

This script converts Codex's JSONL shape into rows for the configured vault
messages table (client=codex) so Codex conversations are searchable through the
same vault as everything else.

All targets (BigQuery project, dataset, messages table, gcloud config dir,
machine name) are resolved from ~/.claude/session-vault.config.json via _vault.py -
nothing is hardcoded. No-op unless the vault is enabled and a project is set.

Usage:
  ./scripts/sync-codex-transcripts-to-bq.py [--dry-run]

  --dry-run (or VAULT_DRY_RUN=1) prints the resolved target and what it would
  load, and makes NO BigQuery writes.

Safe to re-run. Deduplication is session-level: if a Codex session_id already
exists in the vault, the file is skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Config resolution: everything comes from ~/.claude/session-vault.config.json via the
# shared _vault.py loader. No personal project id, dataset, or path is hardcoded.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _vault  # noqa: E402

CFG = _vault.resolve()
if not CFG["enabled"] or not CFG["bq_project"]:
    sys.exit(0)
os.environ["CLOUDSDK_CONFIG"] = CFG["gcloud_config_dir"]

BQ_PROJECT = CFG["bq_project"]
# messages_table is "<dataset>.messages" - the bq CLI takes it with --project_id.
MESSAGES_TABLE = CFG["messages_table"]

CODEX_DIRS = [
    Path.home() / ".codex/sessions",
    Path.home() / ".codex/archived_sessions",
]

UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


def machine_name() -> str:
    # Absolute path: scutil is in /usr/sbin, which a minimal scheduler PATH
    # (launchd/systemd/cron) may omit, so a bare name raised FileNotFoundError and
    # silently produced a second identity for the same machine.
    try:
        return subprocess.check_output(
            ["/usr/sbin/scutil", "--get", "LocalHostName"], text=True
        ).strip()
    except Exception:
        return socket.gethostname().split(".")[0]


# Machine identifier: config override, else scutil (macOS) / hostname (Linux) at runtime.
MACHINE = CFG["machine_name"] or machine_name()


def fetch_existing_sessions() -> set[str]:
    print("=== Fetching existing vault sessions ===")
    res = subprocess.run(
        [
            "bq",
            "query",
            "--nouse_legacy_sql",
            "--format=csv",
            "--max_rows=1000000",
            "--project_id=" + BQ_PROJECT,
            f"SELECT DISTINCT session_id FROM `{BQ_PROJECT}.{MESSAGES_TABLE}`",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        print(f"  bq query failed: {res.stderr}", file=sys.stderr)
        sys.exit(1)
    sessions = {line.strip() for line in res.stdout.splitlines()[1:] if line.strip()}
    print(f"  Vault already has {len(sessions):,} sessions")
    return sessions


def session_id_from_path(path: Path) -> str | None:
    match = UUID_RE.search(path.stem)
    return match.group(1) if match else None


def iter_codex_files() -> list[Path]:
    files: list[Path] = []
    for root in CODEX_DIRS:
        if not root.exists():
            continue
        files.extend(p for p in root.rglob("*.jsonl") if p.name != "session_index.jsonl")
    return sorted(files)


def text_from_content_blocks(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""

    parts: list[str] = []
    for block in value:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type in {"input_text", "output_text", "text"}:
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        elif block_type == "summary":
            summary = block.get("summary")
            if isinstance(summary, str) and summary:
                parts.append(summary)
    return "\n".join(parts)


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_codex_file(path: Path) -> tuple[str | None, list[dict[str, Any]]]:
    session_id = session_id_from_path(path)
    project_dir = ""
    model = ""
    entrypoint = "codex"
    rows: list[dict[str, Any]] = []

    with path.open() as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue

            payload = evt.get("payload") or {}
            if not isinstance(payload, dict):
                continue

            evt_type = evt.get("type")
            payload_type = payload.get("type")
            ts = evt.get("timestamp")
            row_id = f"codex:{session_id or path.stem}:{line_no}"

            if evt_type == "session_meta":
                session_id = payload.get("id") or session_id
                project_dir = payload.get("cwd") or project_dir
                originator = payload.get("originator") or "Codex"
                source = payload.get("source") or ""
                entrypoint = f"{originator}/{source}" if source else originator
                continue

            if evt_type == "turn_context":
                project_dir = payload.get("cwd") or project_dir
                model = payload.get("model") or model
                continue

            if not session_id or not ts:
                continue

            base: dict[str, Any] = {
                "session_id": session_id,
                "timestamp": ts,
                "project_dir": project_dir or None,
                "machine": MACHINE,
                "client": "codex",
                "entrypoint": entrypoint,
                "model": model or None,
                "uuid": row_id,
                "event_type": payload_type or evt_type,
            }

            row: dict[str, Any] | None = None

            if evt_type == "response_item" and payload_type == "message":
                role = payload.get("role")
                if role == "developer":
                    continue
                content = text_from_content_blocks(payload.get("content"))
                if content:
                    row = {**base, "role": role or "unknown", "content": content}

            elif evt_type == "response_item" and payload_type in {
                "function_call",
                "custom_tool_call",
            }:
                row = {
                    **base,
                    "role": "assistant",
                    "content": None,
                    "tool_calls": compact_json(payload),
                }

            elif evt_type == "response_item" and payload_type in {
                "function_call_output",
                "custom_tool_call_output",
            }:
                row = {
                    **base,
                    "role": "tool",
                    "content": None,
                    "tool_results": compact_json(payload),
                }

            elif evt_type == "event_msg" and payload_type == "token_count":
                usage = (payload.get("info") or {}).get("last_token_usage") or {}
                if isinstance(usage, dict):
                    row = {
                        **base,
                        "role": "system",
                        "content": None,
                        "input_tokens": usage.get("input_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                        "cache_read_input_tokens": usage.get("cached_input_tokens"),
                    }

            if row is not None:
                rows.append({k: v for k, v in row.items() if v is not None})

    return session_id, rows


def write_ndjson(rows: list[dict[str, Any]]) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False) as tmp:
        for row in rows:
            tmp.write(json.dumps(row, ensure_ascii=False) + "\n")
        return tmp.name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry_run = args.dry_run or os.environ.get("VAULT_DRY_RUN") == "1"

    target = f"{BQ_PROJECT}:{MESSAGES_TABLE}"
    print("=== session-vault Codex syncer ===")
    print(f"  Target: {target}")
    if dry_run:
        print("  Mode: DRY RUN (no BigQuery writes)")
    print()

    existing = fetch_existing_sessions()
    seen_local: set[str] = set()
    files = iter_codex_files()

    print()
    print("=== Scanning Codex transcripts ===")
    print(f"  Found {len(files):,} Codex JSONL files")

    new_rows: list[dict[str, Any]] = []
    files_processed = 0
    skipped_existing = 0
    skipped_duplicate = 0
    skipped_no_session = 0
    skipped_no_rows = 0

    for path in files:
        sid_hint = session_id_from_path(path)
        if sid_hint and sid_hint in existing:
            skipped_existing += 1
            continue
        if sid_hint and sid_hint in seen_local:
            skipped_duplicate += 1
            continue

        sid, rows = parse_codex_file(path)
        if not sid:
            skipped_no_session += 1
            continue
        if sid in existing:
            skipped_existing += 1
            continue
        if sid in seen_local:
            skipped_duplicate += 1
            continue
        if not rows:
            skipped_no_rows += 1
            continue

        files_processed += 1
        new_rows.extend(rows)
        seen_local.add(sid)

    print(f"  Files processed: {files_processed:,}")
    print(f"  Files skipped (already in vault): {skipped_existing:,}")
    print(f"  Files skipped (duplicate local copy): {skipped_duplicate:,}")
    print(f"  Files skipped (no session id): {skipped_no_session:,}")
    print(f"  Files skipped (no uploadable rows): {skipped_no_rows:,}")
    print(f"  New rows: {len(new_rows):,}")

    if not new_rows:
        print()
        print("All Codex sessions already in BQ. Nothing to sync.")
        return 0

    ndjson = write_ndjson(new_rows)
    size_mb = os.path.getsize(ndjson) / 1_048_576

    print()
    print(f"=== Uploading {len(new_rows):,} rows ({size_mb:.1f} MB) ===")
    print(f"  Into: {target} (--max_bad_records=100)")
    if dry_run:
        print(f"DRY RUN - skipping upload. NDJSON: {ndjson}")
        return 0

    res = subprocess.run(
        [
            "bq",
            "load",
            "--source_format=NEWLINE_DELIMITED_JSON",
            "--project_id=" + BQ_PROJECT,
            "--max_bad_records=100",
            MESSAGES_TABLE,
            ndjson,
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        print(f"Done. Uploaded {len(new_rows):,} Codex rows.")
        os.unlink(ndjson)
        return 0

    print(f"bq load failed:\n{res.stderr}", file=sys.stderr)
    print(f"NDJSON preserved at: {ndjson}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
