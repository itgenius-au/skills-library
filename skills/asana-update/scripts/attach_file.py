#!/usr/bin/env python3
"""Attach files to an Asana task, with the comment that goes with them.

    attach_file.py <task_url_or_gid> --file PATH [--file PATH ...]
                   [--name NAME ...]
                   --comment link|name|none
                   [--body-file BODY.html] [--mention USER_GID ...]
                   [--resume ATTACHMENT_GID ...] [--no-follow] [--dry-run]

Three shapes, chosen with --comment:

  link  exactly one file; the comment is the body, then a link to the file.
        For showing something with what the comment says (a QA or debugging
        screenshot, a piece of evidence).
  name  one or more files; the comment is the body, the --mention tags, then
        each file's exact name in a list. Nothing is linked. For handing
        documents to whoever is tagged; they find the files by name in the
        task's attachment list.
  none  no comment. For when the mention lives elsewhere (a description).

--name sends a file under another name, one --name per --file, in the same
order (for example a phone photo as "Site visit photo 3"). A name
with no extension keeps the file's own. Every check, the duplicate check and
--resume use that name. Without --name, a file goes up under its own name.

Everyone @mentioned in the posted comment is then added as a follower of the
task and read back, so they see later replies. A follower miss prints PARTIAL
and never fails the run. --no-follow skips it; use it only for the subject of a
private or sensitive task.

A refusal before anything is sent prints one line. Once sending has started,
any failure stops at once and prints a STOPPED block: what landed, what did
not, whether the comment posted, and the command that finishes the job. That
command carries --resume <attachment gid> for each file that already landed:
each one is checked (still on the task, same name, same size) and not
uploaded again. If a reply is lost, the task is re-read first: a write that
did land is counted ("Reconciled"); one that can't be accounted for is marked
Uncertain (a file) or UNKNOWN (the comment). Never rename a file to get past
the duplicate check - that is how duplicate and orphaned attachments happen.

Exit codes: 0 done; 2 verify failed (something landed but doesn't check out);
3 needs a person (a file of that name is already on the task and is not
covered by --resume; nothing uploaded); 4 bad input or an API error. They are
distinct, unlike the other scripts' exit 1, so an agent can tell "already
there" from "Asana failed" without parsing text.
"""

import argparse
import html
import http.client
from html.parser import HTMLParser
import json
import mimetypes
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from fnmatch import fnmatch
from pathlib import Path

import _asana
from _asana import (BASE_URL, extract_task_gid, mentioned_user_gids, task_url,
                    unsupported_tags, wrap_body)

MAX_BYTES = 100 * 1024 * 1024  # Asana's documented per-attachment limit
# Names that usually hold credentials. A file posted here is visible to the
# whole workspace, so these are refused outright; rename the file if it really
# is safe to post.
CREDENTIAL_NAMES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "id_rsa*", "id_ed25519*",
                    "*key*.json", "*credential*", "*secret*", "*token*")
ATTACHMENT_FIELDS = "name,size,permanent_url"
LINK_PLACEHOLDER = "(asset link, added after upload)"


class Stop(Exception):
    """Stop now: print `msg` and exit with `code`."""

    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code
        self.msg = msg


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

class Named:
    """A local file sent under another name (--name). It stands in for the Path:
    .name is the upload name; stat(), read_bytes() and the rest read the file."""

    def __init__(self, path: Path, name: str):
        self.path = path
        self.name = name

    def __getattr__(self, attr):
        return getattr(self.path, attr)

    def __str__(self):
        return str(self.path)


# An extension: a dot, then 1 to 8 letters or digits with at least one letter.
# "Flight 07.15" or "Mr. Smith" has a dot but no extension, so it gets the file's.
_EXTENSION_RE = re.compile(r"\.(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{1,8}")


def upload_name(path: Path, name: str) -> str:
    """The --name for this file, with the file's extension when it has none."""
    name = name.strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise Stop(4, f"--name {name!r} is not a file name (empty, or has a slash).")
    has_extension = _EXTENSION_RE.fullmatch(Path(name).suffix or "")
    return name if has_extension else name + path.suffix


def check_inputs(args) -> list:
    """Every refusal that needs no network. Returns the files as Paths
    (a Named for a file given a --name)."""
    given = getattr(args, "names", None) or []
    if given and len(given) != len(args.files):
        raise Stop(4, f"{len(given)} --name for {len(args.files)} --file; give one --name per "
                      "--file, in the same order, or none.")
    paths, names = [], set()
    for i, f in enumerate(args.files):
        p = Path(f).expanduser()
        if not p.is_file():
            raise Stop(4, f"Not a file: {p}")
        if p.stat().st_size > MAX_BYTES:
            raise Stop(4, f"{p.name} is {p.stat().st_size} bytes, over Asana's 100 MB limit.")
        name = upload_name(p, given[i]) if given else p.name
        for checked in {p.name, name}:
            if any(fnmatch(checked.lower(), pat) for pat in CREDENTIAL_NAMES):
                raise Stop(4, f"{checked} looks like a credential file; refused. Everyone in the "
                              "workspace can open an attachment. Rename it only if it really is safe.")
        if any(c == '"' or ord(c) < 32 for c in name):
            raise Stop(4, f"{name!r} has a quote, newline or control character, which the "
                          "upload can't carry unchanged; rename the local file and run again.")
        if name in names:
            raise Stop(4, f"{name} is given twice; file names must be unique on the task.")
        names.add(name)
        paths.append(Named(p, name) if name != p.name else p)
    if args.comment == "link" and len(paths) != 1:
        raise Stop(4, "--comment link takes exactly one file; use --comment name for several.")
    if args.comment == "none" and (args.body_file or args.mention):
        raise Stop(4, "--comment none posts no comment, so --body-file and --mention would be "
                      "silently dropped; refused.")
    for gid in args.mention + args.resume:
        if not gid.isdigit():
            raise Stop(4, f"Expected a numeric Asana gid, got {gid!r}.")
    if len(set(args.resume)) != len(args.resume):
        raise Stop(4, "The same --resume gid is given twice.")
    return paths


def unwrap_body(s: str) -> str:
    """Strip an outer <body>...</body>, as append_description.py does, so the
    mentions and file list land inside the one body wrap_body adds."""
    s = s.strip()
    if s.startswith("<body>") and s.endswith("</body>"):
        return s[len("<body>"):-len("</body>")].strip()
    return s


def read_body(args) -> str:
    if not args.body_file:
        return ""
    try:
        body = unwrap_body(Path(args.body_file).expanduser().read_text())
    except (OSError, UnicodeDecodeError) as e:
        raise Stop(4, f"Cannot read --body-file {args.body_file}: {e}")
    bad = unsupported_tags(body)
    if bad:
        raise Stop(4, "The body has tag(s) Asana rejects: " + ", ".join(f"<{t}>" for t in bad))
    return body


# ---------------------------------------------------------------------------
# The comment
# ---------------------------------------------------------------------------

def build_comment(option: str, body: str, mentions: list, files: list):
    """The comment's HTML (unwrapped), or None for --comment none.

    `files` is a list of (name, url) in --file order; url may be the
    placeholder in a dry run. Names are escaped the way the skill escapes
    text (`&`, `<`, `>` only; Asana shows `&#x27;` literally).
    """
    if option == "none":
        return None
    parts = [body] if body else []
    tags = " ".join(f'<a data-asana-gid="{gid}"/>' for gid in mentions)
    if tags:
        parts.append(tags)
    if option == "link":
        name, url = files[0]
        parts.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(name, quote=False)}</a>')
    else:  # name: exact names, never linked
        items = "".join(f"<li><code>{html.escape(n, quote=False)}</code></li>" for n, _ in files)
        parts.append(f"<ul>{items}</ul>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Asana calls (kept small so tests can replace them)
# ---------------------------------------------------------------------------

# Set by main() from --token-secret / --token-project.
_TOKEN_KWARGS = {}


def get_token() -> str:
    try:
        return _asana.fetch_token(**_TOKEN_KWARGS)
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip()[:300]
        raise Stop(4, f"Could not fetch the Asana token (gcloud failed: {detail}). Nothing was "
                      "sent. If gcloud asks you to sign in again, the person runs "
                      "`gcloud auth login` in their own terminal.")


def list_attachments(token: str, task: str) -> list:
    return _asana.paginate("/attachments", token,
                           {"parent": task, "opt_fields": ATTACHMENT_FIELDS})


def encode_multipart(fields: dict, file_field: str, filename: str, content: bytes,
                     content_type: str, boundary: str = None):
    """A multipart/form-data body. Returns (body, Content-Type header value).

    `_asana.request` sends JSON only, and Asana takes uploads as multipart.
    """
    boundary = boundary or uuid.uuid4().hex
    # check_inputs refuses these names; this only stops a header being broken.
    safe_name = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
    chunks = []
    for key, value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                      f"{value}\r\n".encode())
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
                  f'filename="{safe_name}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
                  + content + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload(token: str, task: str, path: Path) -> dict:
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body, header = encode_multipart({"parent": task}, "file", path.name, path.read_bytes(), ctype)
    req = urllib.request.Request(
        f"{BASE_URL}/attachments?opt_fields={ATTACHMENT_FIELDS}", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": header,
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["data"]


def asset_url(attachment: dict, gid: str) -> str:
    """The attachment's own link. Falls back to the asset-link shape Asana
    returns if permanent_url is missing."""
    return (attachment.get("permanent_url")
            or f"https://app.asana.com/app/asana/-/get_asset?asset_id={gid}")


def post_story(token: str, task: str, comment_html: str) -> dict:
    payload = {"data": {"html_text": wrap_body(_asana.add_author_line(comment_html, token))}}
    return _asana.request("POST", f"/tasks/{task}/stories", token, data=payload)["data"]


def follow_mentions(token: str, task: str, story_gid: str, comment_html: str) -> list:
    """Add the comment's @mentioned users as followers. Never raises (see _asana)."""
    return _asana.follow_mentions(task, story_gid, comment_html, token,
                                  request_fn=_asana.request)


def list_stories(token: str, task: str) -> list:
    return _asana.paginate(f"/tasks/{task}/stories", token,
                           {"opt_fields": "resource_subtype,text,html_text,created_by.gid"})


def my_user_gid(token: str) -> str:
    """Whose token this is: the author of every comment this script posts."""
    return _asana.request("GET", "/users/me", token, params={"opt_fields": "gid"})["data"]["gid"]


# ---------------------------------------------------------------------------
# A write whose response was lost: did it land?
# ---------------------------------------------------------------------------
# The skill's rule ("When things go wrong"): before retrying, query the API to
# see whether the write actually happened. Same shape as create_task.py's
# create_or_resume: compare against what existed before the write; adopt a new
# match; anything that can't be accounted for is uncertain, never assumed.
# http.client.HTTPException covers a response cut short (IncompleteRead),
# which is not an OSError.
API_ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError, ValueError,
              KeyError, TypeError)


def refused(e: Exception) -> bool:
    """Asana answered 4xx: it refused the request, so nothing was written.
    Anything else (a timeout, a cut-off response, a 5xx, no id in the reply)
    leaves open whether the write happened."""
    return isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500


def reconcile_upload(token: str, task: str, path: Path, before: set, landed: dict,
                     was_refused: bool):
    """("landed", gid) | ("absent", None) | ("unknown", None).

    Adopts exactly one new attachment with this name and size. It can't prove
    who uploaded it; a different person attaching a same-named, same-sized
    file in the same seconds is treated as unreachable (as create_task.py's
    create_or_resume adopts a new same-name task). Nothing found is "absent"
    only if Asana refused the request; otherwise it is unknown, as in
    create_or_resume.
    """
    try:
        rows = list_attachments(token, task)
    except API_ERRORS:
        return "unknown", None
    mine = set(landed.values())
    new = [a for a in rows if a.get("gid") not in before and a.get("gid") not in mine
           and a.get("name") == path.name]
    matching = [a for a in new if size_of(a) == path.stat().st_size]
    if len(matching) == 1 and len(new) == 1:
        return "landed", matching[0]["gid"]
    if not new and was_refused:
        return "absent", None
    return "unknown", None


class _Labels(HTMLParser):
    """Collects the text inside <a> and <code> elements: where this script puts
    file names (a link's label, a list item's code)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.current = []
        self.labels = []

    def handle_starttag(self, tag, attrs):
        if tag in ("a", "code"):
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in ("a", "code") and self.depth:
            self.depth -= 1
            if not self.depth:
                self.labels.append("".join(self.current).strip())
                self.current = []

    def handle_data(self, data):
        if self.depth:
            self.current.append(data)


def story_names(story: dict) -> set:
    """Exact strings a comment presents as names: link labels and code items in
    its rich text, and whole lines of its plain text.

    Exact, not substring: a requested name must equal one of these, so
    "attachment", "body" or a suffix of a real name can't match markup, a URL
    or part of a longer name. Both fields are read because a link comment's
    plain `text` shows the asset URL and the name survives only in `html_text`.
    """
    parser = _Labels()
    parser.feed(story.get("html_text") or "")
    lines = {line.strip() for line in (story.get("text") or "").splitlines()}
    return {n for n in parser.labels + list(lines) if n}


def reconcile_comment(token: str, task: str, before: set, names: list, was_refused: bool):
    """("posted", gid) | ("absent", None) | ("unknown", None).

    Ours means: new since the snapshot, written by this token's own user, and
    naming every file; exactly one such comment. Anything else that can't be
    ruled out is unknown. "Absent" needs both no new comment and a refusal.
    """
    try:
        rows = list_stories(token, task)
        me = my_user_gid(token)
    except API_ERRORS:
        return "unknown", None
    new = [s for s in rows if s.get("gid") not in before
           and s.get("resource_subtype") == "comment_added"]
    ours = [s for s in new if (s.get("created_by") or {}).get("gid") == me
            and set(names) <= story_names(s)]
    if len(ours) == 1:
        return "posted", ours[0]["gid"]
    if not new and was_refused:
        return "absent", None
    return "unknown", None


def size_of(attachment: dict):
    """The attachment's size in bytes, or None if Asana didn't say. 0 is a size."""
    try:
        return int(attachment.get("size"))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Reporting a stop
# ---------------------------------------------------------------------------

def describe_error(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        try:
            text = e.read().decode(errors="replace")[:300]
        except Exception:  # the body may already have been read by _asana.request
            text = ""
        return f"HTTP {e.code} {text}".strip()
    return f"{type(e).__name__}: {e}"


def resume_command(args, task: str, landed: dict) -> str:
    cmd = ["python3", str(Path(__file__).resolve()), task]
    for f in args.files:
        # absolute(), not resolve(): a symlink keeps its own name, which is the
        # name the first run uploaded under.
        cmd += ["--file", str(Path(f).expanduser().absolute())]
    for name in getattr(args, "names", None) or []:
        cmd.append(f"--name={name}")   # one argument: a name that starts with "-" stays a value
    cmd += ["--comment", args.comment]
    if args.body_file:
        cmd += ["--body-file", str(Path(args.body_file).expanduser().absolute())]
    for gid in args.mention:
        cmd += ["--mention", gid]
    if args.no_follow:
        cmd += ["--no-follow"]
    for flag in ("token_secret", "token_project"):
        value = getattr(args, flag, None)
        if value:
            cmd += ["--" + flag.replace("_", "-"), value]
    for gid in landed.values():
        cmd += ["--resume", gid]
    return " ".join(shlex.quote(c) for c in cmd)


COMMENT_UNKNOWN = ("UNKNOWN - it may have posted. Look at the task's comments before running "
                   "the resume command; if the comment is there, do not run it.")


def stop_block(reason: str, args, task: str, paths: list, landed: dict, comment: str,
               uncertain: list = ()) -> str:
    missing = [p.name for p in paths if p.name not in landed and p.name not in uncertain]
    lines = [
        f"STOPPED: {reason}",
        "Landed:        " + (", ".join(f"{n} ({g})" for n, g in landed.items()) or "none"),
        "Not uploaded:  " + (", ".join(missing) or "none"),
    ]
    if uncertain:
        lines.append("Uncertain:     " + ", ".join(uncertain) + " - may be on the task; look "
                     "before resuming (if it is there, the resume run stops at the duplicate "
                     "check: ask the person, don't rename)")
    lines += [
        f"Comment:       {comment}",
        f"Resume with:   {resume_command(args, task, landed)}",
        "Tell the person, record the resume command where your work is tracked, and run it "
        "once Asana works again. Do not rename files to get past the duplicate check. If the "
        "script's path above is gone (a plugin update moves it), run scripts/attach_file.py "
        "from the current asana-update skill with the same arguments.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def preview(path: Path) -> str:
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    source = f"  (from {path.path})" if isinstance(path, Named) else ""
    line = f"  {path.name}{source}  {path.stat().st_size} bytes  {ctype}"
    if ctype.startswith("text/") or path.suffix in (".md", ".json", ".csv", ".log", ".txt"):
        try:
            head = path.read_text(errors="replace").splitlines()[:5]
        except OSError as e:
            raise Stop(4, f"Cannot read {path}: {e}")
        line += "".join(f"\n      | {h}" for h in head)
    return line


def run(args) -> int:
    try:
        task = extract_task_gid(args.task)
    except ValueError as e:
        raise Stop(4, str(e))
    paths = check_inputs(args)
    body = read_body(args)
    planned = build_comment(args.comment, body, args.mention,
                            [(p.name, LINK_PLACEHOLDER) for p in paths])
    if planned is not None:
        try:
            wrap_body(planned)
        except ValueError as e:
            raise Stop(4, str(e))

    print(f"Task {task_url(task)}: {len(paths)} file(s), comment: {args.comment}")
    for p in paths:
        print(preview(p))
    if args.resume:
        print("Already landed (--resume): " + ", ".join(args.resume))
    if planned is not None:
        print("Comment:\n" + planned)
        mentions = mentioned_user_gids(planned)
        if mentions and args.no_follow:
            print("Followers: not changed (--no-follow)")
        elif mentions:
            print("Will add as followers (after the post, users only): " + ", ".join(mentions))
    if args.dry_run:
        print("DRY RUN: nothing sent. Show this to the person; run without --dry-run on their go.")
        return 0

    token = get_token()
    landed = {}  # name -> attachment gid, in --file order as they land

    try:
        current = list_attachments(token, task)
    except API_ERRORS as e:
        raise Stop(4, f"Could not list the task's attachments ({describe_error(e)}). Nothing sent.")
    by_gid = {a.get("gid"): a for a in current}
    by_name = {p.name: p for p in paths}

    for gid in args.resume:
        a = by_gid.get(gid)
        if a is None:
            raise Stop(4, f"--resume {gid} is not on task {task}. Do not rename the file; ask the "
                          "person what happened to it.")
        p = by_name.get(a.get("name"))
        if p is None or size_of(a) != p.stat().st_size:
            raise Stop(4, f"--resume {gid} is {a.get('name')!r} ({a.get('size')} bytes), which "
                          "doesn't match any --file by name and size. Do not rename the file; "
                          "ask the person.")
        if p.name in landed:
            raise Stop(4, f"--resume {landed[p.name]} and --resume {gid} both match {p.name}; "
                          "only one of them is this run's file. Ask the person which.")
        landed[p.name] = gid

    on_task = {a.get("name") for a in current}
    taken = [p.name for p in paths if p.name not in landed and p.name in on_task]
    if taken:
        raise Stop(3, f"Already on task {task}: {', '.join(taken)}. Nothing uploaded. If an "
                      "earlier run of this script left it there, its STOPPED block has the "
                      "resume command; otherwise ask the person.")

    before_attachments = set(by_gid)
    for p in paths:
        if p.name in landed:
            continue
        try:
            a = upload(token, task, p)
            if not (isinstance(a, dict) and a.get("gid")):
                raise ValueError("the upload response carried no attachment gid")
        except API_ERRORS as e:
            state, gid = reconcile_upload(token, task, p, before_attachments, landed,
                                          refused(e))
            if state == "landed":
                print(f"Reconciled: {p.name} landed ({gid}) although the response failed.")
                landed[p.name] = gid
                continue
            raise Stop(4, stop_block(f"upload of {p.name} failed ({describe_error(e)})",
                                     args, task, paths, landed, "not posted",
                                     uncertain=[p.name] if state == "unknown" else []))
        landed[p.name] = a["gid"]

    try:
        after = {a.get("gid"): a for a in list_attachments(token, task)}
    except API_ERRORS as e:
        raise Stop(2, stop_block(f"could not re-read the attachments to verify "
                                 f"({describe_error(e)})", args, task, paths, landed,
                                 "not posted"))
    for name, gid in landed.items():
        seen = after.get(gid)
        if not seen or seen.get("name") != name or \
                size_of(seen) != by_name[name].stat().st_size:
            raise Stop(2, stop_block(f"VERIFY FAILED: {name} (gid {gid}) is not on the task with "
                                     "the same name and size; check the task now",
                                     args, task, paths, landed, "not posted"))

    story = None
    comment = build_comment(args.comment, body, args.mention,
                            [(p.name, asset_url(after[landed[p.name]], landed[p.name]))
                             for p in paths])
    if comment is not None:
        # Mark once here, so the echo below shows the text that posts.
        comment = _asana.add_author_line(comment, token)
        try:
            before_stories = {s.get("gid") for s in list_stories(token, task)}
        except API_ERRORS as e:
            raise Stop(4, stop_block(f"could not read the task's comments before posting "
                                     f"({describe_error(e)})", args, task, paths, landed,
                                     "not posted"))
        try:
            story = post_story(token, task, comment)
            if not (isinstance(story, dict) and story.get("gid")):
                raise ValueError("the comment response carried no story id")
        except API_ERRORS as e:
            state, gid = reconcile_comment(token, task, before_stories,
                                           [p.name for p in paths], refused(e))
            if state == "posted":
                print(f"Reconciled: the comment posted ({gid}) although the response failed.")
                story = {"gid": gid}
            else:
                raise Stop(4, stop_block(f"posting the comment failed ({describe_error(e)})",
                                         args, task, paths, landed,
                                         "not posted" if state == "absent" else COMMENT_UNKNOWN))

    for p in paths:
        a = after[landed[p.name]]
        verb = "Already attached (--resume)" if landed[p.name] in args.resume else "Attached"
        print(f"{verb} {p.name}  gid {landed[p.name]}  {asset_url(a, landed[p.name])}")
    if story:
        print(f"Posted story {story['gid']}:\n{comment}")
        # A mention notifies once; following keeps them on the thread. Never fatal.
        if not args.no_follow and mentioned_user_gids(comment):
            follow_mentions(token, task, story["gid"], comment)
    print(f"Done: {task_url(task)}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("task", help="Task GID or URL")
    p.add_argument("--file", required=True, action="append", dest="files",
                   help="A file to attach (repeatable)")
    p.add_argument("--name", action="append", default=[], dest="names", metavar="NAME",
                   help="Send the file under this name: one per --file, in order. A name "
                        "with no extension keeps the file's own.")
    p.add_argument("--comment", required=True, choices=["link", "name", "none"],
                   help="link: comment links the one file; name: comment names every file, "
                        "no links; none: no comment")
    p.add_argument("--body-file", help="HTML for the comment's opening text")
    p.add_argument("--mention", action="append", default=[], metavar="USER_GID",
                   help="Tag this person in the comment (repeatable); notifies them")
    p.add_argument("--resume", action="append", default=[], metavar="ATTACHMENT_GID",
                   help="This file already landed in an earlier run; check it, don't re-upload")
    p.add_argument("--no-follow", action="store_true",
                   help="Do not add the @mentioned users as followers. Only for the "
                        "subject of a private or sensitive task.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the files and the comment and exit without sending")
    _asana.add_token_args(p)
    args = p.parse_args(argv)
    global _TOKEN_KWARGS
    _TOKEN_KWARGS = _asana.token_request(args)
    try:
        return run(args)
    except Stop as s:
        print(s.msg)
        return s.code


if __name__ == "__main__":
    sys.exit(main())
