#!/usr/bin/env python3
"""Read-only scan for sessions that hit the OAuth "session expired" error after a token wipe.

Usage: scan_casualties.py [--home-root DIR] --since TIME ACCOUNT

Looks at <home-root>/<account>/.claude/projects/*/*.jsonl (modified at or after TIME) and
prints one line per session that contains an API error entry, marked STOPPED (the
error is the last user/assistant entry) or RECOVERED (the session carried on afterwards),
with the last thing the user asked before the error. Then a SUMMARY line:
  SUMMARY since=<YYYY-MM-DDTHH:MM:SSZ> sessions=N files=N stopped=N recovered=N partial=N unreadable=N

RECOVERED needs a normal assistant reply after the last error; user-only entries after it
(a resent message, a notification) leave the session STOPPED. A user/assistant entry with an
unreadable shape makes its file UNREADABLE (malformed_entry=N). The ask text is redacted
(sk-ant- tokens, 32+ char token-like runs) and timestamps print only as parsed UTC.

A session can resume under another project folder, leaving transcript fragments with the
same session id in several folders. Fragments are grouped by session id, judged together
(merged by entry timestamp), and a group is included when ANY fragment is new enough.

An error entry is an assistant entry flagged isApiErrorMessage true that is either
error "authentication_failed" or says "OAuth session expired" / "could not be refreshed".
Plain assistant prose, tool results and user text that quote the phrase never match.
A bad LAST line (a write in progress) is tolerated when valid entries precede it: the file
is still analysed and also reported as PARTIAL <path> bad_last_line=N.
It never writes or modifies any file and fails closed: a file or folder it cannot read is
UNREADABLE, never silently counted as fine.

Exit codes: 3 if any UNREADABLE or PARTIAL; else 1 if any STOPPED; else 0; 2 = usage error.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

# Harness tags (<task-notification>, <system-reminder>, ...) always have a hyphenated name;
# plain markup such as <div> or <task> in a real request is kept as the ask.
HARNESS_TAG_RE = re.compile(r"^<[a-z][a-z0-9]*(-[a-z0-9]+)+[\s>/]")
SK_RE =re.compile(r"sk-ant-\S*")
LONG_RUN_RE = re.compile(r"[A-Za-z0-9_.=+/-]{32,}")  # token-like runs
PHRASES = ("oauth session expired", "could not be refreshed")
# `stat -c %y` form: 2025-03-04 20:21:21.663934721 +0000
STAT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.(\d+))? ([+-])(\d{2})(\d{2})$")


def valid_account(name):
    return bool(name) and "/" not in name and name not in (".", "..")


def parse_since(value):
    """ISO 8601 (Z or offset), 'YYYY-MM-DD HH:MM[:SS]' or `stat -c %y` form; naive = UTC.

    Returns an aware datetime.
    """
    v = value.strip()
    try:
        m = STAT_RE.match(v)
        if m:
            day, hms, frac, sign, hh, mm = m.groups()
            micro = (frac or "0")[:6].ljust(6, "0")
            v = f"{day}T{hms}.{micro}{sign}{hh}:{mm}"
        elif v.endswith("Z"):
            v = v[:-1] + "+00:00"  # explicit, so it does not depend on the Python version
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid time: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def content_text(msg):
    """Plain string content, or the joined text of text blocks. Never tool_use/tool_result."""
    if not isinstance(msg, dict):
        return ""
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c
                        if isinstance(b, dict) and b.get("type") == "text"
                        and isinstance(b.get("text", ""), str))
    return ""


def is_error(entry):
    """Only the harness's own API-error entry: prose that merely quotes the phrase is not one."""
    if entry.get("type") != "assistant" or entry.get("isApiErrorMessage") is not True:
        return False
    if entry.get("error") == "authentication_failed":
        return True
    low = content_text(entry.get("message")).lower()
    return any(p in low for p in PHRASES)


def valid_block(b):
    """A content block is a dict with a string type; text blocks also carry string text."""
    if not isinstance(b, dict) or not isinstance(b.get("type"), str):
        return False
    return b["type"] != "text" or isinstance(b.get("text"), str)


def is_malformed(e):
    """A user/assistant entry we cannot read the shape of must not be judged as fine.

    A record with no string type is malformed. Records with any other string type
    (system, summary, attachment, ...) are left alone.
    """
    if not isinstance(e.get("type"), str):
        return True
    if e["type"] not in ("user", "assistant") or e.get("isSidechain") is True:
        return False
    msg = e.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("content"), (str, list)):
        return True
    if isinstance(msg["content"], list) and not all(valid_block(b) for b in msg["content"]):
        return True
    # A flagged API error with no error code and no text cannot be classified.
    return (e.get("type") == "assistant" and e.get("isApiErrorMessage") is True
            and not isinstance(e.get("error"), str) and not content_text(msg).strip())


def load_entries(path):
    """Return (entries, partial_line, reason).

    reason is set (and entries None) when the file is unreadable. partial_line is the
    number of a bad LAST line, tolerated only when valid entries precede it.
    """
    with open(path, errors="replace") as f:
        lines = [(n, ln) for n, ln in enumerate(f, 1) if ln.strip()]
    entries = []
    for i, (n, ln) in enumerate(lines):
        try:
            e = json.loads(ln)
            if not isinstance(e, dict):
                raise ValueError("not an object")
        except ValueError:
            if i == len(lines) - 1 and entries:
                return entries, n, None  # write in progress
            return None, None, f"bad_json_line={n}"
        if is_malformed(e):
            return None, None, f"malformed_entry={n}"
        entries.append(e)
    return entries, None, None


def find_ask(turns, end):
    """Last user text before turns[end] that is not a harness notification or tool result."""
    for e in reversed(turns[:end]):
        if e.get("type") != "user":
            continue
        text = content_text(e.get("message")).strip()
        if not text or HARNESS_TAG_RE.match(text):
            continue
        # Redact before truncating so a secret cut in half can never leak a prefix.
        text = SK_RE.sub("[REDACTED]", text)
        text = LONG_RUN_RE.sub("[REDACTED]", text)
        text = " ".join(text.split()).replace('"', "'")
        return text[:100]
    return ""


def entry_dt(entry):
    """An entry's timestamp as an aware datetime, or None when missing or unparseable."""
    v = entry.get("timestamp") if entry else None
    if not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v[:-1] + "+00:00" if v.endswith("Z") else v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt.timestamp()
    except (ValueError, OverflowError, OSError):
        return None
    return dt


def entry_time(entry):
    dt = entry_dt(entry)
    return dt.timestamp() if dt else None


def ts(entry):
    """Print timestamps only as parsed UTC, never the raw file text."""
    dt = entry_dt(entry)
    if dt is None:
        return "unknown"
    try:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError):
        return "unknown"


def merge_turns(fragments):
    """Merge the user/assistant entries of several fragments into one timeline.

    Sort key is (time, fragment index, position). An entry with no usable timestamp
    inherits the time of the entry before it in its own file (0 if it leads the file),
    so it keeps its within-file place and the sort is stable and deterministic.
    """
    keyed = []
    for fi, entries in enumerate(fragments):
        last = 0.0
        for pos, e in enumerate(entries):
            t = entry_time(e)
            if t is None:
                t = last
            last = t
            if e.get("isSidechain") is not True and e.get("type") in ("user", "assistant"):
                keyed.append(((t, fi, pos), e))
    keyed.sort(key=lambda k: k[0])
    return [e for _, e in keyed]


def judge(turns, projects, sid):
    """Return (status, session line or None) for a merged timeline."""
    errs = [i for i, e in enumerate(turns) if is_error(e)]
    if not errs:
        return "CLEAN", None
    # Recovered only if the assistant produced a normal reply after the last error.
    # A user message, a notification, or any flagged API error (rate limit, server
    # error, another auth error) is not a continuation.
    recovered = any(e.get("type") == "assistant" and e.get("isApiErrorMessage") is not True
                    for e in turns[errs[-1] + 1:])
    status = "RECOVERED" if recovered else "STOPPED"
    return status, (f"{status} {sid} project={','.join(sorted(projects))} "
                    f"first_error={ts(turns[errs[0]])} last_entry={ts(turns[-1])} "
                    f"ask=\"{find_ask(turns, errs[-1])}\"")


def discover(projects):
    """Return (files, unreadable). One bad project folder or entry never aborts the rest.

    Raises OSError only when the top-level projects folder itself cannot be listed.
    """
    files, bad = [], []
    for proj in sorted(os.scandir(projects), key=lambda d: d.name):
        try:
            if not proj.is_dir():
                continue
            entries = sorted(os.scandir(proj.path), key=lambda d: d.name)
        except OSError as ex:
            bad.append((proj.path, type(ex).__name__))
            continue
        for f in entries:
            if not f.name.endswith(".jsonl") or f.name.startswith("agent-"):
                continue
            try:
                if f.is_file():
                    files.append(f.path)
            except OSError as ex:
                bad.append((f.path, type(ex).__name__))
    return files, bad


def main():
    p = argparse.ArgumentParser(description="Read-only scan for OAuth-expiry casualties.")
    p.add_argument("--home-root", default="/home")
    p.add_argument("--since", required=True, type=parse_since)
    p.add_argument("account", metavar="ACCOUNT")
    args = p.parse_args()
    if not valid_account(args.account):
        p.error(f"invalid account name: {args.account!r}")
    since_ts = args.since.timestamp()
    since_txt = args.since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    projects = os.path.join(args.home_root, args.account, ".claude", "projects")
    try:
        files, bad = discover(projects)
    except OSError as ex:
        print(f"UNREADABLE {projects} {type(ex).__name__}")
        return 3

    groups = {}
    for path in files:
        groups.setdefault(os.path.basename(path)[:-len(".jsonl")], []).append(path)

    sessions = nfiles = stopped = recovered = partial = 0
    unreadable = len(bad)
    for path, cls in bad:
        print(f"UNREADABLE {path} {cls}")
    for sid in sorted(groups):
        paths = groups[sid]
        fresh = False
        for path in paths:
            try:
                fresh = fresh or os.stat(path).st_mtime >= since_ts
            except OSError as ex:
                unreadable += 1
                print(f"UNREADABLE {path} {type(ex).__name__}")
        if not fresh:
            continue
        sessions += 1
        fragments, projects = [], []
        for path in paths:
            nfiles += 1
            try:
                entries, partial_line, reason = load_entries(path)
            except OSError as ex:
                entries, partial_line, reason = None, None, type(ex).__name__
            if entries is None:
                unreadable += 1
                print(f"UNREADABLE {path} {reason}")
                continue
            if partial_line:
                partial += 1
                print(f"PARTIAL {path} bad_last_line={partial_line}")
            fragments.append(entries)
            projects.append(os.path.basename(os.path.dirname(path)))
        status, line = judge(merge_turns(fragments), projects, sid)
        if line:
            print(line)
        stopped += status == "STOPPED"
        recovered += status == "RECOVERED"
    print(f"SUMMARY since={since_txt} sessions={sessions} files={nfiles} stopped={stopped} "
          f"recovered={recovered} partial={partial} unreadable={unreadable}")

    if unreadable or partial:
        return 3
    return 1 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
