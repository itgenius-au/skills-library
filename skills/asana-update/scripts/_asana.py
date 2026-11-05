"""Shared helpers for the asana-update skill's scripts.

Why this file exists: duplicate tasks and broken comments usually trace back to
shell escaping (curl -d '{...}' with embedded newlines or quotes -> malformed
JSON -> the agent misreads the reply as a failure -> retry -> duplicate).
Routing every write through Python with json.dumps removes that failure mode.

Settings come from ~/.claude/asana-update.config.json, a flat JSON object
(copy templates/asana-update.config.example.json). Set ASANA_UPDATE_CONFIG to
read another file. The token is resolved in this order:

  1. --token-secret / --token-project on the command line (Google Secret
     Manager, read with gcloud);
  2. token_secret + gcp_project in the config (Secret Manager, read with gcloud);
  3. the ASANA_TOKEN environment variable;
  4. none of these: the script stops with exit 2 and says what to set.

Time entries (log_time.py) use personal_token_secret or ASANA_PERSONAL_TOKEN
when set, because Asana shows the token's owner as the entry's author; with
neither, they use the token above.
"""

import html
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://app.asana.com/api/1.0"
TEMPLATE = "templates/asana-update.config.example.json"


def _config_path() -> str:
    return os.environ.get("ASANA_UPDATE_CONFIG") or os.path.expanduser(
        "~/.claude/asana-update.config.json")


CONFIG_PATH = _config_path()


# "ok", "missing" (no file) or "invalid" (unreadable, bad JSON, or not a JSON
# object). An invalid file stops every script with exit 2 (check_config), so a
# typo in the config is never read as "nothing configured".
CONFIG_STATUS = "missing"


def load_config() -> dict:
    """Read the config file. Returns {} when it is absent or invalid, and sets
    CONFIG_STATUS to say which."""
    global CONFIG_STATUS
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
    except FileNotFoundError:
        CONFIG_STATUS = "missing"
        return {}
    except (OSError, ValueError):
        CONFIG_STATUS = "invalid"
        return {}
    if not isinstance(data, dict):
        CONFIG_STATUS = "invalid"
        return {}
    CONFIG_STATUS = "ok"
    return data


CONFIG = load_config()


def _cfg_str(value) -> str:
    """A config string, or "" when it is missing, not a string, or still a
    template placeholder ("your_...", "you@example.com" or "Your Name")."""
    if not isinstance(value, str):
        return ""
    s = value.strip()
    if s.lower().startswith("your_") or s.lower() == "you@example.com" or s == "Your Name":
        return ""
    return s


WORKSPACE = _cfg_str(CONFIG.get("workspace_gid"))
GCP_PROJECT = _cfg_str(CONFIG.get("gcp_project"))
TOKEN_SECRET = _cfg_str(CONFIG.get("token_secret"))
PERSONAL_TOKEN_SECRET = _cfg_str(CONFIG.get("personal_token_secret"))
# Optional: pins the gcloud account used for every Secret Manager read. Without
# it, gcloud uses its active account, which another terminal can change.
GCLOUD_ACCOUNT = _cfg_str(CONFIG.get("gcloud_account"))
MY_USER_GID = _cfg_str(CONFIG.get("user_gid"))
MY_EMAIL = _cfg_str(CONFIG.get("user_email"))
MY_NAME = _cfg_str(CONFIG.get("user_name"))
_AGENTS = CONFIG.get("agent_user_gids")
AGENT_USER_GIDS = [str(g) for g in _AGENTS] if isinstance(_AGENTS, list) else []
_SECTIONS = CONFIG.get("default_sections")
DEFAULT_SECTIONS = ({str(k): str(v) for k, v in _SECTIONS.items()}
                    if isinstance(_SECTIONS, dict) else {})
AUTHOR_LABEL = _cfg_str(CONFIG.get("author_label")) or "Claude"
_AUTHOR_CACHE = {}
_TOKEN_CACHE = {}
# Tokens that are probably a person's own PAT (an explicit secret, or the
# ASANA_TOKEN variable). Every token gets the /users/me lookup; this set only
# records where a token came from.
_EXPLICIT_TOKENS = set()
_sleep = time.sleep
_TOTAL_SLEEP = 0
_MAX_ATTEMPTS = 5
_MAX_TOTAL_SLEEP = 600


class SetupError(SystemExit):
    """A missing setting. Exits 2; str() is the message."""

    def __init__(self, msg: str):
        super().__init__(2)
        self.msg = msg

    def __str__(self):
        return self.msg


def setup_error(msg: str) -> SetupError:
    print(f"asana-update: {msg}", file=sys.stderr)
    return SetupError(msg)


def check_config() -> None:
    """Stop with exit 2 when the config file exists but is not a JSON object."""
    if CONFIG_STATUS == "invalid":
        raise setup_error(
            f"config at {CONFIG_PATH} is not a JSON object (unreadable or bad JSON). "
            f"Fix it, or copy {TEMPLATE} again.")


def require_workspace(value: str = "") -> str:
    """The workspace gid to use: `value`, else workspace_gid from the config."""
    check_config()
    ws = (value or "").strip() or WORKSPACE
    if not ws:
        raise setup_error(
            f"no workspace gid. Set workspace_gid in {CONFIG_PATH} (copy {TEMPLATE}), "
            "or pass --workspace <gid>.")
    return ws


def _secret_read(secret_name: str, project: str) -> str:
    cache_key = (project, secret_name)
    if cache_key in _TOKEN_CACHE:
        return _TOKEN_CACHE[cache_key]
    cmd = [(shutil.which("gcloud") or "gcloud"), "secrets", "versions", "access", "latest",
           f"--secret={secret_name}", f"--project={project}"]
    if GCLOUD_ACCOUNT:
        cmd.append(f"--account={GCLOUD_ACCOUNT}")
    where = f"secret {secret_name!r} in project {project!r}"
    if GCLOUD_ACCOUNT:
        where += f" as {GCLOUD_ACCOUNT}"
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        # The callers print exc.stderr as "nothing written: ...". Name the
        # secret and project there; the secret's value (stdout) is never shown.
        exc.stderr = f"{where}: {(exc.stderr or '').strip() or 'gcloud failed'}"
        exc.output = exc.stdout = None
        raise
    except OSError as exc:
        raise setup_error(
            f"gcloud not found or not runnable ({type(exc).__name__}), so {where} "
            "cannot be read. Install the Google Cloud CLI, or use ASANA_TOKEN instead.")
    token = result.stdout.strip()
    _TOKEN_CACHE[cache_key] = token
    return token


def fetch_token(secret_name: str = None, personal: bool = False, project: str = None) -> str:
    """Return an Asana token. Never prints it. Order: see the module docstring.

    A gcloud failure raises subprocess.CalledProcessError (the callers turn it
    into a one-line "nothing written" message). A missing setting raises
    SetupError (exit 2)."""
    check_config()
    if secret_name is not None or project is not None:
        secret = secret_name or (PERSONAL_TOKEN_SECRET if personal else "") or TOKEN_SECRET
        effective_project = project or GCP_PROJECT
        if not secret:
            raise setup_error("--token-project needs --token-secret (or token_secret in the config).")
        if not effective_project:
            raise setup_error(
                f"--token-secret {secret!r} needs --token-project, or gcp_project in {CONFIG_PATH}.")
        token = _secret_read(secret, effective_project)
        if not personal:
            _EXPLICIT_TOKENS.add(token)
        return token

    if personal:
        if PERSONAL_TOKEN_SECRET:
            # A personal secret that cannot be read must stop the write: falling
            # back would log the time entry under another login, for good.
            if not GCP_PROJECT:
                raise setup_error(
                    f"personal_token_secret is set but gcp_project is not, in {CONFIG_PATH}.")
            return _secret_read(PERSONAL_TOKEN_SECRET, GCP_PROJECT)
        ambient = os.environ.get("ASANA_PERSONAL_TOKEN")
        if ambient:
            return ambient

    if TOKEN_SECRET and GCP_PROJECT:
        return _secret_read(TOKEN_SECRET, GCP_PROJECT)
    ambient = os.environ.get("ASANA_TOKEN")
    if ambient:
        _EXPLICIT_TOKENS.add(ambient)
        return ambient
    if TOKEN_SECRET:
        raise setup_error(f"token_secret is set but gcp_project is not, in {CONFIG_PATH}.")
    raise setup_error(
        "no Asana token. Do one of: (1) pass --token-secret <secret> --token-project <project> "
        "(Google Secret Manager); (2) set token_secret and gcp_project in "
        f"{CONFIG_PATH} (copy {TEMPLATE}); (3) export ASANA_TOKEN=<your personal access token>.")


def add_token_args(parser):
    """Add --token-secret / --token-project to a parser."""
    g = parser.add_argument_group("token from Google Secret Manager")
    g.add_argument("--token-secret", metavar="SECRET",
                   help="Secret Manager secret that holds the token to write with "
                        "(for example a workspace your default token cannot reach).")
    g.add_argument("--token-project", metavar="PROJECT",
                   help="GCP project that holds --token-secret (default: gcp_project).")
    return g


def token_request(args) -> dict:
    """Return the fetch_token() keyword arguments the token options ask for.

    {} means the default token. Raises SystemExit on a bad combination, before
    any secret is read or anything is written."""
    secret = getattr(args, "token_secret", None)
    project = getattr(args, "token_project", None)
    for flag, value in (("--token-secret", secret), ("--token-project", project)):
        if value is not None and not value.strip():
            raise SystemExit(f"refusing to write: {flag} is empty")
    if project is not None and secret is None and not (TOKEN_SECRET or PERSONAL_TOKEN_SECRET):
        raise SystemExit("refusing to write: --token-project needs --token-secret "
                         "(or token_secret in the config)")
    kwargs = {}
    if secret is not None:
        kwargs["secret_name"] = secret.strip()
    if project is not None:
        kwargs["project"] = project.strip()
    return kwargs


def request(method: str, path: str, token: str, data=None, params=None):
    """Authenticated Asana API call. Returns parsed JSON, raises on HTTP error.

    429 is retried after Retry-After; a 5xx or a network error is retried for
    GET only (a write may have landed, so the caller checks before retrying)."""
    global _TOTAL_SLEEP

    url = BASE_URL + path
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    for attempt in range(_MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode(errors="replace")
            except Exception as body_exc:
                error_body = f"<body unavailable: {type(body_exc).__name__}>"
            print(f"HTTP {exc.code} {method} {path}\n{error_body}", file=sys.stderr)
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = int(retry_after) if retry_after is not None else 1
                except (TypeError, ValueError):
                    delay = 1
            elif 500 <= exc.code < 600 and method == "GET":
                delay = 2 ** (attempt + 1)
            else:
                raise
            retry_exc = exc
        except (
            urllib.error.URLError,
            TimeoutError,
            http.client.HTTPException,
            ConnectionError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            if method != "GET":
                raise
            delay = 2 ** (attempt + 1)
            retry_exc = exc

        if attempt == _MAX_ATTEMPTS - 1:
            raise RuntimeError(
                f"Asana request failed after {_MAX_ATTEMPTS} attempts"
            ) from retry_exc
        if _TOTAL_SLEEP + delay > _MAX_TOTAL_SLEEP:
            raise RuntimeError(
                f"Asana retry sleep limit of {_MAX_TOTAL_SLEEP} seconds exceeded"
            ) from retry_exc
        _sleep(delay)
        _TOTAL_SLEEP += delay


def paginate(path, token, params=None):
    params = dict(params or {})
    params.setdefault("limit", 100)
    rows = []
    while True:
        response = request("GET", path, token, params=dict(params))
        rows.extend(response["data"])
        next_page = response.get("next_page")
        if not next_page:
            return rows
        params["offset"] = next_page["offset"]


def resolve_user_gid(value: str, token: str, workspace: str = None) -> str:
    """Accept a bare user gid or an email address and return the gid.

    A digit string is returned unchanged (already a gid); anything else is
    matched case-insensitively against the workspace users' emails. Raises
    SystemExit if no user matches: fail loud rather than silently pick the
    wrong person.
    """
    s = str(value).strip()
    if s.isdigit():
        return s
    users = paginate(
        f"/workspaces/{require_workspace(workspace)}/users", token,
        params={"opt_fields": "email,name"}
    )
    target = s.lower()
    match = next(
        (u for u in users if (u.get("email") or "").lower() == target), None
    )
    if not match:
        raise SystemExit(f"cannot resolve user email to a gid: {value!r}")
    return match["gid"]


def task_url(gid: str) -> str:
    return f"https://app.asana.com/0/0/{gid}/f"


def extract_task_gid(url_or_gid: str) -> str:
    """Accept a bare GID, a task URL, or a `focus=true` permalink."""
    s = str(url_or_gid).strip()
    if s.isdigit():
        return s
    m = re.search(r"/task/(\d+)", s)
    if m:
        return m.group(1)
    m = re.search(r"/0/\d+/(\d+)", s)
    if m:
        return m.group(1)
    m = re.search(r"(\d{10,})", s)
    if m:
        return m.group(1)
    raise ValueError(f"cannot extract task gid from: {url_or_gid!r}")


# An @mention notifies once but does not subscribe, so the person misses every
# later reply on the task. Every comment writer that can carry a mention adds
# the mentioned users as followers.
_ANCHOR_RE = re.compile(r"<a\b[^>]*>", re.IGNORECASE)
_GID_ATTR_RE = re.compile(r"""\bdata-asana-gid\s*=\s*["'](\d+)["']""", re.IGNORECASE)
_TYPE_ATTR_RE = re.compile(r"""\bdata-asana-type\s*=\s*["']([a-z_]+)["']""", re.IGNORECASE)


def mentioned_user_gids(html) -> list:
    """Gids of the @mentions in a comment body, in order, without repeats.

    An anchor typed as anything but a user (a task or project link, as Asana
    stores it) is skipped. An untyped anchor counts: that is how a mention is
    written before Asana expands it."""
    gids = []
    for tag in _ANCHOR_RE.findall(html or ""):
        gid = _GID_ATTR_RE.search(tag)
        if not gid:
            continue
        kind = _TYPE_ATTR_RE.search(tag)
        if kind and kind.group(1).lower() != "user":
            continue
        if gid.group(1) not in gids:
            gids.append(gid.group(1))
    return gids


def follow_mentions(task_gid, story_gid, html, token, request_fn=None) -> list:
    """Add everyone @mentioned in a posted comment as a follower of the task.

    Reads the posted story back so Asana's own expansion says which anchors are
    users, adds them in one addFollowers call (idempotent), then reads the
    followers back. Returns the gids that are still not following.

    Never raises: the comment is already live, so a miss prints PARTIAL to stderr
    and the caller must NOT post the comment again. Pass the caller's own
    `request` as request_fn, so a test that fakes it fakes these calls too.
    """
    req = request_fn or request
    gids = mentioned_user_gids(html)
    if not gids:
        return []
    try:
        story = req("GET", f"/stories/{story_gid}", token,
                    params={"opt_fields": "html_text"})
        gids = mentioned_user_gids(story["data"].get("html_text") or "")
    except Exception as exc:
        print(f"NOTE: could not read the comment back ({exc}); "
              "using the mentions as written", file=sys.stderr)
    if not gids:
        return []
    url = task_url(task_gid)
    try:
        req("POST", f"/tasks/{task_gid}/addFollowers", token,
            data={"data": {"followers": gids}})
    except Exception as exc:
        print(f"PARTIAL: comment posted on {url} but addFollowers failed ({exc}); "
              f"add them as followers by hand: {', '.join(gids)}. "
              "Do not post the comment again.", file=sys.stderr)
        return gids
    try:
        task = req("GET", f"/tasks/{task_gid}", token,
                   params={"opt_fields": "followers.name"})
        followers = {f.get("gid"): f.get("name") or f.get("gid")
                     for f in task["data"].get("followers") or []}
    except Exception as exc:
        print(f"PARTIAL: comment posted on {url} but the follower read-back failed "
              f"({exc}); check these are followers: {', '.join(gids)}. "
              "Do not post the comment again.", file=sys.stderr)
        return gids
    missing = [g for g in gids if g not in followers]
    following = [followers[g] for g in gids if g in followers]
    if following:
        print("Following: " + ", ".join(following))
    if missing:
        print(f"PARTIAL: comment posted on {url} but {', '.join(missing)} did not "
              "become a follower; add by hand. Do not post the comment again.",
              file=sys.stderr)
    return missing


_LIST_WS_RE = re.compile(
    r"(</li>|<ul[^>]*>|<ol[^>]*>)\s+(<li[^>]*>|</ul>|</ol>)",
    re.IGNORECASE,
)


def _compact_lists(html: str) -> str:
    """Strip whitespace between list-related tags.

    Asana renders newlines inside <ul>/<ol> verbatim, producing huge indents and
    blank lines between bullets. The fix: collapse whitespace at every <li>/<ul>/<ol>
    boundary before posting. Apply the regex repeatedly until stable to cover
    `</li>\\n  </li>` chains where each match consumes one boundary.
    """
    prev = None
    while prev != html:
        prev = html
        html = _LIST_WS_RE.sub(r"\1\2", html)
    return html


# Tags Asana accepts in BOTH html_notes (descriptions) and html_text (comments).
# Anything else fails: a description gets "400 XML is invalid" (<p>, <br>, <th>,
# <img>, <div>), and a COMMENT is accepted but silently stored as escaped plain
# text. See references/rich-text.md.
ALLOWED_TAGS = frozenset({
    "body", "strong", "em", "u", "s", "code", "a", "ul", "ol", "li",
    "blockquote", "pre", "h1", "h2", "h3", "hr", "table", "tr", "td",
})
_TAG_RE = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)")


def unsupported_tags(html: str) -> list:
    """Return the sorted tag names Asana rich text would reject (empty = safe)."""
    return sorted({t.lower() for t in _TAG_RE.findall(html or "")} - ALLOWED_TAGS)


def wrap_body(html: str) -> str:
    """Ensure html is wrapped in <body>...</body>. Asana requires it for rich text.

    Also compacts whitespace inside <ul>/<ol> so lists render as tight bullets
    (see _compact_lists for the why). Raises ValueError on a tag Asana would
    reject, because a comment with one is silently turned into escaped text.
    """
    bad = unsupported_tags(html)
    if bad:
        raise ValueError(
            "unsupported Asana rich-text tag(s): " + ", ".join(f"<{t}>" for t in bad)
            + ". Use real newlines instead of <p>/<br>, and <td><strong> instead of <th>."
        )
    html = _compact_lists(html.strip())
    if html.startswith("<body"):
        return html
    return f"<body>{html}</body>"


# Author line. A personal access token makes Asana show the PERSON as the
# author, so a reader cannot tell an agent wrote the text. Comments and
# descriptions written with a person's token start with "Written by
# <author_label> for <first name>." (author_label defaults to Claude). An agent
# account (a gid in agent_user_gids) already shows the agent in its own name,
# so it gets no line.
_BODY_OPEN_RE = re.compile(r"^<body[^>]*>", re.IGNORECASE)
_BODY_TAG_RE = re.compile(r"</?body[^>]*>", re.IGNORECASE)


def is_empty_body(body) -> bool:
    """True when a body holds nothing once its <body> wrapper and whitespace go.
    Any other tag counts as content: a body that is only an @-mention is real."""
    return not _BODY_TAG_RE.sub("", body or "").strip()


# An attribution line STARTS with "Written by <author_label>" (or the default
# "Written by Claude"), after at most a short "[QA update -" style prefix. A
# sentence that only mentions the phrase is not one.
def author_line_re():
    """The pattern for an existing author line, built from AUTHOR_LABEL."""
    labels = {"claude", AUTHOR_LABEL.lower()}
    alt = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    return re.compile(rf"^[\[(\s]*(?:[^\]\n]{{0,40}}?[-:]\s*)?written by (?:{alt})(?!\w)",
                      re.IGNORECASE)


def starts_with_author_line(text: str) -> bool:
    """True when the first 300 characters (tags stripped) open with an author
    line. For dry-run reports and read-backs."""
    plain = re.sub(r"<[^>]+>", "\n", (text or "")[:300])
    first = next((line.strip() for line in plain.splitlines() if line.strip()), "")
    return bool(author_line_re().match(first[:160]))


def _first_word(name) -> str:
    parts = str(name or "").split()
    return parts[0] if parts else ""


def author_line(token: str) -> str:
    """Return "Written by Claude for <first name>." when this token posts as a
    person, else "" (an agent account).

    Every token is looked up once per process with GET /users/me, whatever
    the config holds. An agent account (a gid in agent_user_gids) gets no
    line. Every other login gets one. A failed lookup warns on stderr and
    returns the line: an extra line is cheaper than an agent post that reads
    as human.
    """
    if token in _AUTHOR_CACHE:
        return _AUTHOR_CACHE[token]
    try:
        me = request("GET", "/users/me", token,
                     params={"opt_fields": "gid,name,email"})["data"]
    except Exception as exc:
        print(f"WARNING: could not read who this token belongs to ({type(exc).__name__}); "
              "adding the author line to be safe.", file=sys.stderr)
        me = None
    if me is None:
        first = _first_word(MY_NAME)
    elif _is_agent_account(me):
        first = None
    else:
        if (MY_USER_GID or MY_EMAIL) and not _is_configured_person(me):
            _note_other_login(me)
        first = _first_word(me.get("name") or MY_NAME)
    if first is None:
        line = ""
    elif first:
        line = f"Written by {AUTHOR_LABEL} for {first}."
    else:
        line = f"Written by {AUTHOR_LABEL}."
    _AUTHOR_CACHE[token] = line
    return line


def _is_agent_account(me: dict) -> bool:
    return str(me.get("gid") or "") in AGENT_USER_GIDS


def _is_configured_person(me: dict) -> bool:
    if MY_USER_GID:
        return me.get("gid") == MY_USER_GID
    return (me.get("email") or "").strip().lower() == MY_EMAIL.lower()


def _note_other_login(me: dict) -> None:
    """Say which login the line is for when it is not the configured person."""
    name = str(me.get("name") or "")
    print(
        f"NOTE: this token posts as {name or me.get('gid')} "
        f"<{me.get('email') or 'no email'}>, not user_gid, so the author "
        "line names that login. If it is an automation account, add its gid to "
        f"agent_user_gids in {CONFIG_PATH}.",
        file=sys.stderr,
    )


def _has_author_line(body: str) -> bool:
    """True when the first line of the body already says an agent wrote it.
    Only the first line counts: a summary that mentions the "Written by Claude"
    rule is not an author line."""
    plain = re.sub(r"<[^>]+>", "\n", body or "")
    first = next((line.strip() for line in plain.splitlines() if line.strip()), "")
    return bool(author_line_re().match(first[:160]))


def add_author_line(html_body: str, token: str) -> str:
    """Put the italic author line at the top of an HTML fragment or a
    <body>-wrapped body. Unchanged when no line applies or one is there."""
    if is_empty_body(html_body):
        return html_body
    line = author_line(token)
    if not line or _has_author_line(html_body):
        return html_body
    tag = f"<em>{html.escape(line, quote=False)}</em>\n"
    s = (html_body or "").strip()
    m = _BODY_OPEN_RE.match(s)
    if m:
        return s[:m.end()] + tag + s[m.end():]
    return tag + s


def add_author_line_text(text: str, token: str) -> str:
    """Plain-text form of add_author_line, for `text` / `notes` fields."""
    if not (text or "").strip():
        return text
    line = author_line(token)
    if not line or _has_author_line(text):
        return text
    return f"{line}\n{text}"


def mark_task_data(data: dict, token: str) -> dict:
    """Add the author line to a task payload's description in place.
    A task with no description stays without one."""
    if data.get("html_notes"):
        data["html_notes"] = add_author_line(data["html_notes"], token)
    elif data.get("notes"):
        data["notes"] = add_author_line_text(data["notes"], token)
    return data


# Comment shape: a plain-English summary first, technical details below an
# <hr>, and every file, doc or task named as an inline link. A wall of text with
# no <hr> is refused.
WALL_CHARS = 500
SUMMARY_CHARS = 400
_TAGS_RE = re.compile(r"<[^>]+>")
_HR_RE = re.compile(r"<hr\s*/?>", re.IGNORECASE)
_LINK_RE = re.compile(r"<a\s[^>]*href=", re.IGNORECASE)
_FILEISH_RE = re.compile(
    r"(?<![\w/])(?:[\w.-]+/)*[\w-]+\.(?:md|pdf|csv|xlsx?|docx?|pptx?|json|py|html?|png|jpe?g)\b",
    re.IGNORECASE)


def _plain_len(html_fragment: str) -> int:
    text = html.unescape(_TAGS_RE.sub(" ", html_fragment or ""))
    return len(" ".join(text.split()))


def shape_problems(body: str, is_html: bool = True):
    """Check a comment body against the comment shape.

    Returns (blocking, warnings): two lists of one-line messages. A blocking
    problem stops a live post unless the caller passes --skip-shape-check."""
    blocking, warnings = [], []
    if not is_html:
        if _plain_len(html.escape(body or "", quote=False)) > WALL_CHARS:
            blocking.append(
                f"plain-text comment over {WALL_CHARS} characters: write it as HTML "
                "(--html-file) with a plain-English summary, an <hr>, then the details")
        return blocking, warnings
    parts = _HR_RE.split(body or "", maxsplit=1)
    if len(parts) == 1:
        if _plain_len(body) > WALL_CHARS:
            blocking.append(
                f"comment over {WALL_CHARS} characters with no <hr>: lead with a "
                "plain-English summary, then put the technical details below an <hr>")
    elif _plain_len(parts[0]) > SUMMARY_CHARS:
        warnings.append(
            f"the summary above the <hr> is {_plain_len(parts[0])} characters "
            f"(aim for under {SUMMARY_CHARS}): move detail below the <hr>")
    plain = html.unescape(_TAGS_RE.sub(" ", body or ""))
    if _FILEISH_RE.search(plain) and not _LINK_RE.search(body or ""):
        warnings.append(
            "the comment names a file but has no link: name every file, doc or "
            'task as <a href="...">name</a>')
    return blocking, warnings
