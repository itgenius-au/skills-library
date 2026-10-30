#!/usr/bin/env python3
"""Read-only check: is any Claude Code session of an account in the middle of a turn?

Usage: turn_check.py [--home-root DIR] [--proc-root DIR] [--window-min N] ACCOUNT [ACCOUNT ...]

Run it as root on the VM (sudo -n python3 -I turn_check.py claude-1 claude-2). It prints one
verdict line per account, then a SUMMARY line:
  IDLE     every transcript it had to check ends on a finished assistant turn
  BUSY     at least one transcript ends on something else: a turn is in progress
  UNKNOWN  it could not tell (see detail=...): treat it like BUSY

Which transcripts it checks, under <home-root>/<account>/.claude/projects:
  * every main transcript (*.jsonl) written in the last --window-min minutes (default 20), and
  * any older one whose session id (its file name) a live process of that account still
    references: in /proc/<pid>/cmdline, or in an open /proc/<pid>/fd link such as
    /tmp/claude-<uid>/<project>/<session id>/. A long build or test writes nothing for a
    long time, so the age of the file alone proves nothing.
An old transcript that no live process references is a dead session and is not read.

For each transcript, the last user or assistant entry must be an assistant entry whose
stop_reason is end_turn or stop_sequence. Anything else is a turn in progress.

It skips subagent transcripts (agent-*.jsonl, anything under a subagents folder) and entries
flagged isSidechain: they rarely end on end_turn, and a parent that waits on a subagent already
ends on a tool_use entry, so the parent is caught on its own.

It never writes anything and never prints transcript text: a mid-turn line shows only the
session id, the project folder name, and the type and stop_reason of the last entry.

It fails closed. A missing or unreadable projects folder, an unreadable transcript, a line that
is not a complete JSON object (a write in progress), a file with no user or assistant entry, an
account that does not exist, or a /proc read that did not finish (anything but a process that
just exited) gives UNKNOWN, never IDLE. Names read from disk are printed only when they are
plain, so a file name cannot forge a verdict line.

Nothing can stop a new turn from starting in the seconds after the check. Run it as the last
step before the restart.

Exit codes: 3 if any account is UNKNOWN; else 1 if any is BUSY; else 0 (all IDLE); 2 = usage error.
"""
import argparse
import json
import os
import pwd
import re
import stat
import sys
import time

IDLE_STOPS = ("end_turn", "stop_sequence")
TAIL = 4 * 1024 * 1024  # the last turn is at the end of the file: do not read a huge one whole
GONE = (FileNotFoundError, ProcessLookupError)  # the process exited while we looked: not a problem
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PLAIN_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
STOP_RE = re.compile(r"^[a-z_]{1,30}$")


def positive_int(value):
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}")
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def valid_account(name):
    return bool(name) and "/" not in name and name not in (".", "..")


def plain(text):
    """A name from disk, or a placeholder when it holds anything but plain characters."""
    return text if PLAIN_RE.match(text) else "<odd-name>"


def account_uid(account):
    try:
        return pwd.getpwnam(account).pw_uid
    except KeyError:
        return None


def live_refs(proc_root, uid):
    """Return (strings, problems): cmdline and fd-link text of the processes of uid.

    A read error other than a process that vanished means the set may be incomplete, so it is
    reported as a problem (fail closed).
    """
    refs, problems = [], set()
    try:
        pids = os.listdir(proc_root)
    except OSError:
        return refs, {"process_table_unreadable"}
    for pid in pids:
        if not pid.isdigit():
            continue
        pdir = os.path.join(proc_root, pid)
        try:
            if os.stat(pdir).st_uid != uid:
                continue
            with open(os.path.join(pdir, "cmdline"), "rb") as fh:
                refs.append(fh.read().decode("utf-8", "replace"))
            fddir = os.path.join(pdir, "fd")
            for name in os.listdir(fddir):
                try:
                    refs.append(os.readlink(os.path.join(fddir, name)))
                except GONE:
                    pass
                except OSError:
                    problems.add("process_inspection_incomplete")
        except GONE:
            continue
        except OSError:
            problems.add("process_inspection_incomplete")
    return refs, problems


def find_transcripts(root):
    """Return (paths, problems) for the main transcripts under the projects folder."""
    try:
        if not stat.S_ISDIR(os.stat(root).st_mode):
            return [], {"projects_folder_missing"}
    except FileNotFoundError:
        return [], {"projects_folder_missing"}
    except OSError:
        return [], {"projects_folder_unreadable"}
    paths, problems = [], set()

    def onerror(_err):
        problems.add("folder_unreadable")

    for folder, dirs, names in os.walk(root, onerror=onerror):
        dirs[:] = sorted(d for d in dirs if d != "subagents")
        for name in sorted(names):
            if name.endswith(".jsonl") and not name.startswith("agent-"):
                paths.append(os.path.join(folder, name))
    return paths, problems


def read_last_entry(path):
    """Return (last main user/assistant entry or None, problem or None).

    Opens without following links and without blocking, so a symlink or a named pipe that an
    account planted under the name of a transcript cannot hang or mislead the check.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None, "file_unreadable"
    try:
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return None, "file_not_regular"
            size = fh.seek(0, 2)
            fh.seek(max(0, size - TAIL))
            lines = fh.read().split(b"\n")
    except OSError:
        return None, "file_unreadable"
    if size > TAIL:
        lines = lines[1:]  # the first line of a tail read is cut in the middle
    last = None
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):
            return None, "unparseable_line"
        if not isinstance(entry, dict):
            return None, "unparseable_line"
        if entry.get("type") in ("user", "assistant") and entry.get("isSidechain") is not True:
            last = entry
    return last, None


def is_finished(entry):
    if entry.get("type") != "assistant":
        return False
    message = entry.get("message")
    return isinstance(message, dict) and message.get("stop_reason") in IDLE_STOPS


def describe(entry):
    message = entry.get("message")
    stop = message.get("stop_reason") if isinstance(message, dict) else None
    stop = stop if isinstance(stop, str) and STOP_RE.match(stop) else "none"
    return f"{entry.get('type')}/{stop}"


def check_account(account, home_root, proc_root, uid, window_min, now):
    """Return (verdict, checked, detail_words, lines) for one account."""
    root = os.path.join(home_root, account, ".claude", "projects")
    paths, problems = find_transcripts(root)
    if "projects_folder_missing" in problems or "projects_folder_unreadable" in problems:
        return "UNKNOWN", 0, sorted(problems), []
    # The live references come first: an old transcript is read only when a process points at it.
    refs, ref_problems = live_refs(proc_root, uid)
    problems |= ref_problems
    blob = "\n".join(refs)
    cutoff = now - window_min * 60
    checked, mid_turn = 0, []
    for path in paths:
        stem = os.path.basename(path)[:-len(".jsonl")]
        try:
            recent = os.lstat(path).st_mtime >= cutoff
        except OSError:
            problems.add("file_unreadable")
            continue
        live = (not recent) and bool(UUID_RE.match(stem)) and stem in blob
        if not recent and not live:
            continue  # a dead old session: not read at all
        checked += 1
        last, problem = read_last_entry(path)
        if problem:
            problems.add(problem)
            continue
        if last is None:
            problems.add("no_user_or_assistant_entry")
            continue
        if is_finished(last):
            continue
        tag = "recent" if recent else "old, live process"
        project = plain(os.path.basename(os.path.dirname(path)))
        mid_turn.append(f"  mid-turn session={plain(stem)} project={project} "
                        f"last={describe(last)} ({tag})")
    if mid_turn:
        return "BUSY", checked, sorted(problems) or ["mid_turn"], mid_turn
    if problems:
        return "UNKNOWN", checked, sorted(problems), []
    return "IDLE", checked, ["ok"], []


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Read-only check for sessions in the middle of a turn (IDLE, BUSY or UNKNOWN).")
    p.add_argument("--home-root", default="/home")
    p.add_argument("--proc-root", default="/proc", help="for tests: a fake /proc tree")
    p.add_argument("--window-min", type=positive_int, default=20,
                   help="minutes: a transcript written this recently is always checked (default 20)")
    p.add_argument("accounts", metavar="ACCOUNT", nargs="+")
    args = p.parse_args(argv)
    for account in args.accounts:
        if not valid_account(account):
            p.error(f"invalid account name: {account!r}")

    counts = {"IDLE": 0, "BUSY": 0, "UNKNOWN": 0}
    now = time.time()
    for account in args.accounts:
        uid = account_uid(account)
        if uid is None:
            verdict, checked, detail, lines = "UNKNOWN", 0, ["no_such_account"], []
        else:
            verdict, checked, detail, lines = check_account(
                account, args.home_root, args.proc_root, uid, args.window_min, now)
        counts[verdict] += 1
        print(f"{account} {verdict} checked={checked} detail={','.join(detail)}")
        for line in lines:
            print(line)
    print(f"SUMMARY idle={counts['IDLE']} busy={counts['BUSY']} unknown={counts['UNKNOWN']}")

    if counts["UNKNOWN"]:
        return 3
    return 1 if counts["BUSY"] else 0


if __name__ == "__main__":
    sys.exit(main())
