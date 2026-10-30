#!/usr/bin/env python3
"""Reconnect offline Claude Code background sessions that were started with `claude --bg`.

Subcommands: inventory, queue-check, resume, read, last-reply, wrap-wait.
Everything it reads lives under ~/.claude (CLAUDE_CONFIG_DIR moves that folder). State lives in
--work DIR (default: <claude config dir>/session-recovery). It needs no config file. Stdlib only.

The only things it changes are the sessions it wakes with `claude --bg --resume`. It never
pins, archives or deletes anything.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "references", "review-prompt.md")
DEFAULT_MARK = "RECOVERY REVIEW v1"
# claude.ai stamps updated_at ~8 h (28,800 s) after the last local entry when it
# retires an idle session; that gap is normal. Anything beyond this slack means
# a message was queued remotely while the session was offline.
GAP_THRESHOLD_S = 29100
WRAP_DONE = "Session Wrap done"
WRAP_ARCHIVE = "You can archive this conversation now."
WRAP_NOT_READY = "Not ready to archive:"
WRAP_FRESH = "Next session starts fresh."
WRAP_HELD = "Reply `go`"
POLL_S = 30
PIN_HINT = ("PIN: nothing was pinned. A session that will wait for you more than about 8 hours is "
            "retired again unless you pin it: open `claude agents` and press Ctrl+T on its row.")


def nudge_text(mark=DEFAULT_MARK):
    return (f"{mark} follow-up: the review request was saved for you and should arrive with this wake. "
            f"Run it once. If you did not receive a message starting '{mark}. The user asked the Session "
            "Recovery session', reply only 'MISSING REVIEW PROMPT' and stop, without running tools.")


NUDGE = nudge_text()
MARK = DEFAULT_MARK  # kept for callers that import the default


# ---------- config ----------

def config_dir():
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return os.path.expanduser(env) if env else os.path.expanduser("~/.claude")


def default_work():
    return os.path.join(config_dir(), "session-recovery")


def home(p):
    return os.path.expanduser(p)


# ---------- pure helpers ----------

def load_page(path):
    """Return the session list from a page file: raw tool result text or bare {"data": [...]} JSON."""
    raw = open(path).read()
    i = raw.find('{"ccr"')
    if i >= 0:
        obj = json.JSONDecoder().raw_decode(raw[i:])[0]
    else:
        obj = json.loads(raw)
    if isinstance(obj, dict) and "ccr" in obj:
        obj = obj["ccr"]
    return obj.get("data", []) if isinstance(obj, dict) else list(obj)


def load_pages(paths):
    out, seen = [], set()
    for p in paths:
        for s in load_page(p):
            if s["id"] not in seen:
                seen.add(s["id"])
                out.append(s)
    return out


def suffix(sid):
    return sid.split("_", 1)[1] if "_" in sid else sid


def read_job_files(jobs_glob):
    """Every readable job state dict under the glob."""
    out = []
    for f in glob.glob(jobs_glob):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def load_jobs(jobs_glob):
    """Map bridge suffix (cse_<X> -> X) to the job state dict."""
    jobs = {}
    for d in read_job_files(jobs_glob):
        b = d.get("bridgeSessionId") or ""
        if b:
            jobs[suffix(b)] = d
    return jobs


def build_rows(sessions, jobs):
    """Rows for the non-archived `disconnected` sessions in a session list, joined to their VM jobs."""
    rows = []
    for s in sessions:
        if s.get("session_status") == "SESSION_STATUS_ARCHIVED":
            continue
        if s.get("connection_status") != "disconnected":
            continue
        j = jobs.get(suffix(s["id"]))
        rows.append({
            "remote": s["id"], "title": s.get("title", ""), "origin": s.get("origin") or "",
            "status": s.get("session_status", "")[15:],
            "created": s.get("created_at", "")[:16], "updated": s.get("updated_at", "")[:16],
            "updated_at": s.get("updated_at"),
            "local": (j or {}).get("sessionId"), "short": (j or {}).get("daemonShort"),
            "state": (j or {}).get("state"), "detail": ((j or {}).get("detail") or "")[:90],
            "cwd": (j or {}).get("cwd"),
        })
    return rows


def rows_from_jobs(jobs, is_live):
    """Local-only rows: every job that has a session id and short id and no live process.

    There is no remote status here, so `updated_at` is None and queue-check reads CHECK for every
    row: the owner must read each thread in claude.ai/code before a wake."""
    rows = []
    for j in jobs:
        local, short = j.get("sessionId"), j.get("daemonShort")
        if not local or not short or is_live(local):
            continue
        rows.append({
            "remote": ("session_" + suffix(j["bridgeSessionId"])) if j.get("bridgeSessionId") else None,
            "title": j.get("name") or "", "origin": "", "status": "",
            "created": str(j.get("createdAt") or "")[:16], "updated": str(j.get("updatedAt") or "")[:16],
            "updated_at": None, "local": local, "short": short, "state": j.get("state"),
            "detail": (j.get("detail") or "")[:90], "cwd": j.get("cwd"),
        })
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows


def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def gap_seconds(remote_updated, last_local):
    if not remote_updated or not last_local:
        return None
    return (parse_ts(remote_updated) - parse_ts(last_local)).total_seconds()


def gap_flag(gap):
    return "CHECK" if gap is None or gap > GAP_THRESHOLD_S else "ok"


def fill_prompt(template, dupe_text, mark=DEFAULT_MARK):
    d = f"\nDuplicate group: {dupe_text}\n" if dupe_text else ""
    return template.replace("{DUPES}", d).replace("{MARK}", mark)


def read_jsonl(path):
    out = []
    for line in open(path):
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def user_text(e):
    c = e.get("message", {}).get("content")
    if isinstance(c, str):
        return c
    return " ".join(x.get("text", "") for x in (c or []) if isinstance(x, dict))


def main_thread(entries):
    """Drop subagent (isSidechain) and meta (isMeta) records. Without it a delegated subagent's tools
    and final block read as this session's."""
    return [e for e in entries if not (e.get("isSidechain") or e.get("isMeta"))]


def last_index(entries, pred):
    idx = None
    for i, e in enumerate(entries):
        if pred(e):
            idx = i
    return idx


def collect_after(entries, start):
    """Assistant text blocks and tool_use summaries after entries[start]."""
    texts, tools = [], []
    for e in entries[start + 1:]:
        if e.get("type") != "assistant":
            continue
        for b in e.get("message", {}).get("content", []) or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                texts.append(b["text"])
            elif b.get("type") == "tool_use":
                tools.append(f'{b.get("name")}: {json.dumps(b.get("input", {}))[:160]}')
    return texts, tools


def review_reply(entries, mark=DEFAULT_MARK):
    """(text, tools, err) after the last user turn containing the review marker."""
    entries = main_thread(entries)
    start = last_index(entries, lambda e: e.get("type") == "user" and mark in user_text(e))
    if start is None:
        return None, [], "prompt not in transcript yet"
    texts, tools = collect_after(entries, start)
    return "\n\n".join(texts), tools, ""


def is_new_turn(e):
    """A message that asks the session for more: a queued message, or a user record that is not only
    tool results (a typed or delivered message)."""
    if e.get("type") == "queue-operation":
        return True
    if e.get("type") != "user":
        return False
    c = (e.get("message") or {}).get("content")
    if isinstance(c, str):
        return bool(c.strip())
    blocks = [b for b in (c or []) if isinstance(b, dict)]
    return any(b.get("type") != "tool_result" for b in blocks)


def has_text(e):
    return e.get("type") == "assistant" and any(
        isinstance(b, dict) and b.get("type") == "text" for b in (e.get("message") or {}).get("content", []) or [])


def unanswered_after_reply(entries, start):
    """True when a new turn came in after the last assistant text that follows entries[start]: the reply
    the caller would judge is no longer the session's current state."""
    last_text = last_index(entries[start + 1:], has_text)
    if last_text is None:
        return False
    return any(is_new_turn(e) for e in entries[start + 1 + last_text + 1:])


def marker_reply(entries, mark, with_pending=False):
    """(hits, texts, tool_count) after the last user/queue-operation/attachment entry containing mark.
    With with_pending=True a 4th value says whether a newer user turn is still unanswered."""
    kinds = ("user", "queue-operation", "attachment")
    entries = main_thread(entries)
    hits = sum(1 for e in entries if e.get("type") in kinds and mark in json.dumps(e))
    start = last_index(entries, lambda e: e.get("type") in kinds and mark in json.dumps(e))
    if start is None:
        return (0, [], 0, False) if with_pending else (0, [], 0)
    texts, tools = collect_after(entries, start)
    if with_pending:
        return hits, texts, len(tools), unanswered_after_reply(entries, start)
    return hits, texts, len(tools)


def wrap_status(texts):
    """DONE when the final reply block has the line `Session Wrap done` followed only by the session-wrap
    skill's own closing line (`You can archive this conversation now.`); HELD when that closing line says
    the wrap waits on the user (`Not ready to archive: ...`, `Next session starts fresh.`) or the block asks
    for `Reply `go``; else RUNNING. Only the last block counts, so an earlier progress line cannot trip it."""
    if not texts:
        return "RUNNING"
    last = texts[-1].rstrip()
    lines = [ln.strip() for ln in last.splitlines()]
    idx = [i for i, ln in enumerate(lines) if ln == WRAP_DONE]
    if idx:
        after = [ln for ln in lines[idx[-1] + 1:] if ln]
        if all(ln == WRAP_ARCHIVE for ln in after):
            return "DONE"
        if any(ln.startswith(WRAP_NOT_READY) or ln == WRAP_FRESH for ln in after):
            return "HELD"
    if WRAP_HELD in last:
        return "HELD"
    return "RUNNING"


def parse_result_block(text):
    """Pull REVIEW RESULT from the last fenced block of the reply."""
    blocks = re.findall(r"```[^\n]*\n(.*?)```", text or "", re.S)
    out = {"review_result": None}
    if not blocks:
        return out
    for line in blocks[-1].splitlines():
        m = re.match(r"\s*REVIEW RESULT:\s*(.*)", line)
        if m:
            out["review_result"] = m.group(1).strip()
    return out


def live_pid(uuid, sessions_glob=None):
    for f in glob.glob(sessions_glob or os.path.join(config_dir(), "sessions", "*.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("sessionId") == uuid:
            pid = d.get("pid")
            if pid and os.path.exists(f"/proc/{pid}"):
                return pid
    return None


def job_state(short):
    """The background job's state.json for an 8-character short id, or {}."""
    try:
        with open(os.path.join(config_dir(), "jobs", short, "state.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def project_dir_name(cwd):
    """Claude Code's project folder name for a cwd: every '/' and '.' becomes '-'."""
    return re.sub(r"[/.]", "-", cwd) if cwd else None


def resolve_transcript(key, by_uuid=True, cwd=None):
    """(path, note) for the exact session's transcript. Never guesses between sessions.

    A short id is first resolved to its full uuid through the job's state.json. A short id that
    matches more than one uuid, with no job to settle it, returns (None, "AMBIGUOUS ...").
    When one uuid has files in more than one project folder, the folder of the session's cwd
    wins, else the most recently modified file (the live continuation)."""
    uuid = key
    if not by_uuid:
        st = job_state(key)
        uuid = st.get("sessionId")
        cwd = cwd or st.get("cwd")
        if not uuid:
            cands = glob.glob(os.path.join(config_dir(), "projects", "*", f"{key}*.jsonl"))
            uuids = sorted({os.path.basename(p)[:-len(".jsonl")] for p in cands})
            if len(uuids) > 1:
                return None, f"AMBIGUOUS short id {key}: {', '.join(uuids)} (pass the full uuid)"
            if not uuids:
                return None, "no transcript"
            uuid = uuids[0]
    fs = glob.glob(os.path.join(config_dir(), "projects", "*", f"{uuid}.jsonl"))
    if not fs:
        return None, "no transcript"
    want = project_dir_name(cwd)
    same = [p for p in fs if want and os.path.basename(os.path.dirname(p)) == want]
    pick = same or fs
    return max(pick, key=lambda p: os.path.getmtime(p)), None


def find_transcript(key, by_uuid=True, cwd=None):
    return resolve_transcript(key, by_uuid, cwd)[0]


def last_local_ts(path):
    # Deliberately reads ALL records: a sidechain timestamp still means the session was active.
    last = None
    for e in read_jsonl(path):
        t = e.get("timestamp")
        if isinstance(t, str) and (last is None or t > last):
            last = t
    return last


# ---------- CLI wrappers ----------

def inv_path(work):
    return os.path.join(home(work), "inventory.json")


def load_inventory(work):
    try:
        return json.load(open(inv_path(work)))
    except OSError:
        sys.exit(f"no inventory at {inv_path(work)}; run `inventory` first")


def vm_rows(work, shorts=()):
    rows = [r for r in load_inventory(work) if r["short"]]
    return [r for r in rows if not shorts or r["short"] in shorts]


def cmd_inventory(a):
    jobs_glob = os.path.join(config_dir(), "jobs", "*", "state.json")
    if a.sessions:
        rows = build_rows(load_pages(a.sessions), load_jobs(jobs_glob))
    else:
        rows = rows_from_jobs(read_job_files(jobs_glob), lambda u: bool(live_pid(u)))
    os.makedirs(home(a.work), exist_ok=True)
    json.dump(rows, open(inv_path(a.work), "w"), indent=1)
    for r in rows:
        print(f'{(r["short"] or "-"):8} {r["state"] or "-":8} {r["origin"][:12]:12} {r["updated"]} '
              f'| {r["title"][:60]}')
    mode = "disconnected" if a.sessions else "no live process (local jobs only)"
    print(f"{mode}: {len(rows)} | mapped to VM job: {sum(1 for r in rows if r['short'])}")
    return 0


def cmd_queue_check(a):
    for r in vm_rows(a.work, set(a.short)):
        f = find_transcript(r["local"], cwd=r.get("cwd"))
        last = last_local_ts(f) if f else None
        rem = r.get("updated_at")
        gap = gap_seconds(rem, last)
        print(f"{r['short']} {gap_flag(gap):5} remote {str(rem)[:19]} local {str(last)[:19]} "
              f"gap {gap if gap is None else int(gap)}s | {r['title'][:50]}")
    return 0


def trust_hint(cwd):
    print("  TRUST: the CLI saved the message. Trust the MAIN checkout key in ~/.claude.json "
          "projects[<main checkout>].hasTrustDialogAccepted (a worktree uses its main checkout's key; "
          f"cwd was {cwd}), then re-run with --nudge (do not resend the full prompt).")


def cmd_resume(a):
    rows = {r["short"]: r for r in vm_rows(a.work)}
    dupes = json.load(open(a.dupes)) if a.dupes else {}
    template = None
    woke = 0
    for short in a.short:
        r = rows.get(short)
        if not r:
            print(f"{short}: SKIP not in inventory (or no VM job)")
            continue
        if live_pid(r["local"]):
            print(f"{short}: SKIP live process, a resume would start a copy")
            continue
        if a.nudge:
            prompt = nudge_text(DEFAULT_MARK)
        else:
            if template is None:
                template = open(TEMPLATE).read()
            prompt = fill_prompt(template, dupes.get(short), DEFAULT_MARK)
        cwd = os.path.expanduser(r["cwd"] or a.default_cwd)
        # A saved cwd that no longer exists (a removed worktree) is reported, never swapped for
        # another folder: a wake from a different cwd can load the wrong project instructions.
        if not os.path.isdir(cwd):
            print(f"{short}: SKIP missing cwd {cwd} (worktree removed or moved?); "
                  "recreate the folder or wake this session by hand")
            continue
        # No other flags: any flag makes the CLI start a copy instead of resuming.
        try:
            res = subprocess.run(["claude", "--bg", "--resume", r["local"], prompt], cwd=cwd,
                                 stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"{short}: FAIL could not run the resume ({type(e).__name__}: {e}); continuing")
            continue
        out = ((res.stdout or "") + (res.stderr or "")).strip()
        print(f"{short}: rc={res.returncode} {out.replace(chr(10), ' | ')[:400]}")
        if "Workspace not trusted" in out:
            trust_hint(cwd)
        if "started a copy" in out:
            m = re.search(r"started a copy[^\n]*?([0-9a-f]{8})", out)
            print(f"  COPY: {m.group(1) if m else '(id not parsed, see output)'}; "
                  "stop it with `claude stop <id>`")
        elif res.returncode == 0 and "Workspace not trusted" not in out:
            woke += 1
    if woke:
        print(PIN_HINT)
    return 0


def cmd_read(a):
    rows = {r["short"]: r for r in vm_rows(a.work)}
    shorts = [s for s in a.short if s in rows]
    for s in a.short:
        if s not in rows:
            print(f"{s}: not in inventory")
    deadline = time.time() + a.wait
    while True:
        res = {}
        for s in shorts:
            f = find_transcript(rows[s]["local"], cwd=rows[s].get("cwd"))
            res[s] = review_reply(read_jsonl(f), DEFAULT_MARK) if f else (None, [], "no transcript")
        done = bool(shorts) and all(v[0] and "REVIEW RESULT:" in v[0] for v in res.values())
        if done or time.time() >= deadline:
            break
        time.sleep(POLL_S)
    for s, (text, tools, err) in res.items():
        print(f"===== {s} {rows[s]['title']}")
        if err:
            print(err)
        print(f"tool calls after prompt: {len(tools)}")
        for t in tools:
            print("  -", t)
        print("----- reply:")
        print(text or "(none yet)")
        p = parse_result_block(text)
        print(f"REVIEW RESULT: {p['review_result']}")
    return 0 if done else 1


def cmd_last_reply(a):
    for short in a.short:
        f, note = resolve_transcript(short, by_uuid=False)
        if not f:
            print(f"===== {short} {note}")
            continue
        hits, texts, tools = marker_reply(read_jsonl(f), a.mark)
        print("=====", short, "marker hits", hits)
        if hits:
            print("tool calls:", tools)
            print("\n".join(texts)[-2500:])
    return 0


def wrap_state(short, mark):
    """(status, tool count, last reply block) for one session; status also NO-TRANSCRIPT / NO-MARK."""
    f, note = resolve_transcript(short, by_uuid=False)
    if not f:
        # An ambiguous short id is never settled by guessing: it must not read as DONE or HELD.
        return ("AMBIGUOUS" if note and note.startswith("AMBIGUOUS") else "NO-TRANSCRIPT"), 0, (note or "")
    hits, texts, tools, pending = marker_reply(read_jsonl(f), mark, with_pending=True)
    if not hits:
        return "NO-MARK", 0, ""
    status = wrap_status(texts)
    # A message after the wrap (typed or queued) reopens the session until it answers again.
    if pending and status in ("DONE", "HELD"):
        status = "RUNNING"
    return status, tools, (texts[-1] if texts else "")


def cmd_wrap_wait(a):
    deadline = time.time() + a.wait
    while True:
        res = {s: wrap_state(s, a.mark) for s in a.short}
        settled = all(v[0] in ("DONE", "HELD") for v in res.values())
        if settled or time.time() >= deadline:
            break
        time.sleep(POLL_S)
    for s, (status, tools, last) in res.items():
        print(f"{s} {status} tool calls: {tools}")
        if status == "HELD":
            print("  reply tail:", last[-1200:].replace("\n", "\n    "))
    return 0 if settled else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--work", default=None, help="state dir (default: <claude config dir>/session-recovery)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("inventory", help="list offline background sessions and join them to their VM jobs")
    s.add_argument("--sessions", nargs="*", default=None, metavar="FILE",
                   help="session list pages (raw tool result text or bare JSON). Optional: without it, "
                        "list local jobs that have no live process")
    s.set_defaults(fn=cmd_inventory)

    s = sub.add_parser("queue-check", help="flag sessions with a remote update later than the idle-retirement gap")
    s.add_argument("short", nargs="*", help="short ids (default: all)")
    s.set_defaults(fn=cmd_queue_check)

    s = sub.add_parser("resume", help="resume offline VM sessions with the review prompt")
    s.add_argument("short", nargs="+")
    s.add_argument("--dupes", metavar="FILE", help="JSON map short -> duplicate-group text")
    s.add_argument("--nudge", action="store_true", help="send the short follow-up instead of the full prompt")
    s.add_argument("--default-cwd", default="~", metavar="DIR",
                   help="cwd for a job that has none saved (default: your home folder)")
    s.set_defaults(fn=cmd_resume)

    s = sub.add_parser("read", help="print each session's reply to the review prompt")
    s.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="poll every 30 s up to this long")
    s.add_argument("short", nargs="+")
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("last-reply", help="print assistant text after the last entry containing MARK")
    s.add_argument("mark")
    s.add_argument("short", nargs="+")
    s.set_defaults(fn=cmd_last_reply)

    s = sub.add_parser("wrap-wait", help="wait for each session's wrap reply: DONE, HELD, or still RUNNING")
    s.add_argument("--mark", required=True, help="text in the message that asked for the wrap")
    s.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="poll every 30 s up to this long")
    s.add_argument("short", nargs="+")
    s.set_defaults(fn=cmd_wrap_wait)

    a = p.parse_args(argv)
    a.work = a.work or default_work()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
