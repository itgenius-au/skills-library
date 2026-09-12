#!/usr/bin/env python3
"""Flush idle Claude Code sessions' unflushed transcript tails to the BigQuery vault.

The Stop hook (bq-log-response.sh) tracks the last vault-logged transcript line per
session in an offset file (one file per session id, under the configured offset-state
dir) and advances it only after a successful insert. A failed insert or a missed Stop
event leaves a silent vault gap that never self-heals once the session is closed. The
daily bulk sync skips sessions already present in BigQuery, so it cannot close a
partial tail either. This sweep closes exactly that hole: for every offset whose
transcript has more lines than the offset and has been idle longer than
--min-idle-hours, it re-runs the Stop hook with the same JSON stdin contract Claude
Code uses. The offset file makes the operation idempotent - success is judged by the
offset advancing, not by the hook's exit code.

Fidelity of swept rows vs live-logged rows (accepted trade-offs):
- cwd/entrypoint are recovered from the transcript's own records, so project_dir and
  client match what the live Stop hook would have written for nearly all rows.
- CLAUDE_EFFORT is not recorded in transcripts, so swept rows carry effort=NULL.
- A session resumed mid-sweep is skipped (transcript-mtime recheck); the worst-case
  race that remains is duplicate vault rows, never loss.

All targets are resolved from ~/.claude/session-vault.config.json via _vault.py; nothing is
hardcoded, and the script is a no-op unless the vault is enabled. The Stop hook it
re-runs is its sibling in this scripts/ directory.

Schedule this daily, ideally just before the bulk sync (scripts/schedulers/ has
templates). Run manually with --dry-run (or VAULT_DRY_RUN=1) to inspect first.
"""

import os
import sys

# Resolve all BigQuery / GCS / offset settings from ~/.claude/session-vault.config.json.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _vault  # noqa: E402  (must follow the sys.path insert above)

CFG = _vault.resolve()
if not CFG["enabled"] or not CFG["bq_project"]:
    sys.exit(0)
os.environ["CLOUDSDK_CONFIG"] = CFG["gcloud_config_dir"]

import argparse  # noqa: E402
import json  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import NamedTuple, Optional, Tuple  # noqa: E402

HOOK_TIMEOUT_SECONDS = 120
META_SCAN_MAX_LINES = 500


class Lag(NamedTuple):
    sid: str
    offset: int
    lines: int
    idle_h: float
    transcript: Path
    mtime: float


def index_transcripts(projects_dir: Path) -> "dict[str, Path]":
    """Map session id -> its real transcript. Skips symlinks (bridged sessions) and
    archive folders (_-prefixed); prefers the newest copy when an id is duplicated."""
    index: "dict[str, Path]" = {}
    if not projects_dir.is_dir():
        return index
    for folder in projects_dir.iterdir():
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        for f in folder.glob("*.jsonl"):
            if f.is_symlink():
                continue
            try:
                current = index.get(f.stem)
                if current is None or f.stat().st_mtime > current.stat().st_mtime:
                    index[f.stem] = f
            except OSError:
                continue  # vanished mid-scan
    return index


def read_offset(offset_file: Path) -> Optional[int]:
    try:
        return int(offset_file.read_text().strip() or 0)
    except (ValueError, OSError):
        return None


def count_lines(path: Path) -> int:
    """Count newline-terminated lines, matching the hook's `wc -l` exactly (an
    unterminated final line must not count, or the sweep re-fails it daily)."""
    total = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            total += chunk.count(b"\n")
    return total


def find_lagging(offsets_dir: Path, transcripts: "dict[str, Path]",
                 now: float, min_idle_hours: float) -> "list[Lag]":
    lags = []
    for offset_file in sorted(offsets_dir.iterdir()):
        offset = read_offset(offset_file)
        if offset is None:
            continue
        transcript = transcripts.get(offset_file.name)
        if transcript is None:
            continue  # pre-retention-change orphan; nothing to flush
        try:
            mtime = transcript.stat().st_mtime
            idle_h = (now - mtime) / 3600
            if idle_h <= min_idle_hours:
                continue  # likely live; its own next Stop will flush
            lines = count_lines(transcript)
        except OSError:
            continue  # purged/rewritten mid-scan; next run will see it
        if lines <= offset:
            continue
        lags.append(Lag(offset_file.name, offset, lines, idle_h, transcript, mtime))
    return lags


def extract_session_meta(transcript: Path) -> "Tuple[Optional[str], Optional[str]]":
    """First recorded cwd + entrypoint from the transcript, so swept rows carry the
    session's real project_dir fallback and client instead of scheduler defaults."""
    cwd = entrypoint = None
    try:
        with open(transcript, errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= META_SCAN_MAX_LINES or (cwd and entrypoint):
                    break
                if '"cwd"' not in line and '"entrypoint"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = cwd or rec.get("cwd")
                entrypoint = entrypoint or rec.get("entrypoint")
    except OSError:
        pass
    return cwd, entrypoint


def flush_session(hook: Path, offsets_dir: Path, lag: Lag) -> str:
    """Re-run the Stop hook for one session. Success = hook exit 0 AND the offset
    reached the line count we saw (a failed bq insert exits 0 but leaves the offset,
    so the offset is the only trustworthy signal)."""
    try:
        if lag.transcript.stat().st_mtime != lag.mtime:
            return "skipped: transcript changed since scan"
    except OSError:
        return "skipped: transcript vanished since scan"

    cwd, entrypoint = extract_session_meta(lag.transcript)
    env = dict(os.environ)
    if entrypoint:
        env["CLAUDE_CODE_ENTRYPOINT"] = entrypoint
    stdin = json.dumps({
        "session_id": lag.sid,
        "transcript_path": str(lag.transcript),
        "cwd": cwd or str(lag.transcript.parent),
    })
    # start_new_session so a timeout can kill the hook's whole process group; a bare
    # kill of the bash parent would orphan the bq/gcloud grandchild mid-insert.
    try:
        proc = subprocess.Popen([str(hook)], stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                text=True, env=env, start_new_session=True)
        try:
            proc.communicate(input=stdin, timeout=HOOK_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()
            return "failed: TimeoutExpired"
    except OSError as e:
        return f"failed: {type(e).__name__}"
    new_offset = read_offset(offsets_dir / lag.sid)
    if proc.returncode == 0 and new_offset is not None and new_offset >= lag.lines:
        return "flushed"
    return f"failed: rc={proc.returncode} offset={new_offset}"


def main(argv: "Optional[list[str]]" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude-dir", type=Path, default=Path.home() / ".claude",
                        help="Claude Code home; its projects/ subdir is scanned for transcripts")
    parser.add_argument("--offsets-dir", type=Path, default=None,
                        help="Per-session offset dir (default: offset_state_dir from config)")
    parser.add_argument("--hook", type=Path, default=None,
                        help="Stop hook to invoke (default: sibling bq-log-response.sh)")
    parser.add_argument("--min-idle-hours", type=float, default=1.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    dry_run = args.dry_run or os.environ.get("VAULT_DRY_RUN") == "1"

    # Offset dir comes from config; the Stop hook is this script's sibling.
    offsets_dir = args.offsets_dir or Path(CFG["offset_state_dir"])
    hook = args.hook or Path(__file__).resolve().parent / "bq-log-response.sh"

    if dry_run:
        print("resolved target:")
        print(f"  offsets dir : {offsets_dir}")
        print(f"  stop hook   : {hook}")
        print(f"  projects    : {args.claude_dir / 'projects'}")
        print(f"  bq target   : {CFG['bq_project']}:{CFG['messages_table']} "
              "(written by the hook, not this script)")

    if not offsets_dir.is_dir():
        print(f"nothing to do: no offsets dir at {offsets_dir}")
        return 0
    if not hook.is_file():
        # Offsets exist but the flusher is unrunnable: that is a broken safety net,
        # not a no-op. Fail loudly so the log shows a nonzero streak.
        print(f"ERROR: hook missing at {hook} while offsets exist in {offsets_dir}")
        return 1

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    transcripts = index_transcripts(args.claude_dir / "projects")
    lags = find_lagging(offsets_dir, transcripts, time.time(), args.min_idle_hours)
    print(f"[{started}] {len(lags)} idle sessions behind "
          f"(of {len(transcripts)} transcripts, min idle {args.min_idle_hours}h)")

    if dry_run:
        for lag in sorted(lags, key=lambda item: item.idle_h):
            print(f"  dry-run {lag.sid[:8]}  {lag.offset}/{lag.lines} lines  "
                  f"idle {lag.idle_h:.1f}h  -> would re-run {hook.name}")
        return 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        statuses = list(pool.map(
            lambda lag: (lag, flush_session(hook, offsets_dir, lag)), lags))

    counts = Counter(status.split(":")[0] for _, status in statuses)
    for lag, status in statuses:
        if status != "flushed" or (lag.lines - lag.offset) > 10:
            print(f"  {lag.sid[:8]}  {lag.offset}/{lag.lines} lines  "
                  f"idle {lag.idle_h:.1f}h  {status}")
    print(f"summary: flushed={counts.get('flushed', 0)} "
          f"failed={counts.get('failed', 0)} skipped={counts.get('skipped', 0)}")
    return 1 if counts.get("failed", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
