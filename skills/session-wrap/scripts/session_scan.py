#!/usr/bin/env python3
"""session_scan.py - deterministic deep-scan core for session-wrap done mode.

Stdlib only (no third-party dependencies).

Given the current worktree identity, this resolves THIS session, stitches its
sibling windows on the same worktree at span level, filters injected/non-genuine
content, and emits a compact evidence digest plus a DEEP_CANDIDATES verdict. It
never loads a whole transcript into a caller's context; it streams and prints a
bounded digest.

The bash wrapper (session-scan.sh) resolves git/worktree facts and passes them in;
this core is pure and testable. Run `--self-test` for the positive + per-vector
negative controls.

"""

from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import os
import re
import sys
import tempfile

# --- signal patterns -------------------------------------------------------

# Explicit directives fire at n=1, matched on USER-role genuine turns only.
# Conservative set: favour precision over recall (tune against sample transcripts).
DIRECTIVE_PATTERNS = [
    r"from now on",
    r"going forward",
    r"next time\b",
    r"update the skill",
    r"add (?:this |it )?to the (?:[\w-]+ )?skill",
    # Named-skill asks: "put in the report skill ...",
    # "check your tracker skill for ... and update as necessary".
    r"put (?:it |this |that )?in(?:to)? (?:the |your |our )?(?:[\w-]+ )?skill",
    r"(?:check|update|fix|change) (?:the |your |our )?[\w-]+ skill\b",
    r"update (?:it |them |that )?as (?:necessary|needed)",
    # "Make that part of the instructions in the future",
    # "do all of the updates from here to the skill", "put a pointer in the team skill".
    r"make (?:that|this|it) part of (?:the |your |our )?(?:instructions|skill|process|workflow)",
    r"(?:do|apply|make) (?:all )?(?:of )?the updates\b.{0,40}?\bto the (?:[\w-]+ )?skill",
    r"put a pointer in(?:to)? (?:the |your |our )?(?:[\w.-]+ )?skill",
    r"why (?:isn't|isnt|is not) this (?:in )?a skill",
    r"this should be a skill",
    r"make (?:this|it) a (?:skill|hook)",
    r"should (?:be )?a hook",
    r"(?:should|could) (?:be )?automat(?:e|ed)",
    r"always (?:make sure|remember|use|run|include|check|do)",
    r"never (?:again|use|do|run|forget|commit|push)",
    r"remember to\b",
    # Scope-rejection pushback ("I don't know why you're doing a nightly sweep.
    # I didn't ask for that"). Word-bounded; genuine user turns only.
    # Apostrophes accept both ' and the iPhone curly U+2019.
    r"\bi (?:didn['’]?t|did not|never) ask(?:ed)? for\b",
    r"\bwhy (?:are|were) you (?:doing|adding|building|making|running)\b",
    # Rejection continuations only; "I don't know why you need/get ..." is a plain question.
    r"\bi don['’]?t know why you(?:['’]re| are| were)? "
    r"(?:doing|adding|building|making|running|changing|creating|setting up)\b",
    r"\bwho asked (?:you )?for\b",
    r"\bthat['’]?s not what i (?:asked|wanted)\b",
    r"\bnot what i (?:asked for|wanted)\b",
    # Typed while a turn was running, for example: "Why didn't you follow the format?
    # You're supposed to put the link inline."
    # The user states the rule the agent broke, or asks why it was skipped.
    # The "supposed to" form needs an action verb, so "you're supposed to get an email" is
    # not flagged.
    r"\byou(?:['’]re| are| were) (?:supposed|meant|required) to "
    r"(?:put|use|post|run|check|include|add|read|ask|follow|send|update|make|call|verify|link|attach|"
    r"do|create|write|save|open|start|show|give|tell|keep|set|log|record|reply|answer)\b",
    r"\bwhy (?:didn['’]?t|did not) you\b",
    # Indirect form only as a request ("tell me why you didn't ..."); a bare "why you
    # didn't" is often an explanation ("that's why you didn't see it"), not a correction.
    # A request needs "tell/show me" or a polite lead before "explain" ("thanks for
    # explaining why you didn't ..." and "let me explain why you didn't ..." are not asks).
    r"\b(?:(?:tell|show) me|(?:please|can you|could you|would you)(?: (?:just|kindly|also|now))? explain) "
    r"why you (?:didn['’]?t|did not)\b",
    # Each is anchored on a verb phrase that states a standing change, so chatter like
    # "turn the heat into a skillet" (skill\b rejects skillet) or "let's focus on
    # tidying five files at a time" stays quiet.
    r"\b(?:turn|convert|make) [\w' -]{1,60}? into an? (?:[\w-]+ )?skill\b",
    r"\b(?:they|you) should (?:actually |really |literally )?(?:run|use|do|follow)\b",
    r"\bi meant\b.{0,80}?\b(?:run|use|do|not just)\b",
    r"\bi(?:['’]d| would) prefer (?:you |just )",
    r"\bplease (?:raise|lower|change|set) the\b",
]
DIRECTIVE_RE = re.compile("|".join(f"(?:{p})" for p in DIRECTIVE_PATTERNS), re.I)

# Inferred correction/redo signals (user turns); need n>=2 to promote.
CORRECTION_RE = re.compile(
    r"^\s*(?:no[,.]|nope\b|that'?s wrong|that is wrong|not what i|"
    r"you were supposed to|i (?:told|asked) you|actually[,]|undo\b|revert\b|"
    r"redo\b|did you (?:check|read|verify|test)|are you sure)",
    re.I,
)

# Injected regions the harness embeds in user-role records. We STRIP these spans from
# the text before matching, so a directive that sits before/after an injected block is
# still seen, and an injected phrase inside a genuine turn is never matched. Paired
# XML-ish tags are removed wholesale (DOTALL, non-greedy); a stray opening tag with no
# close is removed to end of string.
INJECTION_SPAN_TAGS = (
    "system-reminder", "task-notification", "cross-session-message",
    "command-name", "command-message", "command-args",
    "local-command-stdout", "local-command-stderr",
)
_paired = "|".join(re.escape(t) for t in INJECTION_SPAN_TAGS)
# `[^<>]*` (not `[^>]*`) bounds the opening tag so a malformed tag missing its `>` cannot
# rescan the whole suffix - that gave quadratic runtime on `<system-reminder`xN input.
INJECTION_SPAN_RE = re.compile(
    rf"<({_paired})\b[^<>]*>.*?</\1>|<({_paired})\b[^<>]*>.*",
    re.I | re.S,
)

# After span-stripping, a block whose head still starts with one of these is a whole
# injected/non-authored block (no closing tag) - drop it entirely.
WHOLE_INJECTION_PREFIXES = (
    "caveat: the messages below were generated by the user while running",
    "[heartbeat",
    "[system notification",
    "[request interrupted",
    "this session is being continued from a previous",  # compaction preamble
    "# agents.md",
    "# claude.md",
)

# --- record helpers --------------------------------------------------------


def slugify(path: str) -> str:
    """Every '/' and every '.' in the absolute path becomes '-'."""
    return re.sub(r"[/.]", "-", path)


def iter_records(path: str):
    """Yield (lineno, obj) for each valid JSON line; skip malformed lines.

    A human queued prompt is yielded as a user record (normalize_queued_turn). When
    the same prompt is later delivered as a normal user record, that delivery is
    skipped, so one message never counts twice (the usual Claude Code
    transcript dedupe rule). A queued prompt with no later delivery is still counted.
    """
    pending = collections.Counter()
    try:
        with open(path, "r", errors="replace") as fh:
            for i, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, json.JSONDecodeError):
                    continue
                rec = normalize_queued_turn(obj)
                if isinstance(rec, dict) and rec.get("queuedCommand"):
                    key = _user_text_key(rec)
                    if key:
                        pending[key] += 1
                elif pending and isinstance(rec, dict) and rec.get("type") == "user":
                    key = _user_text_key(rec)
                    if key and pending[key] > 0:
                        pending[key] -= 1
                        rec = _drop_text_blocks(rec)
                        if rec is None:
                            continue
                yield i, rec
    except (OSError, IOError):
        return


def _drop_text_blocks(obj: dict):
    """The delivered copy of a queued prompt, with only its text removed. Non-text
    blocks (tool_result, images) stay, so a tool error bundled with the delivery is
    still counted. Returns None when nothing but text was in it."""
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return None
    rest = [b for b in content if not (isinstance(b, dict) and b.get("type") == "text")]
    if not rest:
        return None
    rec = dict(obj)
    rec["message"] = dict(msg, content=rest)
    return rec


def _user_text_key(obj: dict) -> str:
    """The joined, stripped text of a user record (text blocks only), for matching a
    queued prompt to its later delivery."""
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n\n".join(b.get("text", "") for b in content
                           if isinstance(b, dict) and b.get("type") == "text"
                           and isinstance(b.get("text"), str)).strip()
    return ""


def normalize_queued_turn(obj):
    """A message the user sends while the agent is mid-turn is stored as an attachment
    record (`attachment.type == "queued_command"`), not a `type: user` record, so every
    user-turn check dropped it (for example "Make that part of the instructions in
    the future" was missed). Rewrite a HUMAN queued prompt as a plain user record; leave
    everything else (task notifications, non-human origins) untouched."""
    if not isinstance(obj, dict) or obj.get("type") != "attachment":
        return obj
    att = obj.get("attachment")
    if not isinstance(att, dict) or att.get("type") != "queued_command":
        return obj
    if att.get("commandMode") != "prompt":
        return obj
    origin = att.get("origin")
    human = (isinstance(origin, dict) and origin.get("kind") == "human") or att.get("humanTurn") is True
    prompt = att.get("prompt")
    if not human or not isinstance(prompt, (str, list)):
        return obj
    rec = {k: v for k, v in obj.items() if k != "attachment"}
    rec["type"] = "user"
    rec["message"] = {"role": "user", "content": prompt}
    rec["queuedCommand"] = True
    return rec


def record_role(obj: dict) -> str:
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("role"), str):
        return msg["role"]
    t = obj.get("type")
    return t if isinstance(t, str) else ""


def record_cwd(obj: dict):
    """The cwd this record ran under - a worktree-state's worktreePath wins, else the
    per-record cwd. Used to filter to spans that belong to THIS worktree."""
    ws = obj.get("worktreeSession")
    if isinstance(ws, dict):
        wp = ws.get("worktreePath")
        if isinstance(wp, str) and wp:
            return wp
    c = obj.get("cwd")
    if isinstance(c, str) and c:
        return c
    return None


def is_non_genuine(obj: dict) -> bool:
    """True for records we must never treat as user/assistant authored turns."""
    if obj.get("isMeta") is True:
        return True
    if obj.get("isCompactSummary") is True:
        return True
    if obj.get("isSidechain") is True:
        return True
    t = obj.get("type")
    if t not in ("user", "assistant"):
        return True
    return False


def text_blocks(obj: dict):
    """Yield plain-text strings from a record's message.content.

    Handles content as a bare string OR a list of blocks. Only 'text' blocks are
    returned - tool_use / tool_result / thinking blocks are skipped (directive
    matching must never see tool payloads or injected tool output).
    """
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return
    content = msg.get("content")
    if isinstance(content, str):
        yield content
        return
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                txt = block.get("text")
                if isinstance(txt, str):
                    yield txt


def tool_error_strings(obj: dict):
    """Yield normalized error text from is_error tool_result blocks (user records)."""
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return
    content = msg.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        if not block.get("is_error"):
            continue
        c = block.get("content")
        if isinstance(c, str):
            yield _norm_err(c)
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and isinstance(b.get("text"), str):
                    yield _norm_err(b["text"])


# Tool errors that are harness noise, not friction worth a lesson: worktree-isolation
# guard refusals and MCP re-auth prompts (in practice most INFERRED "repeated tool
# error" lines were these). Matched on the normalized (lower-case) text.
NOISE_ERROR_MARKERS = (
    "this session is isolated in the worktree",
    "needs you to sign in again",
    "run /mcp to re-authenticate",
)


def is_noise_error(norm: str) -> bool:
    return any(m in norm for m in NOISE_ERROR_MARKERS)


def _norm_err(s: str) -> str:
    # Collapse whitespace + drop digits/paths so identical errors group.
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = re.sub(r"0x[0-9a-f]+|\b\d+\b", "N", s)
    return s[:200]


def strip_injected(txt: str) -> str:
    """Remove injected regions and return the authored remainder ('' if none).

    Strips paired/stray injected XML spans, then drops the block entirely if what is
    left is itself a whole injected/non-authored block (heartbeat, caveat/compaction
    preamble, an AGENTS.md/CLAUDE.md dump). Also drops a block that is enclosed in an
    AGENTS/CLAUDE 'Contents of ... .md' injection preamble.
    """
    cleaned = INJECTION_SPAN_RE.sub(" ", txt)
    head = cleaned.lstrip()[:160].lower()
    if any(head.startswith(p) for p in WHOLE_INJECTION_PREFIXES):
        return ""
    if head.startswith("contents of ") and (".md" in head):
        return ""
    return cleaned


def short(txt: str, n: int = 160) -> str:
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt if len(txt) <= n else txt[: n - 1] + "…"


# --- discovery -------------------------------------------------------------


def read_sessions(sessions_dir: str):
    out = []
    for p in glob.glob(os.path.join(sessions_dir, "*.json")):
        try:
            with open(p) as fh:
                obj = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(obj, dict) and obj.get("sessionId") and obj.get("cwd"):
            out.append(obj)
    return out


def _pid_live(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        # No such process, or a process we cannot signal (another user's). For SEED
        # selection we want OUR own live session, so treat both as not-live.
        return False
    except OSError:
        return False


def resolve_seed_session(wt_path: str, sessions_dir: str) -> str | None:
    """Return the sessionId of THIS worktree's live session, or None."""
    candidates = []
    for s in read_sessions(sessions_dir):
        cwd = s.get("cwd", "")
        if cwd == wt_path or wt_path.startswith(cwd.rstrip("/") + "/") or cwd.startswith(wt_path.rstrip("/") + "/"):
            candidates.append(s)
    # Prefer exact cwd match, then a live pid.
    candidates.sort(key=lambda s: (s.get("cwd") != wt_path, not _pid_live(s.get("pid"))))
    for s in candidates:
        if s.get("cwd") == wt_path and _pid_live(s.get("pid")):
            return s.get("sessionId")
    for s in candidates:
        if _pid_live(s.get("pid")):
            return s.get("sessionId")
    # No live pid: fall back to an exact-cwd match if present (may be this session
    # mid-write before its sessions/ file lists a stable pid).
    for s in candidates:
        if s.get("cwd") == wt_path:
            return s.get("sessionId")
    return None


SUSPECT_BYTES = 200 * 1024
# SCAN-SUSPECT also needs this many typed user turns in the seed transcript. Calibrated
# on a few hundred local transcripts over 200 KB: most of those with 0 evidence had
# fewer than 5 typed turns (autonomous "go" sessions), where 0 evidence is expected.
SUSPECT_MIN_TYPED_TURNS = 5
# A user turn shorter than this ("go", "yes", "ok do it") is an ack, not a typed turn.
TYPED_TURN_MIN_CHARS = 21


def _size_kb(path: str) -> str:
    """File size in KB as text, or "?" when the stat fails (never breaks the digest)."""
    try:
        return str(os.path.getsize(path) // 1024)
    except OSError:
        return "?"


def record_dup_key(obj: dict):
    """Identity of a record that can appear in more than one transcript file of one
    session (a resumed session copies its early records into the new folder's file).
    The uuid when present; else (timestamp, type, hash of the message content). A
    record with neither a uuid nor a timestamp has no safe key, so it is never merged."""
    try:
        uid = obj.get("uuid")
        # Only a non-empty string is a real uuid; a malformed one falls back to the
        # timestamp key, so it can never share a key with a different record.
        if isinstance(uid, str) and uid:
            return ("uuid", uid)
        ts = obj.get("timestamp")
        if ts is None:
            return None
        blob = json.dumps(obj.get("message"), sort_keys=True, default=str)
        return ("ts", json.dumps(ts, sort_keys=True, default=str), str(obj.get("type")),
                hashlib.sha1(blob.encode("utf-8", "replace")).hexdigest())
    except (TypeError, ValueError, RecursionError):
        # Odd field types must not lose the whole digest: no key means never merged.
        return None


def count_typed_turns(paths) -> int:
    """Genuine user turns whose authored text is longer than an ack, over the whole
    file(s). Given several files, a record seen in more than one counts once."""
    if isinstance(paths, str):
        paths = [paths]
    n = 0
    first_file = {}            # key -> file that held it first
    for path in paths:
        for _ln, obj in iter_records(path):
            if is_non_genuine(obj) or record_role(obj) != "user":
                continue
            if len(paths) > 1:
                key = record_dup_key(obj)
                if key is not None:
                    # Repeats inside one file keep counting; only a copy in a
                    # DIFFERENT file is a duplicate.
                    if first_file.setdefault(key, path) != path:
                        continue
            authored = " ".join(strip_injected(t) for t in text_blocks(obj)).strip()
            if len(authored) >= TYPED_TURN_MIN_CHARS:
                n += 1
    return n


WEAK_MIN_CHARS = 61
WEAK_MAX_LINES = 10


def weak_typed_turns(paths):
    """Up to WEAK_MAX_LINES typed human turns over 60 chars as (file, line, first 120
    chars), for the deep pass to read when no directive pattern matched."""
    out = []
    for path in paths:
        for ln, obj in iter_records(path):
            if is_non_genuine(obj) or record_role(obj) != "user":
                continue
            authored = " ".join(strip_injected(t) for t in text_blocks(obj)).strip()
            if len(authored) >= WEAK_MIN_CHARS:
                out.append((path, ln, " ".join(authored.split())[:120]))
                if len(out) >= WEAK_MAX_LINES:
                    return out
    return out


def find_session_files(projects_dir: str, session_id: str | None) -> list[str]:
    """Find EVERY <session id>.jsonl in any folder under projects_dir, oldest first. A
    session launched in one folder that enters and exits worktrees keeps writing to the
    LAUNCH folder's slug dir, so a cwd-derived slug can point at an empty folder. A
    session that resumed in another worktree has the file in TWO folders: the old one
    holds the early part, the new one a copy of it plus the resumed part. Returns []
    when the id is empty, unsafe, or no file matches."""
    sid = (session_id or "").strip()
    if not sid or "/" in sid or "\\" in sid or sid.startswith("."):
        return []
    hits = [p for p in glob.glob(os.path.join(glob.escape(projects_dir), "*", f"{glob.escape(sid)}.jsonl"))
            if os.path.isfile(p)]
    return sorted(hits, key=lambda p: (os.path.getmtime(p), p))


def candidate_dirs(projects_dir: str, wt_path: str, main_path: str, parent_path: str):
    seen, out = set(), []
    for p in (wt_path, main_path, parent_path):
        if not p:
            continue
        d = os.path.join(projects_dir, slugify(p))
        if d not in seen and os.path.isdir(d):
            seen.add(d)
            out.append(d)
    return out


def file_matches_identity(path: str, wt_path: str, wt_branch: str, seed_id: str | None) -> bool:
    """Cheap whole-file substring scan. Endpoints never REJECT - we scan the whole
    text, so a mid-file match is caught. Identity = the worktree path (always) or
    the branch (only when non-empty; a bare branch like 'main' is too broad, so we
    require the path unless the branch is a specific non-default token)."""
    base = os.path.basename(path)
    if seed_id and base == f"{seed_id}.jsonl":
        return True
    # Scan raw BYTES, not decoded text: a full UTF-8 decode of a multi-GB corpus is
    # the dominant cost, and a byte-substring search (memchr) needs no decode. We must
    # read the whole file (identity can sit mid-file), so keep this pass cheap.
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except (OSError, IOError):
        return False
    if wt_path and wt_path.encode("utf-8", "replace") in data:
        return True
    # Only trust the branch when it is worktree-specific (not the default branch).
    if wt_branch and wt_branch not in ("main", "master", "trunk") \
            and wt_branch.encode("utf-8", "replace") in data:
        return True
    return False


def within_recency(path: str, cutoff_mtime: float) -> bool:
    try:
        return os.path.getmtime(path) >= cutoff_mtime
    except OSError:
        return False


# --- main scan -------------------------------------------------------------


def scan(wt_path, wt_branch, projects_dir, sessions_dir, main_path, parent_path,
         recency_days, cap, now, env_session_id=None):
    notes = []
    # Seed transcript by session id (CLAUDE_CODE_SESSION_ID), searched across every
    # project folder, BEFORE any cwd-based guessing. Fallback is the old behaviour.
    env_files = []
    if env_session_id and env_session_id.strip():
        env_files = find_session_files(projects_dir, env_session_id)
        if not env_files:
            notes.append(f"CLAUDE_CODE_SESSION_ID ({env_session_id.strip()[:8]}) matched no "
                         "transcript file; falling back to path-based discovery")
        elif len(env_files) > 1:
            listing = ", ".join(f"{f} ({_size_kb(f)} KB)" for f in env_files)
            notes.append(f"session {env_session_id.strip()} has {len(env_files)} transcript "
                         f"files: {listing}")
    # Not in a git work tree (empty path): there is no path identity, so only the
    # session-id transcript can be scanned (a wrap from a non-repo cwd
    # would otherwise skip the scan although the session id finds the transcript).
    if not wt_path:
        if not env_files:
            return _emit(notes + ["not in a git work tree; deep scan skipped"], [], False, [])
        notes.append("not in a git work tree: scanning only this session's transcripts (by session id)")
    seed_id = resolve_seed_session(wt_path, sessions_dir) if wt_path else None
    if wt_branch == "" and wt_path:
        notes.append("detached HEAD (empty branch): matching on path + session id only")

    # Session-id mode reads no folder: an empty path has no identity to match on.
    dirs = candidate_dirs(projects_dir, wt_path, main_path, parent_path) if wt_path else []
    if not dirs and wt_path:
        notes.append("no candidate transcript dirs found")

    cutoff = now - recency_days * 86400
    narrowed = []
    for d in dirs:
        for path in glob.glob(os.path.join(d, "*.jsonl")):
            if within_recency(path, cutoff):
                narrowed.append(path)

    included = list(env_files)
    # In a main checkout (not a linked worktree) the path is in nearly every transcript that
    # ever ran there, so it identifies nothing: with a resolved session id, scan only that
    # transcript. In a linked worktree, sibling windows on the same worktree still stitch in.
    in_main_checkout = bool(main_path) and \
        os.path.realpath(wt_path or ".") == os.path.realpath(main_path)
    if env_files and in_main_checkout:
        notes.append("main checkout: scanning only this session's transcripts (by session id)")
    else:
        for path in narrowed:
            if file_matches_identity(path, wt_path, wt_branch, seed_id):
                included.append(path)

    if not included:
        # Fallback: prefer the seed session file by name across the dirs.
        seed_path = None
        if seed_id:
            for d in dirs:
                cand = os.path.join(d, f"{seed_id}.jsonl")
                if os.path.isfile(cand):
                    seed_path = cand
                    break
        if seed_path:
            included = [seed_path]
            notes.append(f"fallback: resolved current file by seed sessionId ({seed_id[:8]})")
        else:
            # Only accept the newest file if its identity confirms; else unresolved.
            newest = max(narrowed, key=lambda p: os.path.getmtime(p), default=None)
            if newest and file_matches_identity(newest, wt_path, wt_branch, seed_id):
                included = [newest]
                notes.append("fallback: newest identity-confirmed file")
            else:
                notes.append("UNRESOLVED session identity: no file confirms this worktree; "
                             "refusing to scan an unrelated newest transcript")
                return _emit(notes, [], False, [])

    # Dedupe physical aliases by realpath.
    by_real = {}
    for p in included:
        by_real.setdefault(os.path.realpath(p), p)
    included = list(by_real.values())

    # Union records by message uuid across (resumed) files, keeping provenance. Count
    # signals ONLY from records whose active cwd is THIS worktree (span-level, not
    # whole-file), and per distinct turn/record (never per text block).
    seen_keys = {}             # record_dup_key -> path where first seen
    directives = []            # (file, line, role, quote)
    corrections = 0
    corr_loc = None            # (file, line) of first correction
    error_counts = {}          # normalized error -> count
    error_loc = {}             # normalized error -> (file, line) of first occurrence
    genuine_turns = 0
    compaction_seen = False
    compaction_loc = None      # (file, line) of first IN-SPAN compaction marker
    spans = []                 # included files that actually contributed in-span records

    for path in included:
        active_cwd = None
        contributed = False
        for lineno, obj in iter_records(path):
            # Update the active span BEFORE any skip, so a skipped duplicate does not
            # break cwd continuity for a resumed file's unique tail.
            cw = record_cwd(obj)
            if cw is not None:
                active_cwd = cw
            key = record_dup_key(obj)
            if key is not None:
                # A uuid match is a duplicate anywhere (existing rule). The timestamp key
                # is weaker, so it only merges records across DIFFERENT files.
                first = seen_keys.get(key)
                if first is not None and (key[0] == "uuid" or first != path):
                    continue
                seen_keys.setdefault(key, path)
            # The session-id transcript is this session end to end, whatever cwd a record
            # carries (it may have entered and left worktrees); other files stay cwd-filtered.
            in_span = (active_cwd == wt_path) or (path in env_files)
            if not in_span:
                continue
            # Compaction is a signal only when it belongs to THIS span. Record its
            # location and mark the file as contributing so the deep pass gets a SPAN
            # to read even when there are no authored turns.
            if obj.get("isCompactSummary") is True:
                compaction_seen = True
                contributed = True
                if compaction_loc is None:
                    compaction_loc = (path, lineno)
                continue
            # Exclude non-genuine records from ALL counting (incl. tool errors).
            if is_non_genuine(obj):
                continue
            role = record_role(obj)
            if role not in ("user", "assistant"):
                continue
            contributed = True
            # Repeated tool errors: count each distinct normalized error once per record.
            for err in set(e for e in tool_error_strings(obj) if e and not is_noise_error(e)):
                error_counts[err] = error_counts.get(err, 0) + 1
                error_loc.setdefault(err, (path, lineno))
            if role != "user":
                continue
            # Per-turn (per-record) signals, computed over the AUTHORED text only.
            authored = [c for c in (strip_injected(t) for t in text_blocks(obj)) if c.strip()]
            if not authored:
                continue
            genuine_turns += 1
            joined = "\n".join(authored)
            hit = next((c for c in authored if DIRECTIVE_RE.search(c)), None)
            if hit is not None:
                directives.append((path, lineno, role, short(hit)))
            if CORRECTION_RE.search(joined) or any(CORRECTION_RE.search(c) for c in authored):
                corrections += 1
                if corr_loc is None:
                    corr_loc = (path, lineno)
        if contributed:
            spans.append(os.path.realpath(path))

    # Assemble evidence (directives first, then repeated signals with locations).
    evidence = list(directives)
    inferred = []              # (text, file, line)
    if corrections >= 2 and corr_loc:
        inferred.append((f"repeated correction/redo turns x{corrections}", corr_loc[0], corr_loc[1]))
    for err, c in sorted(error_counts.items(), key=lambda kv: -kv[1]):
        if c >= 2:
            f, ln = error_loc.get(err, ("", 0))
            inferred.append((f"repeated tool error x{c}: {short(err, 100)}", f, ln))

    deep = bool(directives) or bool(inferred) or compaction_seen or genuine_turns > 400
    weak = []
    # Silence on a big transcript is suspect: it may be the wrong file or a wrong path.
    seed_files = list(env_files)
    if not seed_files and seed_id:
        for d in dirs:
            cand = os.path.join(d, f"{seed_id}.jsonl")
            if os.path.isfile(cand):
                seed_files = [cand]
                break
    if not evidence and seed_files:
        # Per-transcript gate: a copied history must not trip the warning by itself.
        size = 0
        for sf in seed_files:
            try:
                size = max(size, os.path.getsize(sf))
            except OSError:
                pass
        if size > SUSPECT_BYTES:
            typed = count_typed_turns(seed_files)
            if typed >= SUSPECT_MIN_TYPED_TURNS:
                if env_files or seed_id:
                    # The seed was resolved by session id, so the path is right: no
                    # pattern matched. Point the deep pass at the typed turns instead.
                    notes.append(f"0 directives matched {typed} typed user turns; review the "
                                 "typed turns by hand (the transcript path is right)")
                    weak = weak_typed_turns(seed_files)
                else:
                    notes.append(f"SCAN-SUSPECT: 0 evidence on a {size // 1024} KB transcript; "
                                 "check the transcript path")
            else:
                notes.append(f"0 evidence is expected: only {typed} typed user turns in the seed "
                             f"transcript (SCAN-SUSPECT needs {SUSPECT_MIN_TYPED_TURNS}+)")
    if compaction_seen:
        loc = f" at {compaction_loc[0]}:{compaction_loc[1]}" if compaction_loc else ""
        notes.append(f"compaction marker present (long/compacted session){loc}")

    return _emit(notes, evidence[:cap], deep, inferred[:cap], spans, weak)


def _emit(notes, evidence, deep, inferred, spans=None, weak=None):
    lines = []
    for n in notes:
        lines.append(f"NOTE {n}")
    for sp in (spans or []):
        if os.path.isfile(sp):      # never print a SPAN for a file that does not exist
            lines.append(f"SPAN {sp}")
    for (f, ln, role, quote) in evidence:
        lines.append(f"EVIDENCE {f}:{ln} | {role} | directive | {quote}")
    for item in inferred:
        if isinstance(item, tuple):
            text, f, ln = item
            loc = f"{f}:{ln}" if f else "(no single location)"
            lines.append(f"INFERRED {loc} | {text}")
        else:
            lines.append(f"INFERRED {item}")
    for (f, ln, quote) in (weak or []):
        lines.append(f"WEAK {f}:{ln} | {quote}")
    lines.append(f"DEEP_CANDIDATES={1 if deep else 0}")
    lines.append(f"EVIDENCE_COUNT={len(evidence)}")
    return "\n".join(lines), deep


# --- self-test -------------------------------------------------------------


def _mk(msgs):
    """Serialize a list of record dicts to JSONL text."""
    return "\n".join(json.dumps(m) for m in msgs) + "\n"


def _u(role, text, cwd=None, **extra):
    rec = {"type": role, "uuid": extra.pop("uuid", os.urandom(6).hex()),
           "message": {"role": role, "content": [{"type": "text", "text": text}]}}
    if cwd is not None:
        rec["cwd"] = cwd
    rec.update(extra)
    return rec


def _terr(text, cwd=None, **extra):
    """A user-type record carrying an is_error tool_result block."""
    rec = {"type": "user", "uuid": extra.pop("uuid", os.urandom(6).hex()),
           "message": {"role": "user", "content": [
               {"type": "tool_result", "is_error": True, "content": text}]}}
    if cwd is not None:
        rec["cwd"] = cwd
    rec.update(extra)
    return rec


def self_test() -> int:
    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        wt = "/tmp/wsX/.claude/worktrees/deep-scan-fixture"
        other = "/tmp/wsX/.claude/worktrees/other-effort"
        br = "wt/deep-scan-fixture"
        projects = os.path.join(tmp, "projects")
        sessions = os.path.join(tmp, "sessions")
        os.makedirs(projects)
        os.makedirs(sessions)
        wt_dir = os.path.join(projects, slugify(wt))
        os.makedirs(wt_dir)
        now = 1_000_000_000.0

        def seed_on():
            with open(os.path.join(sessions, "self.json"), "w") as fh:
                json.dump({"pid": os.getpid(), "sessionId": "SEED", "cwd": wt}, fh)

        def seed_off():
            p = os.path.join(sessions, "self.json")
            if os.path.exists(p):
                os.remove(p)

        def write(name, records, mtime=now):
            p = os.path.join(wt_dir, name)
            with open(p, "w") as fh:
                fh.write(_mk(records))
            os.utime(p, (mtime, mtime))
            return p

        def clear():
            for f in glob.glob(os.path.join(wt_dir, "*.jsonl")):
                os.remove(f)

        seed_on()

        # 1) positive: a genuine in-span user directive.
        write("SEED.jsonl", [
            _u("user", "Please, from now on always run the smoke test before deploy.", cwd=wt),
            _u("assistant", "Understood.", cwd=wt),
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("positive_directive_flagged", "| directive |" in out and deep)
        check("positive_span_manifest", "SPAN " in out)

        # 1b) skill-capture phrasings with a skill name between "the" and "skill".
        for phrase in (
            "Yeah, put in the report skill that totals go in the summary row "
            "Don't round the subtotals.",
            "add this to the report-update skill",
            "put this in the skill",
            "put it into the report-update skill",
        ):
            check("directive_phrase:" + phrase[:30], DIRECTIVE_RE.search(phrase) is not None)
        check("directive_put_in_unrelated_not_flagged",
              DIRECTIVE_RE.search("put the file in the folder, then run the skill") is None)

        # 1c) further skill-capture phrasings, and an unrelated "updates" line.
        for phrase in (
            "And can you use better screenshots in the examples please? Make that part of "
            "the instructions in the future",
            "Could you do all of the updates from here to the skill please?",
            "go and you can put a pointer in the shared skill that there's a local skill",
        ):
            check("directive_phrase_1c:" + phrase[:30], DIRECTIVE_RE.search(phrase) is not None)
        check("directive_updates_unrelated_not_flagged",
              DIRECTIVE_RE.search("the updates to the dashboard are live") is None)

        # 1c2) scope-rejection pushback ("I didn't ask for that").
        clear()
        write("SEED.jsonl", [
            _u("user", "I don't know why you're doing a nightly sweep. I didn't ask for that", cwd=wt),
            _u("assistant", "Removing it.", cwd=wt),
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("pushback_scope_rejection_flagged",
              "| directive |" in out and "nightly sweep" in out and deep)
        check("pushback_scope_rejection_count", "DEEP_CANDIDATES=1" in out)
        for phrase in (
            "I did not ask for this",
            "I never asked for a report",
            "Why are you doing that?",
            "who asked for this change",
            "That's not what I asked",
            "this is not what I wanted",
            "I don't know why you're doing that",
            "I don’t know why you’re adding a sweep",
            "I don't know why you are setting up a cron",
        ):
            check("pushback_phrase:" + phrase[:30], DIRECTIVE_RE.search(phrase) is not None)
        clear()
        write("SEED.jsonl", [
            _u("user", "I didn’t ask for that", cwd=wt),
            _u("assistant", "Removing it.", cwd=wt),
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("pushback_curly_apostrophe_flagged", "| directive |" in out and deep)
        check("pushback_curly_regex", all(DIRECTIVE_RE.search(p) for p in (
            "I didn’t ask for that", "I don’t know why you’re doing a sweep",
            "That’s not what I asked")))
        clear()
        write("SEED.jsonl", [
            _u("user", "I asked for a summary earlier, thanks", cwd=wt),
            _u("assistant", "Here it is.", cwd=wt),
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("pushback_near_miss_not_flagged", "| directive |" not in out and not deep)
        for phrase in ("I don't know why you need this setting",
                       "I don't know why you get that error",
                       "I don’t know why you get that error"):
            check("pushback_question_not_flagged:" + phrase[:34],
                  DIRECTIVE_RE.search(phrase) is None)
        check("pushback_near_miss_regex",
              DIRECTIVE_RE.search("I asked for a summary earlier, thanks") is None)

        # 1d) a HUMAN message queued mid-turn (attachment record) counts as a user turn;
        # a queued task notification does not.
        def _queued(prompt, mode="prompt", kind="human"):
            return {"type": "attachment", "cwd": wt, "isSidechain": False,
                    "attachment": {"type": "queued_command", "prompt": prompt,
                                   "commandMode": mode, "origin": {"kind": kind},
                                   "humanTurn": kind == "human"}}
        clear()
        write("SEED.jsonl", [_u("assistant", "Working.", cwd=wt),
                             _queued("Make that part of the instructions in the future")])
        out, deep = _run(wt, br, projects, sessions, now)
        check("queued_human_turn_flagged", "| directive |" in out and deep)
        clear()
        write("SEED.jsonl", [_u("assistant", "Working.", cwd=wt),
                             _queued("from now on always X", mode="task-notification", kind="task")])
        out, deep = _run(wt, br, projects, sessions, now)
        check("queued_task_notification_not_flagged", "| directive |" not in out)

        # 1e) a queued prompt that is ALSO delivered later as a user record counts once:
        # one queued correction must not reach the corrections >= 2 bar on its own.
        clear()
        write("SEED.jsonl", [_u("assistant", "Working.", cwd=wt),
                             _queued("No, that's wrong"),
                             _u("user", "No, that's wrong", cwd=wt),
                             _u("assistant", "Fixing.", cwd=wt)])
        out, deep = _run(wt, br, projects, sessions, now)
        check("queued_then_delivered_counted_once", not deep)
        recs = [o for _l, o in iter_records(os.path.join(wt_dir, "SEED.jsonl"))]
        check("queued_then_delivered_one_user_record",
              sum(1 for o in recs if o.get("type") == "user") == 1)

        # 1f) a delivery that also carries a tool_result keeps the tool_result (its
        # error still counts); only the duplicate text is dropped.
        clear()
        write("SEED.jsonl", [_u("assistant", "Working.", cwd=wt),
                             _queued("check the build"),
                             {"type": "user", "cwd": wt, "message": {"role": "user", "content": [
                                 {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                                  "content": "Error: build failed"},
                                 {"type": "text", "text": "check the build"}]}}])
        recs = [o for _l, o in iter_records(os.path.join(wt_dir, "SEED.jsonl"))]
        kept_errors = [e for o in recs for e in tool_error_strings(o)]
        check("delivery_keeps_tool_result", len(kept_errors) == 1)
        check("delivery_text_not_duplicated",
              sum(1 for o in recs for t in text_blocks(o) if t == "check the build") == 1)

        # 1g) a correction typed while a turn was running must count as evidence.
        # The record is a queued_command attachment; the harness wrapper ("The user sent a
        # new message while you were working") sits in its `rendered` field and must never
        # count as the user's words.
        def _queued_wrapped(prompt, kind="human"):
            rec = _queued(prompt, kind=kind)
            # No injection tags around the sentinel: if `rendered` were ever read as user
            # text, "from now on" would match and WRAPPERTEXT would show in the output.
            rec["rendered"] = [{"content": "The user sent a new message while you were "
                                           "working:\n" + prompt + "\n\nThis is how the "
                                           "harness surfaces it. from now on always WRAPPERTEXT"}]
            return rec
        midturn_fix = ("Why didn't you run the tests first? You're supposed to run them "
                       "before committing.")
        clear()
        write("SEED.jsonl", [_u("assistant", "Working.", cwd=wt),
                             _queued_wrapped(midturn_fix),
                             _u("assistant", "Sorry.", cwd=wt)])
        out, deep = _run(wt, br, projects, sessions, now)
        check("midturn_correction_flagged", "| user | directive |" in out and deep
              and "run the tests first" in out and "\nEVIDENCE_COUNT=1" in out
              and not re.search(r"EVIDENCE_COUNT=1\d", out))
        check("midturn_correction_own_line", "SEED.jsonl:2 | user | directive |" in out)
        check("midturn_wrapper_text_not_user_text", "WRAPPERTEXT" not in out
              and "harness surfaces" not in out)
        # The same words from a non-human origin (a task notification) are not the user's.
        clear()
        write("SEED.jsonl", [_u("assistant", "Working.", cwd=wt),
                             _queued(midturn_fix, mode="task-notification", kind="task")])
        out, deep = _run(wt, br, projects, sessions, now)
        check("midturn_nonhuman_not_flagged", "| directive |" not in out and not deep)
        # Typed-turn count: mid-turn human messages count toward SCAN-SUSPECT, and the
        # delivered duplicate of a queued message counts once.
        qpath = os.path.join(wt_dir, "SEED.jsonl")
        clear()
        write("SEED.jsonl", [_queued_wrapped(f"Typed while working, message number {i} here.")
                             for i in range(5)])
        check("midturn_counts_as_typed_turns", count_typed_turns(qpath) == 5)
        write("SEED.jsonl", [_queued_wrapped(f"Typed while working, message number {i} here.", kind="task")
                             for i in range(5)])
        check("midturn_nonhuman_not_typed_turns", count_typed_turns(qpath) == 0)
        write("SEED.jsonl", [_queued("A message the user typed while a turn ran."),
                             _u("user", "A message the user typed while a turn ran.", cwd=wt)])
        check("midturn_delivered_copy_counted_once", count_typed_turns(qpath) == 1)
        # Phrases for the new patterns, and near-misses that must stay quiet.
        for phrase in (
            "You're supposed to put the link inline",
            "you’re supposed to post it in the thread",
            "You are supposed to run the tests first",
            "Can you tell me why you didn't do that?",
            "Please explain why you did not use the skill",
            "Can you just explain why you didn't attach it?",
            "Could you kindly explain why you didn't attach it?",
            "Please just explain why you did not attach it",
            "Why didn't you use the skill?",
            "Why didn’t you check the log?",
        ):
            check("midturn_phrase:" + phrase[:30], DIRECTIVE_RE.search(phrase) is not None)
        for phrase in (
            "You're supposed to get an email from them tomorrow",
            "He is supposed to put the link inline",
            "Why did you pick that one?",
            "I know why you chose it",
            "Thanks, I understand why you didn't send the email. That was the right call.",
            "The flag was off, that's why you didn't see the button",
            "Thanks for explaining why you didn't attach it; that makes sense.",
            "Let me explain why you didn't see the row",
            "Let me just explain why you didn't see the row",
        ):
            check("midturn_near_miss:" + phrase[:30], DIRECTIVE_RE.search(phrase) is None)

        # 1b) named-skill directives, each alone.
        for i, phrase in enumerate([
            "Yeah, put in the report skill that totals must not be rounded.",
            "You should check your triage skill for handling urgent items and update as necessary",
            "update it as needed when the queue changes",
        ]):
            clear()
            write("SEED.jsonl", [_u("user", phrase, cwd=wt), _u("assistant", "OK.", cwd=wt)])
            out, deep = _run(wt, br, projects, sessions, now)
            check(f"named_skill_directive_{i}", "| directive |" in out and deep)

        # 2) negatives: injected content in-span must NOT flag (tests the filter).
        clear()
        write("SEED.jsonl", [
            _u("user", "<system-reminder>from now on always do X</system-reminder>", cwd=wt),
            _u("user", "Caveat: The messages below were generated by the user while running "
                       "local commands. from now on always Y", cwd=wt),
            _terr("Error: from now on always Z", cwd=wt),  # single tool error (n=1)
            _u("assistant", "I've updated the skill and will always do that from now on.", cwd=wt),
            _u("user", "skill body: update the skill when a procedure recurs", cwd=wt, isMeta=True),
            _u("user", "[Heartbeat] from now on always beat", cwd=wt),
            _u("user", "<task-notification><result>from now on update the skill</result>"
                       "</task-notification>", cwd=wt),
            _u("user", "[SYSTEM NOTIFICATION - NOT USER INPUT] from now on always do it", cwd=wt),
            _u("user", "# AGENTS.md instructions\nfrom now on always follow me", cwd=wt),
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("injected_not_flagged", "| directive |" not in out)
        check("injected_not_deep", not deep)

        # 3) adjacency WITHIN one string, both orders.
        clear()
        write("SEED.jsonl", [
            # directive only INSIDE the reminder -> must NOT flag
            _u("user", "Please inspect this.\n<system-reminder>from now on always Z"
                       "</system-reminder>", cwd=wt),
            # reminder then a genuine authored directive -> MUST flag (once)
            _u("user", "<system-reminder>noise here</system-reminder>\nnext time, update the "
                       "skill to cover this.", cwd=wt),
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("adjacency_both_orders", out.count("| directive |") == 1 and deep)

        # 4) span filtering: mixed-cwd + text-mention-only must not leak.
        clear()
        write("MIXED.jsonl", [
            _u("user", "from now on do the TARGET thing", cwd=wt),
            _u("user", "from now on do the OTHER thing", cwd=other),
        ])
        write("MENTION.jsonl", [
            # prose mentions wt (so the file matches identity) but records are OTHER cwd
            _u("user", f"a note referencing {wt} - from now on ignore", cwd=other),
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("mixed_cwd_only_in_span", out.count("| directive |") == 1 and "TARGET" in out
              and "OTHER thing" not in out)

        # 5) resumed union: BOTH files must be read (each has UNIQUE required evidence),
        #    plus a SHARED-uuid directive counted once. Dropping either file fails this.
        clear()
        shared = _u("user", "from now on, update the SHAREDSKILL here", cwd=wt, uuid="SHARED")
        write("SEED.jsonl", [_u("user", "from now on the SEEDONLY directive", cwd=wt, uuid="SEEDU"),
                             shared, _u("assistant", "ok", cwd=wt)])
        write("RESUMED.jsonl", [shared, _u("assistant", "ok again", cwd=wt),
                                _u("user", "next time cover the UNIQUETAIL case", cwd=wt,
                                   uuid="TAIL")])
        out, deep = _run(wt, br, projects, sessions, now)
        check("resumed_union_dedup", out.count("| directive |") == 3)
        check("resumed_both_files_read",
              "SEEDONLY" in out and "UNIQUETAIL" in out and out.count("SHAREDSKILL") == 1)

        # 6) per-block / per-turn: one record with many blocks counts once, not N.
        clear()
        many = {"type": "user", "uuid": "many", "cwd": wt, "message": {"role": "user",
                "content": [{"type": "text", "text": "no, that's wrong"} for _ in range(401)]}}
        write("SEED.jsonl", [many])
        out, deep = _run(wt, br, projects, sessions, now)
        check("per_block_not_inflated", not deep)  # 1 correction turn, not 401

        # 7) non-genuine tool errors excluded from recurrence.
        clear()
        write("SEED.jsonl", [
            _terr("boom identical error", cwd=wt, isSidechain=True),
            _terr("boom identical error", cwd=wt, isSidechain=True),
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("nongenuine_errors_excluded", not deep)

        # 8) middle-only inclusion: the ONLY wt reference is a mid-file worktree-state
        #    record; endpoints are OTHER-cwd / no-cwd with no wt bytes. Proves a
        #    whole-file scan (not endpoint sampling) includes it, and the trailing
        #    directive inherits the mid-record span. An endpoint-only discovery fails.
        clear()
        seed_off()
        recs = [_u("user", f"pad {i}", cwd=other) for i in range(30)]
        recs.append({"type": "worktree-state", "uuid": "wsrec",
                     "worktreeSession": {"worktreePath": wt}})   # only wt byte, mid-file
        recs += [_u("user", f"tailpad {i}") for i in range(29)]   # no cwd -> inherit wt span
        recs.append(_u("user", "from now on cover the MIDONLY case"))  # no cwd -> inherit wt
        write("MID.jsonl", recs)
        out, deep = _run(wt, br, projects, sessions, now)
        check("middle_only_selected", deep and "MIDONLY" in out)

        # 9) bridge-stub: a NEWER unrelated file INSIDE a candidate dir, no seed, no
        #    identity -> UNRESOLVED, not scanned.
        clear()
        seed_off()
        p = write("UNRELATED.jsonl", [_u("user", "from now on unrelated", cwd=other)],
                  mtime=now + 100)
        out, deep = _run(wt, "", projects, sessions, now)  # detached HEAD too
        check("bridge_stub_unresolved", "UNRESOLVED" in out and not deep)
        check("detached_head_noted", "detached HEAD" in out)

        # 10) inferred corrections (n>=2) across distinct turns promote, with location.
        clear()
        seed_on()
        write("SEED.jsonl", [
            _u("user", "no, that's wrong, redo it", cwd=wt),
            _u("assistant", "sorry", cwd=wt),
            _u("user", "actually, revert that", cwd=wt),
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("repeated_corrections_flagged", deep and "repeated correction" in out
              and "INFERRED " in out)

        # 11) perf regression: malformed injection prefixes must not blow up (was
        #     quadratic on `<system-reminder`xN with no closing '>').
        import time as _time
        big = "<system-reminder" * 40000            # ~640 KB, no closing '>'
        t0 = _time.perf_counter()
        strip_injected(big)
        check("no_quadratic_blowup", (_time.perf_counter() - t0) < 2.0)

        # 12) compaction behavior:
        #     - in-span compaction summary sets compaction_seen=True, contributed=True,
        #       notes/locations recorded, and triggers DEEP_CANDIDATES.
        #     - out-of-span compaction summary is ignored, does NOT set compaction_seen,
        #       does NOT trigger DEEP_CANDIDATES, does NOT emit SPAN.
        clear()
        seed_on()
        write("SEED.jsonl", [
            # out-of-span compaction
            {"type": "user", "uuid": "c1", "cwd": other, "isCompactSummary": True},
            # in-span compaction
            {"type": "user", "uuid": "c2", "cwd": wt, "isCompactSummary": True},
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("in_span_compaction_flagged", deep and "compaction marker present" in out)
        check("in_span_compaction_location", "SEED.jsonl:2" in out)
        check("in_span_compaction_span", "SPAN " in out)

        # Now test ONLY out-of-span compaction
        clear()
        write("SEED.jsonl", [
            {"type": "user", "uuid": "c1", "cwd": other, "isCompactSummary": True},
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("out_of_span_compaction_not_flagged", not deep and "compaction marker" not in out)
        check("out_of_span_compaction_no_span", "SPAN " not in out)

        # N) session id found under a DIFFERENT folder than the cwd slug (worktree enter/exit).
        launch_dir = os.path.join(projects, "-launch-folder-slug")
        os.makedirs(launch_dir, exist_ok=True)
        clear()  # the worktree slug dir is now empty (a worktree enter/exit leaves it so)
        lp = os.path.join(launch_dir, "ENVSESS.jsonl")
        with open(lp, "w") as fh:
            fh.write(_mk([
                _u("user", "Update the skill so it always reads the session id first.", cwd=wt),
            ]))
        os.utime(lp, (now, now))
        out, _d = scan(wt, br, projects, sessions, "", "", 3650, 50, now, env_session_id="ENVSESS")
        check("env_id_found_in_other_folder", "| directive |" in out and f"SPAN {lp}" in out)
        out, _d = scan(wt, br, projects, sessions, "", "", 3650, 50, now, env_session_id=None)
        check("env_unset_falls_back", "| directive |" not in out)
        out, _d = scan(wt, br, projects, sessions, "", "", 3650, 50, now, env_session_id="NOPE")
        check("env_missing_note_and_no_span",
              "matched no transcript file" in out and "SPAN " not in out)
        out, _d = scan(wt, br, projects, sessions, "", "", 3650, 50, now, env_session_id="../x")
        check("env_unsafe_id_ignored", "matched no transcript file" in out)
        check("find_session_file_empty", find_session_files(projects, "") == [])
        # SCAN-SUSPECT: big transcript with 0 evidence.
        os.remove(lp)
        big = os.path.join(launch_dir, "BIG.jsonl")
        with open(big, "w") as fh:
            fh.write(_mk([_u("user", "ok thanks " + "x" * 300, cwd=wt)] * 1000))
        os.utime(big, (now, now))
        out, _d = scan(wt, br, projects, sessions, "", "", 3650, 50, now, env_session_id="BIG")
        check("seed_resolved_zero_match_note",
              "NOTE 0 directives matched 1000 typed user turns; review the typed turns by hand "
              "(the transcript path is right)" in out and "check the transcript path" not in out)
        check("weak_lines_capped_and_quoted",
              len(re.findall(r"^WEAK ", out, re.M)) == 10 and "| ok thanks xxx" in out)
        check("weak_lines_keep_counters_intact",
              "EVIDENCE_COUNT=0" in out and "DEEP_CANDIDATES=0" in out
              and "| directive |" not in out)
        # Further phrasings that matched nothing, and two look-alikes that must not.
        for i, (txt, want) in enumerate((
                ("Can you turn the release checklist into a skill please", True),
                ("When I said they should do a release check, I meant not just to type it. "
                 "I mean they should actually run the release skill in full mode.", True),
                ("please raise the retry limit to 5", True),
                ("I would prefer just to post a one-line status. Could you set that up?", True),
                ("Let's focus on tidying about five files at a time", False),
                ("turn the heat into a skillet", False))):
            check(f"directive_further_{i}", bool(DIRECTIVE_RE.search(txt)) == want)
        os.remove(big)
        # T) one session id in TWO folders (resumed in another worktree): both files are
        # scanned, a record copied into both counts once, and uuid-less records merge on
        # (timestamp, type, content hash).
        old_dir = os.path.join(projects, "-old-folder")
        new_dir = os.path.join(projects, "-new-folder")
        os.makedirs(old_dir, exist_ok=True)
        os.makedirs(new_dir, exist_ok=True)
        nots = {"type": "user", "cwd": wt, "timestamp": "2026-01-01T00:00:05Z",
                "message": {"role": "user", "content": "Next time, update the skill with NOUUID."}}
        old_recs = [_u("user", "From now on always run the smoke test.", cwd=wt, uuid="D1"), nots]
        new_recs = [_u("user", "From now on always run the smoke test.", cwd=wt, uuid="D1"), nots,
                    _u("assistant", "Resumed.", cwd=wt, uuid="A9")]
        op, np_ = os.path.join(old_dir, "TWIN.jsonl"), os.path.join(new_dir, "TWIN.jsonl")
        with open(op, "w") as fh:
            fh.write(_mk(old_recs))
        with open(np_, "w") as fh:
            fh.write(_mk(new_recs))
        os.utime(op, (now - 100, now - 100))
        os.utime(np_, (now, now))
        out, _d = scan(wt, br, projects, sessions, "", "", 3650, 50, now, env_session_id="TWIN")
        check("two_folders_both_spans", f"SPAN {op}" in out and f"SPAN {np_}" in out)
        check("two_folders_note", "NOTE session TWIN has 2 transcript files: " in out)
        check("two_folders_dedup", out.count("| directive |") == 2
              and "EVIDENCE_COUNT=2" in out and f"{op}:1 |" in out and f"{np_}:1 |" not in out)
        check("two_folders_typed_turns_dedup", count_typed_turns([op, np_]) == 2)
        os.remove(op)
        os.remove(np_)
        # T2) item 1: repeats of one uuid-less record INSIDE a file keep counting when an
        # unrelated second file is added. Only a record seen in a DIFFERENT file is dropped.
        rep_rec = {"type": "user", "cwd": wt, "timestamp": "2026-01-01T00:00:09Z",
                   "message": {"role": "user", "content": "Please check the deploy log again."}}
        fa, fb, fc = (os.path.join(old_dir, n) for n in ("RA.jsonl", "RB.jsonl", "RC.jsonl"))
        with open(fa, "w") as fh:
            fh.write(_mk([rep_rec] * 6))
        with open(fb, "w") as fh:
            fh.write(_mk([_u("user", "A different typed turn in another file.", cwd=wt)]))
        with open(fc, "w") as fh:
            fh.write(_mk([rep_rec]))
        check("typed_turns_single_file_repeats", count_typed_turns([fa]) == 6)
        check("typed_turns_unrelated_second_file_never_reduces", count_typed_turns([fa, fb]) == 7)
        check("typed_turns_cross_file_copy_dropped", count_typed_turns([fa, fc]) == 6)
        for f in (fa, fb, fc):
            os.remove(f)
        # T3) item 2: SCAN-SUSPECT gates on the LARGEST single file, so a transcript under
        # the threshold plus an identical copy does not trip it.
        half = [_u("user", f"typed turn number {i} with enough words", cwd=wt, uuid=f"HU{i}")
                for i in range(6)]
        half += [_u("assistant", "pad " + "z" * 900, cwd=wt, uuid=f"HP{i}") for i in range(150)]
        ha, hb = os.path.join(old_dir, "HALF.jsonl"), os.path.join(new_dir, "HALF.jsonl")
        for f in (ha, hb):
            with open(f, "w") as fh:
                fh.write(_mk(half))
        os.utime(ha, (now - 100, now - 100))
        os.utime(hb, (now, now))
        check("half_files_each_under_threshold", os.path.getsize(ha) < SUSPECT_BYTES
              < 2 * os.path.getsize(ha))
        out, _d = scan(wt, br, projects, sessions, "", "", 3650, 50, now, env_session_id="HALF")
        check("copy_does_not_trip_scan_suspect", "SCAN-SUSPECT" not in out)
        os.remove(ha)
        os.remove(hb)
        # T4) item 4: an object-valued timestamp must not break the scan; a failed size
        # lookup prints "?".
        odd = {"type": "user", "cwd": wt, "timestamp": {"nested": [1, 2]},
               "message": {"role": "user", "content": "From now on always check ODDTS first."}}
        try:
            hash(record_dup_key(odd))
            key_ok = True
        except TypeError:
            key_ok = False
        check("dup_key_object_timestamp_hashable", key_ok)
        # A non-string uuid is malformed: it must not share a key with the string "1".
        num_uuid = {"type": "user", "uuid": 1, "timestamp": "t1", "message": {"content": "a"}}
        str_uuid = {"type": "user", "uuid": "1", "timestamp": "t2", "message": {"content": "b"}}
        check("dup_key_numeric_uuid_not_merged_with_string",
              record_dup_key(num_uuid) != record_dup_key(str_uuid))
        oa, ob = os.path.join(old_dir, "ODD.jsonl"), os.path.join(new_dir, "ODD.jsonl")
        for f in (oa, ob):
            with open(f, "w") as fh:
                fh.write(_mk([odd]))
        os.utime(oa, (now - 100, now - 100))
        os.utime(ob, (now, now))
        try:
            out, _d = scan(wt, br, projects, sessions, "", "", 3650, 50, now, env_session_id="ODD")
        except Exception as exc:  # the digest must survive
            out = "RAISED " + repr(exc)
        check("object_timestamp_does_not_break_scan", "RAISED" not in out and out.count("| directive |") == 1)
        check("size_kb_failure_prints_question_mark", _size_kb(os.path.join(tmp, "nope.jsonl")) == "?")
        os.remove(oa)
        os.remove(ob)
        # _emit never prints a SPAN for a missing file.
        check("emit_skips_missing_span",
              "SPAN " not in _emit([], [], False, [], [os.path.join(tmp, "missing.jsonl")])[0])
        # O) a main checkout (wt == main_path): with a session id, only that transcript is
        # scanned; other sessions that ran in the same folder are not stitched in (a
        # wrap from a main checkout would otherwise stitch dozens of sessions).
        main_wt = "/tmp/wsX"
        main_dir = os.path.join(projects, slugify(main_wt))
        os.makedirs(main_dir, exist_ok=True)
        mine = os.path.join(main_dir, "MINE.jsonl")
        theirs = os.path.join(main_dir, "THEIRS.jsonl")
        with open(mine, "w") as fh:
            fh.write(_mk([_u("user", "Update the skill so it reads the id first.", cwd=main_wt)]))
        with open(theirs, "w") as fh:
            fh.write(_mk([_u("user", "From now on always write the record first.", cwd=main_wt)]))
        for f in (mine, theirs):
            os.utime(f, (now, now))
        out, _d = scan(main_wt, "main", projects, sessions, main_wt, "", 3650, 50, now,
                       env_session_id="MINE")
        check("main_checkout_only_this_session", f"SPAN {mine}" in out and "THEIRS" not in out)
        out, _d = scan(main_wt, "main", projects, sessions, main_wt, "", 3650, 50, now,
                       env_session_id=None)
        check("main_checkout_without_id_unchanged", "THEIRS" in out)
        # P) the session-id transcript counts every record, whatever its cwd: a session that
        # worked inside worktrees and wraps from the main checkout still has its evidence.
        hop = os.path.join(main_dir, "HOP.jsonl")
        with open(hop, "w") as fh:
            fh.write(_mk([_u("user", "Update the skill so it reads the id first.", cwd=other)]))
        os.utime(hop, (now, now))
        out, _d = scan(main_wt, "main", projects, sessions, main_wt, "", 3650, 50, now,
                       env_session_id="HOP")
        check("env_transcript_counts_records_in_any_cwd", "| directive |" in out and "HOP" in out)

        # Q) noise errors: worktree-guard refusals and MCP sign-in errors never count as a
        # repeated tool error (in practice most INFERRED lines were these). A real
        # repeated error in the same transcript still counts.
        clear()
        seed_on()
        guard = ("This session is isolated in the worktree /tmp/wsX/.claude/worktrees/x, but "
                 "this command is too complex to verify. Refusing to run it.")
        mcp = 'MCP server "claude.ai Example Drive" needs you to sign in again (run /mcp to re-authenticate)'
        write("SEED.jsonl", [
            _terr(guard, cwd=wt), _terr(guard, cwd=wt), _terr("<tool_use_error>" + guard, cwd=wt),
            _terr(mcp, cwd=wt), _terr(mcp, cwd=wt),
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("noise_errors_not_inferred", "repeated tool error" not in out and not deep)
        for i, m in enumerate(("server x needs you to sign in again", "please run /mcp to re-authenticate")):
            write("SEED.jsonl", [_terr(m, cwd=wt), _terr(m, cwd=wt)])
            out, deep = _run(wt, br, projects, sessions, now)
            check(f"noise_marker_alone_{i}", "repeated tool error" not in out and not deep)
        write("SEED.jsonl", [
            _terr(guard, cwd=wt), _terr(guard, cwd=wt),
            _terr("db: table not found", cwd=wt), _terr("db: table not found", cwd=wt),
        ])
        out, deep = _run(wt, br, projects, sessions, now)
        check("real_repeated_error_still_inferred",
              "repeated tool error x2: db: table not found" in out and "isolated" not in out and deep)

        # R) SCAN-SUSPECT needs 5+ typed user turns in the seed transcript. "go"-only
        # autonomous sessions get a NOTE saying 0 evidence is expected instead.
        few = os.path.join(launch_dir, "FEW.jsonl")
        recs = [_u("user", "Build the quick fix for the report table and ship it.", cwd=wt)]
        recs += [_u("user", "go", cwd=wt), _u("user", "ok do it", cwd=wt)]
        recs += [_u("assistant", "working " + "y" * 400, cwd=wt)] * 1000
        with open(few, "w") as fh:
            fh.write(_mk(recs))
        os.utime(few, (now, now))
        out, _d = scan(wt, br, projects, sessions, "", "", 3650, 50, now, env_session_id="FEW")
        check("few_turns_no_suspect", "NOTE SCAN-SUSPECT" not in out)
        check("few_turns_note", "NOTE 0 evidence is expected: only 1 typed user turns" in out)
        # Boundary: 4 typed turns -> NOTE; 5 -> SCAN-SUSPECT. A 20-char turn is an ack;
        # long meta / sidechain turns never count.
        for n, want in ((4, False), (5, True)):
            recs = [_u("user", f"typed turn number {i} with words", cwd=wt) for i in range(n)]
            recs += [_u("user", "x" * 20, cwd=wt), _u("user", "meta " * 20, cwd=wt, isMeta=True),
                     _u("user", "side " * 20, cwd=wt, isSidechain=True)]
            recs += [_u("assistant", "working " + "y" * 400, cwd=wt)] * 1000
            with open(few, "w") as fh:
                fh.write(_mk(recs))
            os.utime(few, (now, now))
            out, _d = scan(wt, br, projects, sessions, "", "", 3650, 50, now, env_session_id="FEW")
            check(f"typed_turn_boundary_{n}", ("NOTE 0 directives matched" in out) == want)
        os.remove(few)
        tt = os.path.join(launch_dir, "TT.jsonl")
        with open(tt, "w") as fh:
            fh.write(_mk([
                _u("user", "go"), _u("user", "<system-reminder>a long injected reminder text here"
                                             "</system-reminder>"),
                _u("user", "Please check the deploy log for errors."),
                _u("assistant", "A long assistant reply that is not a user turn."),
            ]))
        check("count_typed_turns_ignores_acks_and_injected", count_typed_turns(tt) == 1)
        os.remove(tt)

        # S) not in a git tree (empty wt_path): scan ONLY the session-id transcript.
        sp = os.path.join(launch_dir, "NOGIT.jsonl")
        with open(sp, "w") as fh:
            fh.write(_mk([_u("user", "Update the skill so it reads the id first.", cwd="/home/x")]))
        os.utime(sp, (now, now))
        out, _d = scan("", "", projects, sessions, "", "", 3650, 50, now, env_session_id="NOGIT")
        check("no_git_session_id_mode", "| directive |" in out and f"SPAN {sp}" in out
              and "not in a git work tree: scanning only" in out and out.count("SPAN ") == 1)
        out, _d = scan("", "", projects, sessions, "", "", 3650, 50, now, env_session_id=None)
        check("no_git_no_id_skipped", "deep scan skipped" in out and "DEEP_CANDIDATES=0" in out
              and "SPAN " not in out)
        os.remove(sp)

    if failures:
        print("SELF-TEST FAILED:", ", ".join(failures), file=sys.stderr)
        return 1

    print("SELF-TEST OK (positive + per-vector negatives + adjacency-both-orders + "
          "span-filter[mixed/mention] + resumed-union[unique-per-file] + per-turn-counting "
          "+ non-genuine-exclusion + middle-only[whole-file] + bridge-stub + detached-HEAD "
          "+ inferred-loc + no-quadratic-blowup + compaction + noise-errors + typed-turn-suspect "
          "+ no-git-session-id + mid-turn-user-message)")
    return 0


def _run(wt, branch, projects, sessions, now):
    return scan(wt, branch, projects, sessions,
                main_path="", parent_path="", recency_days=3650, cap=50, now=now)


# --- cli -------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description="deep session-log scan for session-wrap")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--wt-path", default="")
    ap.add_argument("--wt-branch", default="")
    ap.add_argument("--main-path", default="")
    ap.add_argument("--parent-path", default="")
    ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--sessions-dir", default=os.path.expanduser("~/.claude/sessions"))
    ap.add_argument("--recency-days", type=int, default=365)
    ap.add_argument("--cap", type=int, default=50)
    ap.add_argument("--now", type=float, default=None)
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    # An empty --wt-path is session-id mode (not in a git work tree); see scan().
    import time
    now = args.now if args.now is not None else time.time()
    out, _ = scan(args.wt_path, args.wt_branch, args.projects_dir, args.sessions_dir,
                  args.main_path, args.parent_path, args.recency_days, args.cap, now,
                  env_session_id=os.environ.get("CLAUDE_CODE_SESSION_ID"))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
