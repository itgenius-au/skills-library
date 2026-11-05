#!/usr/bin/env python3
"""
google-chat-update helper - generic, config-driven Google Chat write layer.

Identity is read from ~/.claude/google-chat-update.config.json (a flat JSON
object; copy templates/google-chat-update.config.example.json and fill it in),
never hardcoded. Set GOOGLE_CHAT_UPDATE_CONFIG to use another path. Several
auth paths, all optional depending on what you configure:

  READ         admin SA + DWD impersonating you        -> find a thread
  WRITE bot    bot SA  + chat.bot                       -> post as your bot
  WRITE self   admin SA + DWD + chat.messages.create    -> post as you
  REACT self   personal OAuth / gcloud ADC / admin DWD  -> react as you (chat.messages)
  DELETE self  admin SA + DWD + chat.messages           -> delete YOUR OWN message

Config keys (top level of the config file):
  gcp_project             DEFAULT Secret Manager project holding your chat SA
                          keys. Optional if BOTH per-secret project overrides
                          below are set.
  bot_sa_secret           chat.bot service-account key secret (write as bot)
  bot_sa_project          Secret Manager project for bot_sa_secret (optional; overrides
                          gcp_project - use when the bot key lives in a
                          different project from the admin key)
  bot_display_name        expected sender display name for a bot post
  bot_user_id             "users/NNN" - your bot's user id (optional, for docs)
  admin_sa_secret         admin/DWD service-account key secret (read + write-self)
  admin_sa_project        Secret Manager project for admin_sa_secret (optional; overrides
                          gcp_project)
  dwd_subject             the email the admin SA impersonates (usually yours)
  self_user_id            "users/NNN" - your own Chat user id (write-self check)
  default_write_identity  "bot" or "self" (default "bot")
  gcloud_account          optional: the gcloud account that reads the secrets
                          (pins --account on a multi-account machine)

Subcommands:
  list  <space>                       [--limit N]
  search <space> <term> [--term T]... [--since YYYY-MM-DD] [--max-pages N]
                                      (pages the space's FULL history back to --since,
                                       default 180 days; run it before any top-level post)
  find  [--days N] [--per N] [--top N]
                                      (read-only: lists EVERY space, keeps those active in the last
                                       N days (default 3), shows the newest --top (default 20) with
                                       their latest --per (default 3) messages. Finds group chats,
                                       which have no displayName and so cannot be found by name)
  members <space> [--emails]          (read-only: who can read a space, incl. invited members and
                                       unexpanded groups; --emails resolves each human's email via
                                       the Directory API. Admin SA + DWD, chat.memberships.readonly,
                                       falling back to chat.memberships)
  whois <users/ID> [<users/ID> ...]   (read-only: resolves each Chat user id to primary email, full
                                       name, org unit and suspended flag through the Admin Directory
                                       API. Admin SA + DWD, admin.directory.user.readonly. Identify a
                                       sender by this, never by Chat display name)
  read-thread <thread_name> [--full] [--json]
                                      (read-only: every message of ONE thread, oldest first, all
                                       pages, with attachment metadata and reaction counts. Downloads
                                       nothing. --json prints each raw message. Admin SA + DWD)
  who-reacted <message_name>          (read-only: every reaction on one message - emoji, user id,
                                       user type - all pages, then a `whois` line for the humans)
  post  <space>      [text | --text-file PATH|-]  [--identity bot|self] [--dry-run]
  reply <thread_name> [text | --text-file PATH|-] [--identity bot|self] [--dry-run]
                                      (give the text positionally OR via --text-file, a path or
                                       `-` for stdin; exactly one. Trailing newlines are stripped
                                       from --text-file; positional text is sent as given)
  react <message_name>     [emoji]    [--dry-run]   (reacts AS YOU on ONE message; emoji default 👁)
  react-opener <thread_name> [emoji]  [--dry-run]   (reacts AS YOU on the thread's OPENING
                                                     message, but only if your own emoji is not
                                                     already there; emoji default 👁)
  delete <message_name>   [--yes] [--dry-run]
                                      (deletes ONE of YOUR OWN messages: admin SA + DWD, chat.messages.
                                       Refuses any other sender. Without --yes it only previews.
                                       Verifies by listing the thread, never by waiting for a 404)

Config keys for react (top level of the config file):
  react_emoji             the operator's pick (default 👁); per-teammate
  personal_oauth_secret   (A) Secret Manager secret with a user OAuth {client_id,client_secret,refresh_token}
  personal_token_source   (B) "gcloud-adc" -> use `gcloud auth application-default print-access-token`
  react_token_source      optional: force "personal_oauth" | "gcloud-adc" | "admin_dwd"

The helper does NOT enforce the approval gate or the resolved-thread check -
those live in SKILL.md and are the caller's responsibility. Don't bypass them.
"""

from __future__ import annotations  # `str | None` hints on Python 3.9

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

CONFIG_PATH = os.path.expanduser(
    os.environ.get("GOOGLE_CHAT_UPDATE_CONFIG") or "~/.claude/google-chat-update.config.json"
)
TEMPLATE_HINT = (
    "copy templates/google-chat-update.config.example.json (in this skill's folder) to "
    f"{CONFIG_PATH} and fill in your own values"
)

READ_SCOPES = [
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
]
BOT_SCOPES = ["https://www.googleapis.com/auth/chat.bot"]
SELF_WRITE_SCOPES = ["https://www.googleapis.com/auth/chat.messages.create"]
# A reaction needs the BROAD chat.messages scope. NOT chat.messages.create (that
# posts messages but cannot react), and NOT the narrow chat.messages.reactions.create
# (often not in a DWD grant). See the react docs in SKILL.md.
REACT_SCOPES = ["https://www.googleapis.com/auth/chat.messages"]
# A delete needs the same BROAD chat.messages scope (chat.messages.create cannot delete;
# verified live).
DELETE_SCOPES = ["https://www.googleapis.com/auth/chat.messages"]
# `members`: the narrow readonly scope first; some DWD grants only have the broad one
# (verified 2026-10-30), so members_token() falls back to it.
MEMBERS_SCOPE = "https://www.googleapis.com/auth/chat.memberships.readonly"
MEMBERS_SCOPE_BROAD = "https://www.googleapis.com/auth/chat.memberships"
DIRECTORY_SCOPE = "https://www.googleapis.com/auth/admin.directory.user.readonly"


def _is_placeholder(value) -> bool:
    """True for a template value that was never filled in: one that STARTS with
    "your_" or "users/your_", or the template's you@example.com. A real value
    that only contains "your_" is kept."""
    if not isinstance(value, str):
        return False
    v = value.strip()
    return v.startswith(("your_", "users/your_")) or v == "you@example.com"


def load_config() -> tuple[dict, str, set]:
    """Read the flat config. Returns (values, status, placeholder_keys).

    status is "ok", "missing" (no file) or "invalid" (unreadable, bad JSON, or
    not a JSON object). Template placeholders are dropped from the values and
    listed in placeholder_keys, so an unfilled key reads as unset.
    """
    try:
        with open(CONFIG_PATH) as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}, "missing", set()
    except (OSError, ValueError):
        return {}, "invalid", set()
    if not isinstance(raw, dict):
        return {}, "invalid", set()
    placeholders = {k for k, v in raw.items() if _is_placeholder(v)}
    values = {k: v for k, v in raw.items() if k not in placeholders and not k.startswith("_")}
    return values, "ok", placeholders


CHAT, CONFIG_STATUS, PLACEHOLDER_KEYS = load_config()


def _config_exit(message: str) -> None:
    """Exit 2 with a friendly config-fix message."""
    print(message, file=sys.stderr)
    sys.exit(2)


def _require(key: str) -> str:
    """Return the config value for <key>, or exit 2 with a config-fix message."""
    val = CHAT.get(key)
    if val:
        return val
    if CONFIG_STATUS == "missing":
        _config_exit(f"No config file at {CONFIG_PATH}. To set it up, {TEMPLATE_HINT}.")
    if CONFIG_STATUS == "invalid":
        _config_exit(f"{CONFIG_PATH} is not a readable JSON object. Fix it, or {TEMPLATE_HINT}.")
    if key in PLACEHOLDER_KEYS:
        _config_exit(f"`{key}` in {CONFIG_PATH} still holds the template placeholder. "
                     "Replace it with your own value.")
    _config_exit(
        f"Missing `{key}` in {CONFIG_PATH}. Add it (the template lists every key: "
        "templates/google-chat-update.config.example.json), or, if your setup has no "
        "such identity, use a write path you do have."
    )
    return ""  # not reached


def _load_sa_key(secret_name: str, project: str | None = None) -> dict:
    # `project` is the per-secret override (bot_sa_project / admin_sa_project);
    # it falls back to the shared gcp_project. This lets the bot SA key and the
    # admin SA key live in DIFFERENT Secret Manager projects (e.g. a personal bot
    # key in your own project + a shared admin SA key in the org project).
    project = project or CHAT.get("gcp_project")
    if not project:
        _config_exit(
            f"No Secret Manager project for secret {secret_name!r}. Set `gcp_project` "
            "(shared default) or the matching per-secret override "
            f"(`bot_sa_project` / `admin_sa_project`) in {CONFIG_PATH}."
        )
    cmd = [
        (shutil.which("gcloud") or "gcloud"), "secrets", "versions", "access", "latest",
        f"--secret={secret_name}",
        f"--project={project}",
    ]
    # Pin the operator's gcloud account when configured, so a multi-account
    # workstation reads the secret as the right identity. Harmless if the
    # active account already matches. Unset: use the active account.
    account = CHAT.get("gcloud_account")
    if account:
        cmd.append(f"--account={account}")
    where = (f"secret {secret_name!r} in project {project!r} "
             f"as {account or 'the active gcloud account'}")
    try:
        # stderr is captured so a gcloud error is shown once, below; stdout (the
        # key) is never printed.
        raw = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE)
    except FileNotFoundError:
        _config_exit(f"gcloud not found, so {where} cannot be read. Install the Google Cloud CLI.")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        _config_exit(f"Could not read {where}: {detail[-1] if detail else 'gcloud failed'}. "
                     "Check the secret name, the project, and that this account can read it.")
    try:
        return json.loads(raw)
    except ValueError:
        _config_exit(f"{where} is not a JSON key file. It must hold the whole service account "
                     "key (or the OAuth JSON) as JSON.")


def read_token() -> str:
    """Token for listing/getting messages (admin SA, DWD impersonating you)."""
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    creds = service_account.Credentials.from_service_account_info(
        _load_sa_key(_require("admin_sa_secret"), CHAT.get("admin_sa_project")),
        scopes=READ_SCOPES,
    ).with_subject(_require("dwd_subject"))
    creds.refresh(Request())
    return creds.token


def bot_write_token() -> str:
    """Token for posting as your bot identity (app auth, no DWD)."""
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    creds = service_account.Credentials.from_service_account_info(
        _load_sa_key(_require("bot_sa_secret"), CHAT.get("bot_sa_project")),
        scopes=BOT_SCOPES,
    )
    creds.refresh(Request())
    return creds.token


def self_write_token() -> str:
    """Token for posting AS YOU (admin SA, DWD, chat.messages.create)."""
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    creds = service_account.Credentials.from_service_account_info(
        _load_sa_key(_require("admin_sa_secret"), CHAT.get("admin_sa_project")),
        scopes=SELF_WRITE_SCOPES,
    ).with_subject(_require("dwd_subject"))
    creds.refresh(Request())
    return creds.token


def delete_token() -> str:
    """Token for deleting YOUR OWN message (admin SA, DWD, broad chat.messages)."""
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    creds = service_account.Credentials.from_service_account_info(
        _load_sa_key(_require("admin_sa_secret"), CHAT.get("admin_sa_project")),
        scopes=DELETE_SCOPES,
    ).with_subject(_require("dwd_subject"))
    creds.refresh(Request())
    return creds.token


# --- react (pickup emoji) ---------------------------------------------------
# The react posts AS THE OPERATOR (never the bot). The token source is chosen
# from config so the same skill runs for anyone:
#   personal_oauth  (A) - personal_oauth_secret: a stored user OAuth refresh
#                         token (client_id/client_secret/refresh_token) -> user token
#   gcloud-adc      (B) - personal_token_source == "gcloud-adc": the operator's
#                         own ADC token (they consented chat.messages)
#   admin_dwd           - admin_sa_secret + dwd_subject: DWD mint as self
# Auto precedence is personal_oauth > gcloud-adc > admin_dwd; react_token_source
# forces one. All mint the BROAD chat.messages scope (REACT_SCOPES).

def resolve_react_emoji(arg: str | None, chat: dict | None = None) -> str:
    """CLI arg > react_emoji > default 👁."""
    chat = CHAT if chat is None else chat
    return arg or chat.get("react_emoji") or "👁"


def _react_plan_builders(chat: dict) -> dict:
    def personal_oauth():
        secret = chat.get("personal_oauth_secret")
        return {"source": "personal_oauth", "secret": secret} if secret else None

    def gcloud_adc():
        return {"source": "gcloud-adc"} if chat.get("personal_token_source") == "gcloud-adc" else None

    def admin_dwd():
        secret, subject = chat.get("admin_sa_secret"), chat.get("dwd_subject")
        return {"source": "admin_dwd", "secret": secret, "subject": subject} if (secret and subject) else None

    return {"personal_oauth": personal_oauth, "gcloud-adc": gcloud_adc, "admin_dwd": admin_dwd}


def resolve_react_plan(chat: dict | None = None) -> dict:
    """Pick the self-react token source from config. Raises SystemExit (actionable)
    if a forced source is misconfigured or nothing is configured."""
    chat = CHAT if chat is None else chat
    builders = _react_plan_builders(chat)
    forced = chat.get("react_token_source")
    if forced:
        if forced not in builders:
            raise SystemExit(
                f"react_token_source must be one of {sorted(builders)}, got {forced!r}"
            )
        plan = builders[forced]()
        if plan is None:
            raise SystemExit(
                f"react_token_source={forced!r} but its config is missing "
                "(personal_oauth needs personal_oauth_secret; gcloud-adc needs "
                'personal_token_source="gcloud-adc"; admin_dwd needs admin_sa_secret + dwd_subject).'
            )
        return plan
    for name in ("personal_oauth", "gcloud-adc", "admin_dwd"):  # auto precedence
        plan = builders[name]()
        if plan:
            return plan
    raise SystemExit(
        f"No self-react credential configured in {CONFIG_PATH}. Set one of: "
        "personal_oauth_secret (A), personal_token_source=\"gcloud-adc\" (B), "
        "or admin_sa_secret + dwd_subject."
    )


def reactions_url(message: str) -> str:
    """Reactions collection URL for a message resource name (thread.msg dot-joined)."""
    return f"https://chat.googleapis.com/v1/{message}/reactions"


def react_body(emoji: str) -> dict:
    return {"emoji": {"unicode": emoji}}


def react_token(plan: dict) -> str:
    """Mint a chat.messages token for the resolved react plan (react as the operator)."""
    from google.auth.transport.requests import Request

    src = plan["source"]
    if src == "admin_dwd":
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(
            _load_sa_key(plan["secret"], CHAT.get("admin_sa_project")),
            scopes=REACT_SCOPES,
        ).with_subject(plan["subject"])
        creds.refresh(Request())
        return creds.token
    if src == "personal_oauth":
        from google.oauth2.credentials import Credentials

        info = _load_sa_key(plan["secret"])  # {client_id, client_secret, refresh_token}
        missing = [k for k in ("client_id", "client_secret", "refresh_token") if not info.get(k)]
        if missing:
            raise SystemExit(
                f"personal_oauth_secret ({plan['secret']}) is missing {missing}. It must hold a "
                "user OAuth JSON with client_id, client_secret, and refresh_token consented for "
                "chat.messages."
            )
        creds = Credentials(
            None,
            refresh_token=info["refresh_token"],
            client_id=info["client_id"],
            client_secret=info["client_secret"],
            token_uri="https://oauth2.googleapis.com/token",
            scopes=REACT_SCOPES,
        )
        creds.refresh(Request())
        return creds.token
    if src == "gcloud-adc":
        try:
            out = subprocess.check_output(
                [(shutil.which("gcloud") or "gcloud"), "auth", "application-default",
                 "print-access-token"], text=True, stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            _config_exit("gcloud not found, so the gcloud-adc react token cannot be read. "
                         "Install the Google Cloud CLI.")
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip().splitlines()
            _config_exit("Could not read a gcloud-adc token: "
                         f"{detail[-1] if detail else 'gcloud failed'}. "
                         "Run: gcloud auth application-default login")
        return out.strip()
    raise SystemExit(f"unknown react token source {src!r}")


def _http(method: str, url: str, token: str, body: dict | None = None,
          tolerate: tuple = ()) -> dict:
    """HTTP JSON call. On an HTTP error whose status is in `tolerate`, return a
    sentinel `{"__tolerated__": <code>}` instead of hard-exiting - used so a
    duplicate-reaction create (an already-exists response) is treated as success
    rather than a failure. Any other error still exits non-zero (loud)."""
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        if e.code in tolerate:
            return {"__tolerated__": e.code}
        sys.stderr.write(f"HTTP {e.code} {e.reason}: {e.read().decode()}\n")
        sys.exit(1)
    except urllib.error.URLError as e:
        # Network/DNS/timeout - no response, so nothing was posted on a POST.
        sys.stderr.write(f"Network error reaching Chat API: {e.reason}\n")
        sys.exit(1)


def _resolve_identity(arg: str | None) -> str:
    ident = arg or CHAT.get("default_write_identity") or "bot"
    if ident not in ("bot", "self"):
        raise SystemExit(f"--identity must be 'bot' or 'self', got {ident!r}")
    return ident


def _write_token(identity: str) -> str:
    return bot_write_token() if identity == "bot" else self_write_token()


def _verify_sender(resp: dict, identity: str, allow_unverified: bool = False) -> None:
    """Confirm the post landed under the intended identity.

    The message is ALREADY posted by the time we get here. A wrong or
    unverifiable sender is a real failure - the post is live under the wrong
    name - so we exit non-zero (loud), NOT a warning the caller can miss.
    `--allow-unverified` downgrades a missing-config case to a warning.
    Prefer the immutable `*_user_id` over the mutable display name.
    """
    sender = resp.get("sender") or {}
    disp = sender.get("displayName")
    name = sender.get("name")
    print(f"Posted: {resp.get('name')}")
    print(f"Thread: {(resp.get('thread') or {}).get('name')}")
    print(f"Sender: {disp or name}")

    if identity == "bot":
        exp_id = CHAT.get("bot_user_id")
        exp_name = CHAT.get("bot_display_name")
        remedy = "bot_sa_secret / scope"
    else:  # self
        exp_id = CHAT.get("self_user_id")
        exp_name = None
        remedy = "admin_sa_secret / dwd_subject"

    if exp_id:
        ok = name == exp_id
    elif exp_name:
        ok = disp == exp_name
    else:
        ok = None  # nothing configured to check against

    if ok:
        return
    if ok is None:
        msg = (
            f"cannot verify the {identity} sender: set "
            f"{'bot_user_id/bot_display_name' if identity == 'bot' else 'self_user_id'} "
            f"in {CONFIG_PATH} to confirm identity."
        )
    else:
        expected = exp_id or exp_name
        msg = (
            f"posted as {name!r} / {disp!r}, NOT the configured {identity} "
            f"identity {expected!r}. The message IS live under the wrong sender - "
            f"delete it and fix {remedy}; do NOT blind-retry."
        )
    if allow_unverified and ok is None:
        sys.stderr.write(f"WARNING: {msg}\n")
        return
    sys.stderr.write(f"IDENTITY CHECK FAILED: {msg}\n")
    sys.exit(3)


def _verify_reaction(resp: dict, chat: dict | None = None) -> None:
    """Print the landed reaction and, when self_user_id is configured, confirm it
    posted as the operator. The reaction is ALREADY live by now, so a mismatch is a
    loud non-zero exit, not a warning."""
    chat = CHAT if chat is None else chat
    user = (resp.get("user") or {}).get("name")
    emoji = (resp.get("emoji") or {}).get("unicode")
    print(f"Reacted: {emoji} on {resp.get('name')}")
    print(f"As: {user}")
    expect = chat.get("self_user_id")
    if not expect or not user:
        # Cannot confirm the author. Do not silently pass (a wrong-account gcloud-ADC
        # token would post under the wrong identity) - warn loudly, but the marker is
        # already live so this is not a hard failure.
        why = "self_user_id is not set" if not expect else "the API response carried no user"
        sys.stderr.write(
            f"WARNING: could not verify the react identity ({why}); the reaction is live "
            "but its author was NOT confirmed as you. Set self_user_id to enable the check.\n"
        )
        return
    if user != expect:
        sys.stderr.write(
            f"IDENTITY CHECK FAILED: reaction posted as {user!r}, NOT the configured "
            f"self_user_id {expect!r}. It IS live under the wrong identity - remove it "
            "and fix the react token source; do NOT blind-retry.\n"
        )
        sys.exit(3)


def cmd_list(args):
    qs = urllib.parse.urlencode({"pageSize": args.limit, "orderBy": "createTime desc"})
    url = f"https://chat.googleapis.com/v1/{args.space}/messages?{qs}"
    d = _http("GET", url, read_token())
    for m in d.get("messages", []):
        sender = (m.get("sender") or {}).get("name", "")
        text = (m.get("text") or m.get("formattedText") or "").replace("\n", " / ")
        if not getattr(args, "full", False):
            text = text[:200]
        # Print the FULL message and thread resource names - reply/react flows
        # need `name` (message) and `thread.name` verbatim; don't truncate them.
        name = m.get("name", "")
        thread = (m.get("thread") or {}).get("name", "")
        print(f"{m.get('createTime')} | name={name} | thread={thread} | sender={sender} | {text}")


SEARCH_DEFAULT_DAYS = 180
SEARCH_PAGE_SIZE = 1000


def valid_space_name(space: str) -> bool:
    """A Chat space resource name is spaces/<S> with a URL-safe id."""
    parts = space.split("/")
    return len(parts) == 2 and parts[0] == "spaces" and _valid_id(parts[1])


def search_since_iso(since: str | None, today=None) -> str:
    """Return the RFC 3339 lower bound for a search. `since` is YYYY-MM-DD; None
    means SEARCH_DEFAULT_DAYS before today (UTC)."""
    import datetime as _dt
    if since:
        try:
            d = _dt.date.fromisoformat(since)
        except ValueError:
            raise SystemExit(f"--since must be YYYY-MM-DD, got {since!r}")
    else:
        today = today or _dt.datetime.now(_dt.timezone.utc).date()
        d = today - _dt.timedelta(days=SEARCH_DEFAULT_DAYS)
    return f"{d.isoformat()}T00:00:00Z"


def search_messages_url(space: str, since_iso: str, page_token: str | None = None) -> str:
    """One page of a space's messages newer than since_iso, newest first."""
    q = {
        "filter": f'createTime > "{since_iso}"',
        "orderBy": "createTime desc",
        "pageSize": SEARCH_PAGE_SIZE,
    }
    if page_token:
        q["pageToken"] = page_token
    return f"https://chat.googleapis.com/v1/{space}/messages?{urllib.parse.urlencode(q)}"


def message_matches(msg: dict, terms: list[str]) -> bool:
    """Case-insensitive substring match of any term on the message text."""
    hay = f"{msg.get('text') or ''}\n{msg.get('formattedText') or ''}".lower()
    return any(t.lower() in hay for t in terms if t)


def cmd_search(args):
    """Find every message about a topic in the space's FULL history (not just the
    newest page), so a caller can prove whether a thread already exists before it
    starts a new top-level one. A `list --limit 100` + grep misses older threads,
    and a duplicate top-level post follows."""
    if not valid_space_name(args.space):
        sys.exit(f"Invalid space name: {args.space!r}. Expected spaces/<SPACE_ID>")
    if args.max_pages < 1:
        sys.exit(f"--max-pages must be 1 or more, got {args.max_pages}")
    terms = [args.term] + list(args.terms or [])
    since_iso = search_since_iso(args.since)
    token = read_token()
    scanned, pages, oldest, page_token, capped = 0, 0, None, None, False
    threads: dict[str, int] = {}
    while True:
        d = _http("GET", search_messages_url(args.space, since_iso, page_token), token)
        pages += 1
        for m in d.get("messages", []):
            scanned += 1
            ct = m.get("createTime")
            if ct:
                # Results are newest first, so the last one seen is the oldest. (A raw
                # string compare of RFC 3339 times mis-orders fractional seconds.)
                oldest = ct
            if not message_matches(m, terms):
                continue
            thread = (m.get("thread") or {}).get("name", "")
            threads[thread] = threads.get(thread, 0) + 1
            sender = (m.get("sender") or {}).get("name", "")
            text = (m.get("text") or m.get("formattedText") or "").replace("\n", " / ")[:200]
            print(f"{ct} | name={m.get('name', '')} | thread={thread} | sender={sender} | {text}")
        page_token = d.get("nextPageToken")
        if not page_token:
            break
        if pages >= args.max_pages:
            capped = True
            break
    hits = sum(threads.values())
    print(f"SEARCHED {scanned} messages in {args.space} since {since_iso} "
          f"(oldest seen {oldest or 'none'}); terms={terms}; "
          f"matches={hits} in {len(threads)} thread(s)")
    for t, n in sorted(threads.items(), key=lambda kv: -kv[1]):
        print(f"THREAD {t} ({n} match{'es' if n != 1 else ''})")
    if capped:
        print(f"WARNING: stopped at --max-pages {args.max_pages}; older messages were NOT searched.")
    if scanned == 0:
        print("WARNING: 0 messages searched. Check the space name and your access: "
              "this is not proof that no thread exists.")


# --- find: recent spaces + their latest messages (read-only) -------------------------
# Why it exists: group chats have an empty displayName, so a name search cannot find
# them; recent activity can (in a large domain only a small share of spaces is active
# in any 3-day window).

_RFC3339 = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})$")


def parse_rfc3339(s) -> "datetime.datetime":
    """Parse an RFC 3339 time (Z or offset, fractional seconds of any length) to an
    aware datetime. Raises ValueError. Never compare the raw strings: '...00.5Z' sorts
    before '...00.25Z' as text but is later in time."""
    m = _RFC3339.match(s) if isinstance(s, str) else None
    if not m:
        raise ValueError(f"not an RFC 3339 time: {s!r}")
    y, mo, d, h, mi, sec, frac, tz = m.groups()
    micro = int(((frac or "") + "000000")[:6])
    if tz in ("Z", "z"):
        tzinfo = datetime.timezone.utc
    else:
        sign = -1 if tz[0] == "-" else 1
        tzinfo = datetime.timezone(sign * datetime.timedelta(hours=int(tz[1:3]), minutes=int(tz[4:6])))
    return datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec), micro, tzinfo=tzinfo)


def _space_active_time(space: dict):
    """The space's lastActiveTime as a datetime, or None if missing/unparseable."""
    try:
        return parse_rfc3339(space.get("lastActiveTime"))
    except ValueError:
        return None


def recent_spaces(spaces: list, now, days: int) -> list:
    """Spaces active within `days` of `now`, newest first. Spaces with no or an
    unparseable lastActiveTime are left out (cmd_find counts them)."""
    cutoff = now - datetime.timedelta(days=days)
    keep = []
    for s in spaces:
        t = _space_active_time(s)
        if t is not None and t >= cutoff:
            keep.append((t, s))
    keep.sort(key=lambda ts: ts[0], reverse=True)
    return [s for _, s in keep]


def spaces_list_url(page_token: str | None = None) -> str:
    q = {"pageSize": 1000}
    if page_token:
        q["pageToken"] = page_token
    return f"https://chat.googleapis.com/v1/spaces?{urllib.parse.urlencode(q)}"


# One space's unreadable or briefly failing message read must not abort the whole scan.
FIND_READ_TOLERATED = (403, 404, 429, 500, 502, 503, 504)


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def cmd_find(args):
    for flag in ("days", "per", "top"):
        if getattr(args, flag) < 1:
            sys.exit(f"--{flag} must be 1 or more, got {getattr(args, flag)}")
    token = read_token()
    spaces, page_token = [], None
    while True:  # list EVERY space: a name or recency filter is applied locally
        d = _http("GET", spaces_list_url(page_token), token)
        spaces.extend(d.get("spaces", []))
        page_token = d.get("nextPageToken")
        if not page_token:
            break
    skipped = sum(1 for s in spaces if _space_active_time(s) is None)
    recent = recent_spaces(spaces, _utcnow(), args.days)
    shown = recent[:args.top]
    for s in shown:
        name = s.get("name", "")
        label = s.get("displayName") or "(no name: group chat or DM)"
        print(f"SPACE {name} | {s.get('spaceType', '')} | {label} | last {s.get('lastActiveTime')}")
        qs = urllib.parse.urlencode({"pageSize": args.per, "orderBy": "createTime desc"})
        d = _http("GET", f"https://chat.googleapis.com/v1/{name}/messages?{qs}", token,
                  tolerate=FIND_READ_TOLERATED)
        if d.get("__tolerated__"):
            print(f"  READ ERROR {d['__tolerated__']}")
            continue
        for m in reversed(d.get("messages", [])):  # API returns newest first; print oldest first
            sender = m.get("sender") or {}
            text = (m.get("text") or m.get("formattedText") or "").replace("\n", " / ")[:160]
            att = len(m.get("attachment") or [])
            extra = f" [+{att} att]" if att else ""
            print(f"  {m.get('createTime')} | sender={sender.get('name', '')} "
                  f"{sender.get('displayName', '')} | {text} | "
                  f"thread={(m.get('thread') or {}).get('name', '')}{extra}")
    print(f"FOUND {len(recent)} space(s) active in the last {args.days} day(s) of "
          f"{len(spaces)} listed; showed {len(shown)}; skipped {skipped} with no or an invalid lastActiveTime")
    if not spaces:
        print("WARNING: 0 spaces listed. Check the admin DWD config: this is not proof that no space exists.")


# --- members: who can read a space (read-only) ---------------------------------------

def _mint(key: dict, scopes: list, subject: str) -> str:
    """Mint a DWD access token for `subject` from the admin SA key. Split out so tests
    can stub it."""
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    creds = service_account.Credentials.from_service_account_info(
        key, scopes=scopes).with_subject(subject)
    creds.refresh(Request())
    return creds.token


def members_token() -> str:
    """Token for listing memberships: narrow readonly scope, then the broad one if the
    DWD grant lacks it. Any other error propagates."""
    from google.auth.exceptions import RefreshError

    key = _load_sa_key(_require("admin_sa_secret"), CHAT.get("admin_sa_project"))
    subject = _require("dwd_subject")
    try:
        return _mint(key, [MEMBERS_SCOPE], subject)
    except RefreshError as e:
        if "unauthorized_client" not in str(e):
            raise
    try:
        return _mint(key, [MEMBERS_SCOPE_BROAD], subject)
    except RefreshError:
        sys.exit(f"the admin SA's DWD grant has neither chat.memberships.readonly "
                 f"nor chat.memberships for {subject}")


def directory_token() -> str:
    """Token for the Directory API user lookup (same admin key and subject)."""
    key = _load_sa_key(_require("admin_sa_secret"), CHAT.get("admin_sa_project"))
    return _mint(key, [DIRECTORY_SCOPE], _require("dwd_subject"))


def members_url(space: str, page_token: str | None = None) -> str:
    q = {"pageSize": 1000, "showGroups": "true", "showInvited": "true"}
    if page_token:
        q["pageToken"] = page_token
    return f"https://chat.googleapis.com/v1/{space}/members?{urllib.parse.urlencode(q)}"


def directory_user_url(user_name: str) -> str:
    """Directory users.get URL for a Chat `users/<number>` name."""
    number = user_name.split("/", 1)[1]
    return ("https://admin.googleapis.com/admin/directory/v1/users/"
            f"{urllib.parse.quote(number)}?fields=primaryEmail,name/fullName,suspended")


def cmd_members(args):
    if not valid_space_name(args.space):
        sys.exit(f"Invalid space name: {args.space!r}. Expected spaces/<SPACE_ID>")
    token = members_token()
    memberships, page_token = [], None
    while True:
        d = _http("GET", members_url(args.space, page_token), token)
        memberships.extend(d.get("memberships", []))
        page_token = d.get("nextPageToken")
        if not page_token:
            break
    dir_token, email_errors = None, []  # email_errors: stderr lines; any entry = exit 1
    if args.emails:
        from google.auth.exceptions import RefreshError
        try:
            dir_token = directory_token()
        except RefreshError as e:
            if "unauthorized_client" in str(e):
                email_errors.append("the admin SA's DWD grant lacks admin.directory.user.readonly")
            else:
                email_errors.append(str(e)[:200])
    humans = bots = groups = invited = 0
    for ms in memberships:
        role, state = ms.get("role", ""), ms.get("state", "")
        if state == "INVITED":
            invited += 1
        gm = ms.get("groupMember")
        if gm:
            groups += 1
            print(f"GROUP {gm.get('name', '')} role={role} state={state}")
            continue
        mem = ms.get("member") or {}
        mtype = mem.get("type", "")
        if mtype == "HUMAN":
            humans += 1
        elif mtype == "BOT":
            bots += 1
        line = f"MEMBER {mem.get('name', '')} {mtype} role={role} state={state}"
        if dir_token and mtype == "HUMAN":  # bots are not in the Directory
            name = mem.get("name") or ""
            if not name.startswith("users/") or not name[len("users/"):]:
                line += " email=unknown (no user id)"
                print(line)
                continue
            # Only 404 means "not in this directory". 401/403 mean we are not allowed to
            # ask (or the API is off), which must not read as "external".
            u = _http("GET", directory_user_url(name), dir_token, tolerate=(401, 403, 404))
            code = u.get("__tolerated__")
            if code == 404:
                line += " email=unknown (not in this directory: external or deleted)"
            elif code:
                line += f" email=ERROR {code} (Directory API not permitted or not enabled for this admin)"
                email_errors.append(f"Directory lookup returned HTTP {code}")
            else:
                line += f" email={u.get('primaryEmail', '')} name=\"{(u.get('name') or {}).get('fullName', '')}\""
                if u.get("suspended"):
                    line += " SUSPENDED"
        print(line)
    print(f"MEMBERS {args.space}: humans={humans} bots={bots} groups={groups} invited={invited}")
    if groups:
        print(f"WARNING: {groups} group(s) not expanded. Their members can read this space: "
              "expand each group with the Directory API before a private post.")
    if email_errors:
        # Dedupe, keep order: one line per distinct cause, not one per member.
        for msg in dict.fromkeys(email_errors):
            sys.stderr.write(f"ERROR: cannot resolve emails: {msg}\n")
        sys.exit(1)


# --- whois: Chat user id -> Directory user (email, name, org unit, suspended) ------
# A Chat `users/<digits>` id is the user's Directory id, so one read-only GET resolves it.
# `list` shows only ids, and a Chat display name can differ from the Workspace name, so
# identify a sender by this lookup, never by display name. A bot id has no directory entry
# and returns 404 (verified live). Same call as `members --emails` (that command
# prints email and name per member; `whois` adds the org unit, asks as an admin view and
# reports one line per id).

WHOIS_FIELDS = "primaryEmail,name/fullName,orgUnitPath,suspended"


def valid_user_id(uid: str) -> bool:
    """A Chat user resource name: users/<digits> (ASCII digits only)."""
    return re.fullmatch(r"users/[0-9]+", uid) is not None


def whois_url(uid: str) -> str:
    qs = urllib.parse.urlencode({"viewType": "admin_view", "fields": WHOIS_FIELDS})
    return f"https://admin.googleapis.com/admin/directory/v1/users/{uid.split('/', 1)[1]}?{qs}"


def whois_line(uid: str, reply: dict) -> tuple[str, bool]:
    """One output line for one id, and whether it resolved."""
    code = reply.get("__tolerated__")
    if code == 404:
        return (f"{uid} | NOT FOUND (404): not in the Workspace directory "
                "(a bot, an external user or a mistyped id)"), False
    if code == 403:
        return (f"{uid} | FORBIDDEN (403): the Directory API refused this read; check that "
                f"the DWD grant includes {DIRECTORY_SCOPE} and that dwd_subject "
                "is a Workspace admin"), False
    name = (reply.get("name") or {}).get("fullName") or "?"
    return (f"{uid} | {reply.get('primaryEmail') or '?'} | {name} | "
            f"{reply.get('orgUnitPath') or '?'} | "
            f"suspended={'yes' if reply.get('suspended') else 'no'}"), True


def cmd_whois(args):
    """Resolve each id to one line. A bad or unknown id never stops the next one; the
    exit status is 0 when every id resolved and 1 when any did not."""
    token, failed = None, 0
    for uid in args.users:
        if not valid_user_id(uid):
            print(f"{uid} | INVALID: expected users/<digits>, the sender id that `list` prints")
            failed += 1
            continue
        if token is None:
            from google.auth.exceptions import GoogleAuthError
            try:
                token = directory_token()
            except GoogleAuthError as e:
                # The usual cause is a DWD grant that lacks the Directory scope.
                sys.exit(f"Cannot get a Directory token for `whois`: {e}. The admin service "
                         f"account's domain-wide delegation grant must include {DIRECTORY_SCOPE}, "
                         "and dwd_subject must be a Workspace admin.")
        line, ok = whois_line(uid, _http("GET", whois_url(uid), token, tolerate=(403, 404)))
        print(line)
        failed += 0 if ok else 1
    if failed:
        sys.exit(1)


def resolve_text(args) -> str:
    """Return the message text from the positional `text` XOR `--text-file`.
    A file avoids shell-quoting trouble for long or multi-line posts. Only trailing
    CR/LF are stripped: inner line breaks and leading spaces are kept."""
    pos = getattr(args, "text", None)
    path = getattr(args, "text_file", None)
    if pos is not None and path is not None:
        sys.exit("Give the message text OR --text-file, not both.")
    if pos is None and path is None:
        sys.exit("No message text: give it as an argument or with --text-file PATH (or - for stdin).")
    if path is None:
        text = pos
    elif path == "-":
        try:
            raw = sys.stdin.buffer.read().decode("utf-8")
        except UnicodeDecodeError as e:
            sys.exit(f"stdin is not valid UTF-8: {e}")
        text = raw.removeprefix("\ufeff").rstrip("\r\n")
    else:
        try:
            # utf-8-sig drops a leading BOM (Windows editors add one)
            with open(path, encoding="utf-8-sig", newline="") as f:
                text = f.read().rstrip("\r\n")
        except FileNotFoundError:
            sys.exit(f"--text-file not found: {path}")
        except UnicodeDecodeError as e:
            sys.exit(f"--text-file {path} is not valid UTF-8: {e}")
        except OSError as e:
            sys.exit(f"--text-file {path} cannot be read: {e}")
    if not text.strip():
        sys.exit("Message text is empty or whitespace-only; refusing to post.")
    return text


def cmd_post(args):
    identity = _resolve_identity(args.identity)
    body = {"text": resolve_text(args)}
    url = f"https://chat.googleapis.com/v1/{args.space}/messages"
    if args.dry_run:
        print(f"DRY-RUN post as {identity} -> {url}\n{json.dumps(body, indent=2)}")
        return
    resp = _http("POST", url, _write_token(identity), body)
    _verify_sender(resp, identity, args.allow_unverified)


def cmd_reply(args):
    identity = _resolve_identity(args.identity)
    parts = args.thread.split("/")
    if len(parts) < 4 or parts[0] != "spaces" or parts[2] != "threads":
        sys.exit(f"Invalid thread name: {args.thread!r}. Expected spaces/<id>/threads/<id>")
    space_id = "/".join(parts[:2])  # spaces/<SPACE_ID>
    body = {"text": resolve_text(args), "thread": {"name": args.thread}}
    url = (
        f"https://chat.googleapis.com/v1/{space_id}/messages"
        "?messageReplyOption=REPLY_MESSAGE_OR_FAIL"
    )
    if args.dry_run:
        print(f"DRY-RUN reply as {identity} -> {url}\n{json.dumps(body, indent=2)}")
        return
    resp = _http("POST", url, _write_token(identity), body)
    _verify_sender(resp, identity, args.allow_unverified)


def valid_message_name(msg: str) -> bool:
    """A Chat message resource name is spaces/<S>/messages/<THREAD>.<MSG> - the id after
    `/messages/` is dot-joined, with no further slash (the slash form 400s)."""
    marker = "/messages/"
    if not msg.startswith("spaces/") or marker not in msg:
        return False
    tail = msg.split(marker, 1)[1]
    return "." in tail and "/" not in tail


def cmd_react(args):
    msg = args.message
    if not valid_message_name(msg):
        sys.exit(
            f"Invalid message resource name: {msg!r}. "
            "Expected spaces/<SPACE_ID>/messages/<THREAD_ID>.<MSG_ID> "
            "(thread and message ids joined by a DOT, not a slash - the slash form 400s)."
        )
    emoji = resolve_react_emoji(args.emoji)
    url = reactions_url(msg)
    body = react_body(emoji)
    if args.dry_run:
        # A preview must not require a configured credential (matches post/reply --dry-run).
        try:
            source = resolve_react_plan()["source"]
        except SystemExit:
            source = "(no react credential configured)"
        print(f"DRY-RUN react {emoji} via {source} -> {url}\n{json.dumps(body, indent=2)}")
        return
    resp = _http("POST", url, react_token(resolve_react_plan()), body)
    _verify_reaction(resp)


# --- react-opener: react on the THREAD'S OPENING message, own-eye idempotent ----
# Reacts the pickup emoji on the thread's opening (root) message - NOT the teammate's
# individual reply - and skips only when the OPERATOR'S OWN emoji is already there.
# The opener is the oldest message in the thread; the own-eye check reads the
# operator's reactions and compares across variation-selector forms. All three calls
# (list + reactions.list + reactions.create) run under the one react token
# (chat.messages), verified live.

_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def _valid_id(segment: str) -> bool:
    """A Chat space/thread id is non-empty and made ONLY of URL-safe id chars.
    Rejecting anything else keeps a stray quote/space/control char out of the
    hand-built, double-quoted API filter and the URL path - otherwise it would
    break the quoted filter literal or raise an unhandled InvalidURL."""
    return bool(segment) and all(c in _ID_CHARS for c in segment)


def valid_thread_name(thread: str) -> bool:
    """A Chat thread resource name is spaces/<S>/threads/<T> - exactly four
    slash-separated segments with URL-safe ids (mirrors cmd_reply's check, plus an
    id-charset check so the value is safe to quote into the filter and URL)."""
    parts = thread.split("/")
    return (len(parts) == 4 and parts[0] == "spaces" and parts[2] == "threads"
            and _valid_id(parts[1]) and _valid_id(parts[3]))


def _emoji_key(unicode_str: str) -> str:
    """Normalise an emoji for comparison: drop the variation selectors U+FE0F
    (emoji presentation) and U+FE0E (text). The eye reaction is stored both bare
    (U+1F441) and as the Chat-UI form (U+1F441 U+FE0F), so a raw `==` would miss
    one form; stripping the selectors makes them compare equal (verified live)."""
    return (unicode_str or "").replace("️", "").replace("︎", "")


def thread_messages_list_url(thread_name: str, order: str = "ASC", page_size: int = 1) -> str:
    """List URL for one thread's messages, oldest first - the first result is the
    thread's opening (root) message. `thread.name` value is double-quoted (accepted
    live either way; quoted for consistency with the reactions filter). The whole
    filter is URL-encoded."""
    space = thread_name.split("/threads/", 1)[0]
    qs = urllib.parse.urlencode({
        "filter": f'thread.name = "{thread_name}"',
        "orderBy": f"createTime {order}",
        "pageSize": page_size,
    })
    return f"https://chat.googleapis.com/v1/{space}/messages?{qs}"


def own_reactions_list_url(message_name: str, self_user_id: str) -> str:
    """Reactions URL filtered to the operator's OWN reactions on one message.
    Filter by `user.name` ONLY (both quoted) - NOT by emoji - so every stored emoji
    form comes back for a normalised Python compare (see _emoji_key). Filtering by a
    single emoji.unicode form would miss a variation-selector form of that emoji."""
    qs = urllib.parse.urlencode({"filter": f'user.name = "{self_user_id}"'})
    return f"https://chat.googleapis.com/v1/{message_name}/reactions?{qs}"


def find_thread_opener(thread_name: str, token: str) -> dict:
    """Return the thread's opening (root) message = the oldest message in the thread.
    Hard-fails (never returns None, never falls through to a react) when the thread
    has no visible messages - a bad thread name or no space access."""
    resp = _http("GET", thread_messages_list_url(thread_name), token)
    messages = resp.get("messages", [])
    if not messages:
        sys.exit(
            f"No messages found for thread {thread_name!r}. The thread name may be "
            "wrong, or you may not have access to the space. Resolve it with "
            "`list <space>` and read the `thread=` field of the teammate's message."
        )
    return messages[0]


def own_reaction_present(message_name: str, emoji: str, self_user_id: str, token: str) -> bool:
    """True iff the operator (self_user_id) already reacted on `message_name` with
    `emoji`, matched across variation-selector forms (see _emoji_key)."""
    resp = _http("GET", own_reactions_list_url(message_name, self_user_id), token)
    want = _emoji_key(emoji)
    for rx in resp.get("reactions", []):
        # Defence in depth: the API call is already filtered by user.name, but confirm
        # the user client-side too, so a teammate's identical emoji can never read as
        # yours if the server-side filter were ever ignored.
        if (rx.get("user") or {}).get("name") != self_user_id:
            continue
        if _emoji_key((rx.get("emoji") or {}).get("unicode", "")) == want:
            return True
    return False


def cmd_react_opener(args):
    thread = args.thread
    if not valid_thread_name(thread):
        sys.exit(
            f"Invalid thread resource name: {thread!r}. "
            "Expected spaces/<SPACE_ID>/threads/<THREAD_ID>. Resolve it with "
            "`list <space>` and read the `thread=` field of the teammate's message."
        )
    emoji = resolve_react_emoji(args.emoji)
    if args.dry_run:
        # A preview mints no token, resolves no opener, and makes no network call
        # (matches react/post/reply --dry-run).
        try:
            source = resolve_react_plan()["source"]
        except SystemExit:
            source = "(no react credential configured)"
        print(
            f"DRY-RUN react-opener {emoji} via {source} on the OPENING message of "
            f"{thread}, only if your {emoji} is not already there (no HTTP)."
        )
        return
    token = react_token(resolve_react_plan())
    opener = find_thread_opener(thread, token)
    opener_name = opener.get("name")
    if not opener_name:
        sys.exit(f"The opening message of thread {thread!r} has no resource name in the API response.")
    print(f"Opener: {opener_name} (createTime {opener.get('createTime')})")
    self_id = CHAT.get("self_user_id")
    if self_id:
        if own_reaction_present(opener_name, emoji, self_id, token):
            print(f"Already reacted: your {emoji} is on the opener {opener_name} - skipping.")
            return
    else:
        sys.stderr.write(
            "WARNING: self_user_id is not set - cannot check whether YOUR "
            f"{emoji} is already on the opener; reacting anyway (may duplicate). "
            "Set self_user_id to enable the skip check.\n"
        )
    # React on the OPENER. Tolerate an already-exists response (409) so a duplicate -
    # from the unset-self_id path or a check-then-react race - is a no-op success, not
    # a hard failure (duplicate-create behaviour is otherwise undocumented).
    resp = _http("POST", reactions_url(opener_name), token, react_body(emoji), tolerate=(409,))
    if resp.get("__tolerated__"):
        print(f"Already reacted (server reported it exists) on {opener_name} - skipping.")
        return
    _verify_reaction(resp)


# --- delete: remove ONE of YOUR OWN messages, verified by listing the thread --------
# After a DELETE the message GET still returns 200 with a tombstone record, so a 404
# is never the proof. The proof is the thread list no longer containing the name.

DELETE_PREVIEW_CHARS = 80
DELETE_VERIFY_MAX_PAGES = 20


def valid_delete_target(msg: str) -> bool:
    """Dot-joined server name spaces/<S>/messages/<T>.<M>, OR a client-assigned name
    spaces/<S>/messages/client-<id> (the delete API accepts both; the slash form 400s)."""
    marker = "/messages/"
    if not msg.startswith("spaces/") or marker not in msg:
        return False
    space, tail = msg.split(marker, 1)
    if not (space.count("/") == 1 and _valid_id(space.split("/", 1)[1])):
        return False
    if tail.startswith("client-"):
        return _valid_id(tail)
    return valid_message_name(msg) and all(_valid_id(p) for p in tail.split("."))


def message_thread_name(message_name: str) -> str:
    """spaces/<S>/messages/<T>.<M> -> spaces/<S>/threads/<T>."""
    space, tail = message_name.split("/messages/", 1)
    return f"{space}/threads/{tail.split('.', 1)[0]}"


def thread_page_url(thread_name: str, page_token: str | None = None) -> str:
    space = thread_name.split("/threads/", 1)[0]
    q = {
        "filter": f'thread.name = "{thread_name}"',
        "orderBy": "createTime ASC",
        "pageSize": 1000,
    }
    if page_token:
        q["pageToken"] = page_token
    return f"https://chat.googleapis.com/v1/{space}/messages?{urllib.parse.urlencode(q)}"


def message_in_thread(message_name: str, token: str, thread: str | None = None) -> bool:
    """True iff message_name is still listed in its thread (all pages, capped)."""
    thread = thread or message_thread_name(message_name)
    page_token = None
    for _ in range(DELETE_VERIFY_MAX_PAGES):
        d = _http("GET", thread_page_url(thread, page_token), token)
        if any(m.get("name") == message_name for m in d.get("messages", [])):
            return True
        page_token = d.get("nextPageToken")
        if not page_token:
            return False
    sys.stderr.write(
        f"DELETE VERIFY INCOMPLETE: thread {thread} has more than "
        f"{DELETE_VERIFY_MAX_PAGES} pages; cannot prove the message is gone.\n"
    )
    sys.exit(4)


def cmd_delete(args):
    msg = args.message
    if not valid_delete_target(msg):
        sys.exit(
            f"Invalid message resource name: {msg!r}. "
            "Expected spaces/<SPACE_ID>/messages/<THREAD_ID>.<MSG_ID> "
            "(thread and message ids joined by a DOT, not a slash - the slash form 400s), "
            "or spaces/<SPACE_ID>/messages/client-<ID> for a client-assigned id."
        )
    url = f"https://chat.googleapis.com/v1/{msg}"
    if args.dry_run:
        thread_note = ("the thread named in the GET response" if "/messages/client-" in msg
                       else message_thread_name(msg))
        print(
            f"DRY-RUN delete as self (admin SA + DWD, chat.messages), no HTTP made:\n"
            f"  1. GET    {url}   (refuse unless sender is self_user_id)\n"
            f"  2. DELETE {url}   (only with --yes)\n"
            f"  3. list {thread_note} with filter thread.name = \"...\"   (confirm the message is gone)"
        )
        return
    self_id = CHAT.get("self_user_id")
    if not self_id:
        sys.exit("Refusing to delete: self_user_id is not set, so the sender cannot be "
                 "confirmed as you. Set it in the chat block of your config.")
    token = delete_token()
    m = _http("GET", url, token)
    sender = (m.get("sender") or {}).get("name")
    disp = (m.get("sender") or {}).get("displayName")
    if sender != self_id:
        sys.stderr.write(
            f"REFUSED: {msg} was sent by {sender!r} ({disp!r}), not you ({self_id!r}). "
            "This command deletes only your own messages.\n"
        )
        sys.exit(2)
    text = (m.get("text") or m.get("formattedText") or "").replace("\n", " / ")
    preview = text[:DELETE_PREVIEW_CHARS] + ("..." if len(text) > DELETE_PREVIEW_CHARS else "")
    print(f"Message: {msg}")
    print(f"Sender: {disp or sender} ({sender})")
    print(f"Text: {preview}")
    if not args.yes:
        print("WOULD DELETE (nothing deleted). Show this to the user and re-run with --yes "
              "after they say yes.")
        return
    # A client-assigned name resolves to a server name (<THREAD>.<MSG>) plus a thread in
    # the GET response; verify against those, not the client name.
    canonical = m.get("name") or msg
    thread = (m.get("thread") or {}).get("name")
    if "/messages/client-" in msg and not thread:
        sys.exit(f"Cannot find the thread of {msg!r} in the API response; refusing to delete "
                 "something that cannot be verified afterwards.")
    _http("DELETE", url, token)
    if message_in_thread(canonical, token, thread):
        sys.stderr.write(
            f"DELETE NOT VERIFIED: {msg} is still listed in its thread after the DELETE. "
            "Do not report it as deleted.\n"
        )
        sys.exit(1)
    print(f"DELETED {msg}")


THREAD_READ_MAX_PAGES = 20   # read-thread and who-reacted stop here and say the read is incomplete


def _emoji_label(emoji) -> str:
    """A reaction's emoji: the unicode character, or custom:<uid> for a custom emoji."""
    emoji = emoji or {}
    return emoji.get("unicode") or f"custom:{(emoji.get('customEmoji') or {}).get('uid', '?')}"


def thread_message_lines(m: dict, full: bool) -> list:
    """The lines read-thread prints for one message: a header, its text, then one line per
    attachment and per reaction. Attachment lines are metadata only: nothing is downloaded."""
    sender = m.get("sender") or {}
    text = m.get("text") or m.get("formattedText") or ""
    if not full:
        text = text.replace("\n", " / ")[:200]
    lines = [f"{m.get('createTime')} | name={m.get('name', '')} | "
             f"sender={sender.get('name', '')} ({sender.get('type', '?')})"]
    if text:
        lines.append(text)
    for a in m.get("attachment") or []:
        lines.append(f"  attachment: {a.get('contentName', '?')} | {a.get('contentType', '?')} | "
                     f"{a.get('source', '?')} | {a.get('name', '')}")
    for r in m.get("emojiReactionSummaries") or []:
        lines.append(f"  reaction: {_emoji_label(r.get('emoji'))} x{r.get('reactionCount', 0)}")
    return lines


def cmd_read_thread(args):
    """Every message of one thread, oldest first, all pages (read-only, admin SA + DWD). A
    one-page read can miss later replies, so this follows nextPageToken to the end."""
    if not valid_thread_name(args.thread):
        sys.exit(f"Invalid thread name: {args.thread!r}. Expected spaces/<SPACE_ID>/threads/<THREAD_ID>, "
                 "the thread= value that `list` prints.")
    token, page_token, count = read_token(), None, 0
    for _ in range(THREAD_READ_MAX_PAGES):
        d = _http("GET", thread_page_url(args.thread, page_token), token)
        for m in d.get("messages", []):
            count += 1
            print(json.dumps(m, ensure_ascii=False) if args.json else "\n".join(thread_message_lines(m, args.full)))
        page_token = d.get("nextPageToken")
        if not page_token:
            if not count:
                sys.exit(f"No messages in {args.thread}: a wrong thread name, or the admin user cannot "
                         "read that space.")
            total = f"TOTAL {count} message(s) in {args.thread}"
            if args.json:
                sys.stderr.write(total + "\n")
            else:
                print(total)
            return
    sys.stderr.write(f"READ INCOMPLETE: {args.thread} has more than {THREAD_READ_MAX_PAGES} pages; "
                     f"printed {count} message(s).\n")
    sys.exit(4)


def reactions_page_url(message: str, page_token: str | None = None) -> str:
    q = {"pageSize": 200}
    if page_token:
        q["pageToken"] = page_token
    return f"{reactions_url(message)}?{urllib.parse.urlencode(q)}"


def cmd_who_reacted(args):
    """Every reaction on one message, all pages (read-only, admin SA + DWD). Prints ids only;
    the last line is the `whois` command that names the humans."""
    if not valid_delete_target(args.message):   # the strict check: URL-safe ids only
        sys.exit(f"Invalid message name: {args.message!r}. Expected "
                 "spaces/<SPACE_ID>/messages/<THREAD_ID>.<MSG_ID> (dot-joined; the slash form 400s).")
    token, page_token, count, humans = read_token(), None, 0, []
    for _ in range(THREAD_READ_MAX_PAGES):
        d = _http("GET", reactions_page_url(args.message, page_token), token)
        for r in d.get("reactions", []):
            user = r.get("user") or {}
            print(f"{_emoji_label(r.get('emoji'))} | {user.get('name', '?')} | {user.get('type', '?')}")
            count += 1
            if user.get("type") == "HUMAN" and user.get("name") and user["name"] not in humans:
                humans.append(user["name"])
        page_token = d.get("nextPageToken")
        if not page_token:
            if not count:
                print(f"No reactions on {args.message}.")
            elif humans:
                print(f"Names: chat-post.py whois {' '.join(humans)}")
            return
    sys.stderr.write(f"READ INCOMPLETE: {args.message} has more than {THREAD_READ_MAX_PAGES} pages of "
                     f"reactions; printed {count}.\n")
    sys.exit(4)


def main():
    ap = argparse.ArgumentParser(description="Post Google Chat messages (config-driven identity).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List recent messages in a space (admin SA + DWD)")
    p_list.add_argument("space", help="Space resource name, e.g. spaces/AAAAexample1")
    p_list.add_argument("--limit", type=int, default=30)
    p_list.add_argument("--full", action="store_true",
                        help="Print each message's full text (default truncates at 200 chars)")
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser(
        "search", help="Search a space's full history for a topic (admin SA + DWD)")
    p_search.add_argument("space", help="spaces/<SPACE_ID>")
    p_search.add_argument("term", help="Text to find, case-insensitive (e.g. a customer domain)")
    p_search.add_argument("--term", dest="terms", action="append",
                          help="Another term to match (repeatable; any term matches)")
    p_search.add_argument("--since", default=None,
                          help=f"YYYY-MM-DD lower bound (default {SEARCH_DEFAULT_DAYS} days ago)")
    p_search.add_argument("--max-pages", type=int, default=50,
                          help=f"Page cap, {SEARCH_PAGE_SIZE} messages per page (default 50)")
    p_search.set_defaults(func=cmd_search)

    p_find = sub.add_parser(
        "find", help="List recently active spaces with their latest messages (read-only)")
    p_find.add_argument("--days", type=int, default=3, help="Active within the last N days (default 3)")
    p_find.add_argument("--per", type=int, default=3, help="Latest messages per space (default 3)")
    p_find.add_argument("--top", type=int, default=20, help="Show the newest N spaces (default 20)")
    p_find.set_defaults(func=cmd_find)

    p_members = sub.add_parser(
        "members", help="List who can read a space (read-only; admin SA + DWD)")
    p_members.add_argument("space", help="spaces/<SPACE_ID>")
    p_members.add_argument("--emails", action="store_true",
                           help="Resolve each human member's email via the Directory API")
    p_members.set_defaults(func=cmd_members)

    p_whois = sub.add_parser(
        "whois", help="Resolve Chat user ids to email, full name, org unit and suspended flag "
                      "(admin SA + DWD, read-only)")
    p_whois.add_argument("users", nargs="+", metavar="users/ID",
                         help="Chat user id(s), the sender=users/<digits> value that `list` prints")
    p_whois.set_defaults(func=cmd_whois)

    p_read_thread = sub.add_parser(
        "read-thread", help="Read every message of ONE thread, oldest first, all pages, with attachment "
                            "metadata and reactions (read-only; admin SA + DWD)")
    p_read_thread.add_argument("thread", help="spaces/<SPACE_ID>/threads/<THREAD_ID>, the thread= value of `list`")
    p_read_thread.add_argument("--full", action="store_true",
                               help="Print each message's full text (default: one line, cut at 200 chars)")
    p_read_thread.add_argument("--json", action="store_true",
                               help="Print each raw message as one JSON line (the total goes to stderr)")
    p_read_thread.set_defaults(func=cmd_read_thread)

    p_who_reacted = sub.add_parser(
        "who-reacted", help="List every reaction on one message: emoji, user id, user type (read-only)")
    p_who_reacted.add_argument("message", help="spaces/<SPACE_ID>/messages/<THREAD_ID>.<MSG_ID> (dot-joined)")
    p_who_reacted.set_defaults(func=cmd_who_reacted)

    p_post = sub.add_parser("post", help="Post a top-level message")
    p_post.add_argument("space", help="spaces/<SPACE_ID>")
    p_post.add_argument("text", nargs="?", default=None,
                        help="Message text (Chat-flavoured markdown OK); or use --text-file")
    p_post.add_argument("--text-file", default=None, metavar="PATH|-",
                        help="Read the text from a UTF-8 file, or - for stdin")
    p_post.add_argument("--identity", choices=["bot", "self"], default=None)
    p_post.add_argument("--dry-run", action="store_true")
    p_post.add_argument("--allow-unverified", action="store_true",
                        help="Downgrade a missing-verification-config case to a warning (exit 0).")
    p_post.set_defaults(func=cmd_post)

    p_reply = sub.add_parser("reply", help="Reply in an existing thread")
    p_reply.add_argument("thread", help="spaces/<SPACE_ID>/threads/<THREAD_ID>")
    p_reply.add_argument("text", nargs="?", default=None,
                         help="Message text (Chat-flavoured markdown OK); or use --text-file")
    p_reply.add_argument("--text-file", default=None, metavar="PATH|-",
                         help="Read the text from a UTF-8 file, or - for stdin")
    p_reply.add_argument("--identity", choices=["bot", "self"], default=None)
    p_reply.add_argument("--dry-run", action="store_true")
    p_reply.add_argument("--allow-unverified", action="store_true",
                         help="Downgrade a missing-verification-config case to a warning (exit 0).")
    p_reply.set_defaults(func=cmd_reply)

    p_react = sub.add_parser("react", help="Add an emoji reaction to a message AS YOU (config-driven)")
    p_react.add_argument("message", help="spaces/<SPACE_ID>/messages/<THREAD_ID>.<MSG_ID> (dot-joined)")
    p_react.add_argument("emoji", nargs="?", default=None,
                         help="Unicode emoji; default react_emoji, else 👁")
    p_react.add_argument("--dry-run", action="store_true")
    p_react.set_defaults(func=cmd_react)

    p_react_opener = sub.add_parser(
        "react-opener",
        help="React AS YOU on a thread's OPENING message, only if your emoji is not already there")
    p_react_opener.add_argument("thread", help="spaces/<SPACE_ID>/threads/<THREAD_ID>")
    p_react_opener.add_argument("emoji", nargs="?", default=None,
                                help="Unicode emoji; default react_emoji, else 👁")
    p_react_opener.add_argument("--dry-run", action="store_true")
    p_react_opener.set_defaults(func=cmd_react_opener)

    p_delete = sub.add_parser(
        "delete", help="Delete ONE of YOUR OWN messages (admin SA + DWD); previews unless --yes")
    p_delete.add_argument("message", help="spaces/<SPACE_ID>/messages/<THREAD_ID>.<MSG_ID> (dot-joined)")
    p_delete.add_argument("--yes", action="store_true",
                          help="Actually delete (without it the command only previews)")
    p_delete.add_argument("--dry-run", action="store_true",
                          help="Print the planned requests; make no network call")
    p_delete.set_defaults(func=cmd_delete)

    args, extra = ap.parse_known_args()
    if extra:
        # argparse binds the optional TEXT of post/reply too early, so `post S --identity self
        # TEXT` leaves TEXT unparsed. Take exactly one such word back (an option-like word is a
        # typo, not text; use --text-file for that).
        if getattr(args, "text", "") is None and len(extra) == 1 and not extra[0].startswith("-"):
            args.text = extra[0]
        else:
            ap.error("unrecognized arguments: " + " ".join(extra))
    try:
        args.func(args)
    except ImportError as exc:
        # google-auth (and requests, which its transport needs) are imported only
        # when a token is minted, so this fires before any write.
        missing = getattr(exc, "name", None) or str(exc)
        if not str(missing).startswith(("google", "requests")):
            raise
        _config_exit(f"chat-post.py needs the google-auth and requests packages ({missing} is "
                     "missing). Install them: pip install google-auth requests")


if __name__ == "__main__":
    main()
