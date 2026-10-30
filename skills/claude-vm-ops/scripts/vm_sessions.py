#!/usr/bin/env python3
"""Read-only inventory of live Claude Code sessions on a Claude Code VM.

Usage: vm_sessions.py [-h]

Run as root on the VM (sudo python3 -I vm_sessions.py). Prints one JSON object per live
session: account, pid, kind, cwd, age, idle minutes, process-tree size / RSS / CPU seconds,
and from the transcript: title, first user message, last user message, last assistant text.

The output holds session text. Token-like strings in that text are replaced with [REDACTED]
(sk-ant- tokens and 32+ character token-like runs, the same patterns scan_casualties.py
uses), but anything else a session said is still there. Write the output to a private
path outside any repository, and delete it when you are done.

It never writes anything and never calls `claude agents` (that command can delete
registry files while it lists).

A session process is recognised by the file name of its binary. The default is `claude.exe`,
the name the npm install of Claude Code uses. If your install names the binary differently,
set CLAUDE_SESSION_BIN to that name. Check with: ps -eo pid,comm,args | grep '[c]laude'
"""
import argparse
import json
import os
import pwd
import re
import sys
import time

SESSION_BIN = os.environ.get("CLAUDE_SESSION_BIN", "claude.exe")
UUID_RE = re.compile(
    r"/tmp/claude-\d+/([^/]+)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
# Token shapes, the same patterns as scan_casualties.py.
SK_RE = re.compile(r"sk-ant-\S*")
LONG_RUN_RE = re.compile(r"[A-Za-z0-9_.=+/-]{32,}")
HZ = os.sysconf("SC_CLK_TCK")
BOOT = time.time() - float(open("/proc/uptime").read().split()[0])


def procs():
    out = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            st = open(f"/proc/{d}/stat").read()
            rest = st[st.rindex(")") + 2:].split()
            ppid, utime, stime, start = int(rest[1]), int(rest[11]), int(rest[12]), int(rest[19])
            uid = os.stat(f"/proc/{d}").st_uid
            args = open(f"/proc/{d}/cmdline", "rb").read().split(b"\0")
            rss = 0
            for line in open(f"/proc/{d}/status"):
                if line.startswith("VmRSS"):
                    rss = int(line.split()[1])
            out[int(d)] = dict(ppid=ppid, cpu=(utime + stime) / HZ, start=BOOT + start / HZ, uid=uid,
                               args=[a.decode(errors="replace") for a in args if a], rss=rss)
        except Exception:
            pass
    return out


def text_of(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def redact(text):
    """Replace token-like strings. Do this BEFORE cutting the text, so a secret that the cut
    would split can never leak a prefix."""
    return LONG_RUN_RE.sub("[REDACTED]", SK_RE.sub("[REDACTED]", text))


def read_transcript(path):
    info = dict(title=None, first_user=None, last_user=None, last_assistant=None, turns=0)
    try:
        with open(path, errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                t = e.get("type")
                if t == "summary" and e.get("summary"):
                    info["title"] = redact(str(e["summary"]))
                if e.get("customTitle") or e.get("aiTitle"):
                    info["title"] = redact(str(e.get("customTitle") or e.get("aiTitle")))
                if t == "user" and not e.get("isMeta") and not e.get("toolUseResult"):
                    txt = redact(text_of(e.get("message", {})).strip())
                    if txt and not txt.startswith("<"):
                        info["turns"] += 1
                        if info["first_user"] is None:
                            info["first_user"] = txt[:220]
                        info["last_user"] = txt[:220]
                if t == "assistant":
                    txt = redact(text_of(e.get("message", {})).strip())
                    if txt:
                        info["last_assistant"] = txt[-260:]
    except Exception as ex:
        info["error"] = str(ex)
    return info


def main(argv=None):
    argparse.ArgumentParser(
        description="Read-only inventory of live Claude Code sessions. Run as root. Prints one JSON "
                    "object per session. The output holds session text: write it to a private path "
                    "outside any repository and delete it when done.",
        epilog="Set CLAUDE_SESSION_BIN if your session binary is not named claude.exe.",
    ).parse_args(argv)
    P = procs()
    children = {}
    for pid, p in P.items():
        children.setdefault(p["ppid"], []).append(pid)

    def tree(pid):
        stack, seen = [pid], []
        while stack:
            x = stack.pop()
            seen.append(x)
            stack.extend(children.get(x, []))
        return seen

    now = time.time()
    for pid, p in sorted(P.items()):
        if p["uid"] == 0 or not p["args"]:
            continue
        try:
            pw = pwd.getpwuid(p["uid"])
        except KeyError:
            continue
        joined = " ".join(p["args"])
        if os.path.basename(p["args"][0]) != SESSION_BIN or " daemon run" in joined or "--bg-spare" in joined:
            continue
        kind = "host" if "--sdk-url" in joined else "other"
        slug = uuid = None
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    m = UUID_RE.search(os.readlink(f"/proc/{pid}/fd/{fd}"))
                except OSError:
                    continue
                if m:
                    slug, uuid = m.group(1), m.group(2)
                    break
        except OSError:
            pass
        tpath = f"{pw.pw_dir}/.claude/projects/{slug}/{uuid}.jsonl" if uuid else None
        has_t = bool(tpath and os.path.exists(tpath))
        info = read_transcript(tpath) if has_t else {}
        mtime = os.path.getmtime(tpath) if has_t else None
        t = tree(pid)
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            cwd = None
        print(json.dumps(dict(
            user=pw.pw_name, pid=pid, kind=kind, uuid=uuid, cwd=cwd,
            age_h=round((now - p["start"]) / 3600, 1),
            idle_min=round((now - mtime) / 60) if mtime else None,
            tree_procs=len(t), tree_rss_mb=round(sum(P[x]["rss"] for x in t if x in P) / 1024),
            tree_cpu_s=round(sum(P[x]["cpu"] for x in t if x in P)),
            **info)))


if __name__ == "__main__":
    sys.exit(main())
