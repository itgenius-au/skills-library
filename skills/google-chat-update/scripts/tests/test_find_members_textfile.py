#!/usr/bin/env python3
"""Unit tests for chat-post.py `--text-file`, `find` and `members`.

All I/O is stubbed (read_token, members_token, directory_token, _mint, _http): no network.
"""
import argparse
import datetime
import importlib.util
import io
import pathlib
import urllib.parse

import pytest
from google.auth.exceptions import RefreshError

MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "chat-post.py"
_spec = importlib.util.spec_from_file_location("chat_post", MOD_PATH)
chat_post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_post)

NOW = datetime.datetime(2026, 10, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)


# --- resolve_text / --text-file ---

def _targs(text=None, text_file=None, **kw):
    base = dict(text=text, text_file=text_file)
    base.update(kw)
    return argparse.Namespace(**base)


def test_text_positional_only():
    assert chat_post.resolve_text(_targs(text="hello")) == "hello"


def test_text_file_keeps_inner_newlines_strips_trailing(tmp_path):
    f = tmp_path / "m.txt"
    f.write_bytes("  line one\n\n  line two\r\n\r\n".encode("utf-8"))
    assert chat_post.resolve_text(_targs(text_file=str(f))) == "  line one\n\n  line two"


class _FakeStdin:
    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)


def test_text_file_dash_reads_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", _FakeStdin("from stdin\n".encode("utf-8")))
    assert chat_post.resolve_text(_targs(text_file="-")) == "from stdin"


def test_text_stdin_strips_leading_bom(monkeypatch):
    monkeypatch.setattr("sys.stdin", _FakeStdin("\ufeffhi\n".encode("utf-8")))
    assert chat_post.resolve_text(_targs(text_file="-")) == "hi"


def test_text_file_strips_leading_bom(tmp_path):
    f = tmp_path / "bom.txt"
    f.write_bytes(b"\xef\xbb\xbfhello\n")
    assert chat_post.resolve_text(_targs(text_file=str(f))) == "hello"


def test_text_stdin_invalid_utf8_exits(monkeypatch):
    monkeypatch.setattr("sys.stdin", _FakeStdin(b"\xff\xfe\xfa"))
    with pytest.raises(SystemExit) as e:
        chat_post.resolve_text(_targs(text_file="-"))
    assert "UTF-8" in str(e.value)


def test_text_file_invalid_utf8_exits(tmp_path):
    f = tmp_path / "bad.txt"
    f.write_bytes(b"ok \xff\xfa")
    with pytest.raises(SystemExit) as e:
        chat_post.resolve_text(_targs(text_file=str(f)))
    assert "UTF-8" in str(e.value)


def test_text_both_exits(tmp_path):
    f = tmp_path / "m.txt"
    f.write_text("x")
    with pytest.raises(SystemExit):
        chat_post.resolve_text(_targs(text="a", text_file=str(f)))


def test_text_neither_exits():
    with pytest.raises(SystemExit):
        chat_post.resolve_text(_targs())


def test_text_empty_file_exits(tmp_path):
    f = tmp_path / "e.txt"
    f.write_text(" \n\n")
    with pytest.raises(SystemExit):
        chat_post.resolve_text(_targs(text_file=str(f)))


def test_text_missing_file_exits_naming_path(tmp_path):
    p = str(tmp_path / "nope.txt")
    with pytest.raises(SystemExit) as e:
        chat_post.resolve_text(_targs(text_file=p))
    assert p in str(e.value)


def test_post_dry_run_with_text_file_prints_payload(tmp_path, capsys):
    f = tmp_path / "m.txt"
    f.write_text("multi\nline body\n", encoding="utf-8")
    chat_post.cmd_post(_targs(space="spaces/S", text_file=str(f), identity="bot",
                              dry_run=True, allow_unverified=False))
    out = capsys.readouterr().out
    assert "DRY-RUN post as bot" in out
    assert '"text": "multi\\nline body"' in out


def test_reply_dry_run_with_text_file_prints_payload(tmp_path, capsys):
    f = tmp_path / "m.txt"
    f.write_text("reply body\n", encoding="utf-8")
    chat_post.cmd_reply(_targs(thread="spaces/S/threads/T", text_file=str(f), identity="bot",
                               dry_run=True, allow_unverified=False))
    assert '"text": "reply body"' in capsys.readouterr().out


def test_argparse_text_is_optional(monkeypatch):
    seen = {}
    monkeypatch.setattr(chat_post, "cmd_post", lambda a: seen.update(vars(a)))
    monkeypatch.setattr("sys.argv", ["chat-post.py", "post", "spaces/S", "--text-file", "-"])
    chat_post.main()
    assert seen["text"] is None and seen["text_file"] == "-"


# --- find ---

def test_parse_rfc3339_fraction_ordering_and_offset():
    a = chat_post.parse_rfc3339("2026-10-30T10:00:00.25Z")
    b = chat_post.parse_rfc3339("2026-10-30T10:00:00.5Z")
    assert b > a  # raw string compare gets this wrong
    # 12:00+02:00 is 10:00Z
    assert chat_post.parse_rfc3339("2026-10-30T12:00:00+02:00") == \
        chat_post.parse_rfc3339("2026-10-30T10:00:00Z")
    assert chat_post.parse_rfc3339("2026-10-30T10:00:00.123456789Z").microsecond == 123456
    with pytest.raises(ValueError):
        chat_post.parse_rfc3339("yesterday")


def test_recent_spaces_drops_old_and_missing_sorted_newest_first():
    spaces = [
        {"name": "spaces/OLD", "lastActiveTime": "2026-10-01T00:00:00Z"},
        {"name": "spaces/NONE"},
        {"name": "spaces/BAD", "lastActiveTime": "garbage"},
        {"name": "spaces/A", "lastActiveTime": "2026-10-29T10:00:00.25Z"},
        {"name": "spaces/B", "lastActiveTime": "2026-10-29T10:00:00.5Z"},
    ]
    got = [s["name"] for s in chat_post.recent_spaces(spaces, NOW, 3)]
    assert got == ["spaces/B", "spaces/A"]


def _find_args(**kw):
    base = dict(days=3, per=3, top=20)
    base.update(kw)
    return argparse.Namespace(**base)


def _stub_find(monkeypatch, handler):
    calls = []
    monkeypatch.setattr(chat_post, "read_token", lambda: "TOK")
    monkeypatch.setattr(chat_post, "_utcnow", lambda: NOW)

    def fake_http(method, url, token, body=None, tolerate=()):
        calls.append((url, tolerate))
        return handler(url)
    monkeypatch.setattr(chat_post, "_http", fake_http)
    return calls


def _sp(name, last="2026-10-30T11:00:00Z", display="Team", typ="SPACE"):
    return {"name": name, "spaceType": typ, "displayName": display, "lastActiveTime": last}


def test_find_follows_two_pages_and_reports_counts(monkeypatch, capsys):
    def handler(url):
        if "/messages" in url:
            return {}
        if "pageToken=P2" in url:
            return {"spaces": [_sp("spaces/B", "2026-10-29T00:00:00Z"), _sp("spaces/X", None)]}
        return {"spaces": [_sp("spaces/A")], "nextPageToken": "P2"}
    calls = _stub_find(monkeypatch, handler)
    chat_post.cmd_find(_find_args())
    out = capsys.readouterr().out
    assert sum(1 for u, _ in calls if u.startswith("https://chat.googleapis.com/v1/spaces?")) == 2
    assert "SPACE spaces/A | SPACE | Team | last 2026-10-30T11:00:00Z" in out
    assert out.index("spaces/A |") < out.index("spaces/B |")
    assert ("FOUND 2 space(s) active in the last 3 day(s) of 3 listed; showed 2; "
            "skipped 1 with no or an invalid lastActiveTime") in out


def test_find_top_limits_shown(monkeypatch, capsys):
    def handler(url):
        if "/messages" in url:
            return {}
        return {"spaces": [_sp("spaces/A"), _sp("spaces/B", "2026-10-30T10:00:00Z")]}
    _stub_find(monkeypatch, handler)
    chat_post.cmd_find(_find_args(top=1))
    out = capsys.readouterr().out
    assert "SPACE spaces/A" in out and "SPACE spaces/B" not in out
    assert "FOUND 2 space(s)" in out and "showed 1;" in out


def test_find_403_prints_read_error_and_continues(monkeypatch, capsys):
    def handler(url):
        if "spaces/A/messages" in url:
            return {"__tolerated__": 403}
        if "spaces/B/messages" in url:
            return {"messages": [
                {"createTime": "2026-10-30T09:00:02Z", "text": "newer", "thread": {"name": "spaces/B/threads/T"},
                 "sender": {"name": "users/1", "displayName": "Ann"}, "attachment": [{}, {}]},
                {"createTime": "2026-10-30T09:00:01Z", "text": "older\nline",
                 "thread": {"name": "spaces/B/threads/T"}, "sender": {"name": "users/1", "displayName": "Ann"}},
            ]}
        return {"spaces": [_sp("spaces/A"), _sp("spaces/B", "2026-10-30T10:00:00Z")]}
    calls = _stub_find(monkeypatch, handler)
    chat_post.cmd_find(_find_args(per=2))
    out = capsys.readouterr().out
    assert "  READ ERROR 403" in out
    assert "SPACE spaces/B" in out
    # tolerance is requested, per-space limit goes in the URL
    msg_calls = [(u, t) for u, t in calls if "/messages" in u]
    assert all(t == chat_post.FIND_READ_TOLERATED for _, t in msg_calls)
    assert urllib.parse.parse_qs(urllib.parse.urlparse(msg_calls[0][0]).query)["pageSize"] == ["2"]
    # oldest first, newlines flattened, attachment count, thread
    assert out.index("older / line") < out.index("newer")
    assert "  2026-10-30T09:00:02Z | sender=users/1 Ann | newer | thread=spaces/B/threads/T [+2 att]" in out


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_find_transient_error_goes_on_and_summary_prints(monkeypatch, capsys, code):
    def handler(url):
        if "spaces/A/messages" in url:
            return {"__tolerated__": code}
        if "/messages" in url:
            return {}
        return {"spaces": [_sp("spaces/A"), _sp("spaces/B", "2026-10-30T10:00:00Z")]}
    calls = _stub_find(monkeypatch, handler)
    chat_post.cmd_find(_find_args())
    out = capsys.readouterr().out
    assert f"  READ ERROR {code}" in out and "SPACE spaces/B" in out
    assert "FOUND 2 space(s)" in out
    msg_tol = [t for u, t in calls if "/messages" in u][0]
    assert code in msg_tol  # the status is tolerated, not a hard exit


def test_find_empty_display_name_label_and_text_cut(monkeypatch, capsys):
    def handler(url):
        if "/messages" in url:
            return {"messages": [{"createTime": "2026-10-30T09:00:00Z", "text": "x" * 500}]}
        return {"spaces": [_sp("spaces/G", display="", typ="GROUP_CHAT")]}
    _stub_find(monkeypatch, handler)
    chat_post.cmd_find(_find_args())
    out = capsys.readouterr().out
    assert "| (no name: group chat or DM) |" in out
    assert "x" * 160 in out and "x" * 161 not in out


def test_find_zero_spaces_warns(monkeypatch, capsys):
    _stub_find(monkeypatch, lambda url: {})
    chat_post.cmd_find(_find_args())
    out = capsys.readouterr().out
    assert "FOUND 0 space(s)" in out and "of 0 listed" in out
    assert "WARNING: 0 spaces listed. Check the admin DWD config" in out


@pytest.mark.parametrize("flag", ["days", "per", "top"])
def test_find_rejects_zero(monkeypatch, flag):
    monkeypatch.setattr(chat_post, "read_token", lambda: pytest.fail("must not mint"))
    with pytest.raises(SystemExit):
        chat_post.cmd_find(_find_args(**{flag: 0}))


# --- members ---

def _margs(**kw):
    base = dict(space="spaces/S", emails=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _human(n, state="JOINED", role="ROLE_MEMBER"):
    return {"role": role, "state": state, "member": {"name": f"users/{n}", "type": "HUMAN"}}


BOT = {"role": "ROLE_MEMBER", "state": "JOINED", "member": {"name": "users/app1", "type": "BOT"}}
GROUP = {"role": "ROLE_MEMBER", "state": "JOINED", "groupMember": {"name": "groups/g1"}}


def _stub_members(monkeypatch, handler, dir_token=lambda: "DTOK"):
    calls = []
    monkeypatch.setattr(chat_post, "members_token", lambda: "MTOK")
    monkeypatch.setattr(chat_post, "directory_token", dir_token)

    def fake_http(method, url, token, body=None, tolerate=()):
        calls.append((url, token, tolerate))
        return handler(url)
    monkeypatch.setattr(chat_post, "_http", fake_http)
    return calls


def test_members_follows_pages_counts_group_and_invited(monkeypatch, capsys):
    def handler(url):
        if "pageToken=P2" in url:
            return {"memberships": [GROUP, _human(2, state="INVITED")]}
        return {"memberships": [_human(1), BOT], "nextPageToken": "P2"}
    calls = _stub_members(monkeypatch, handler)
    chat_post.cmd_members(_margs())
    out = capsys.readouterr().out
    assert len(calls) == 2
    q = urllib.parse.parse_qs(urllib.parse.urlparse(calls[0][0]).query)
    assert q["showGroups"] == ["true"] and q["showInvited"] == ["true"] and q["pageSize"] == ["1000"]
    assert "MEMBER users/1 HUMAN role=ROLE_MEMBER state=JOINED" in out
    assert "GROUP groups/g1 role=ROLE_MEMBER state=JOINED" in out
    assert "MEMBERS spaces/S: humans=2 bots=1 groups=1 invited=1" in out
    assert "WARNING: 1 group(s) not expanded." in out


def test_members_no_group_no_warning(monkeypatch, capsys):
    _stub_members(monkeypatch, lambda url: {"memberships": [_human(1)]})
    chat_post.cmd_members(_margs())
    out = capsys.readouterr().out
    assert "groups=0" in out and "WARNING" not in out


def test_members_emails_appended_and_404_unknown_and_bot_skipped(monkeypatch, capsys):
    def handler(url):
        if "/members" in url:
            return {"memberships": [_human(111), _human(222), _human(333), BOT]}
        if url.endswith("/users/111?fields=primaryEmail,name/fullName,suspended"):
            return {"primaryEmail": "ann@example.com", "name": {"fullName": "Ann Lee"}}
        if "/users/222" in url:
            return {"primaryEmail": "bob@example.com", "name": {"fullName": "Bob"}, "suspended": True}
        return {"__tolerated__": 404}
    calls = _stub_members(monkeypatch, handler)
    chat_post.cmd_members(_margs(emails=True))
    out = capsys.readouterr().out
    assert 'state=JOINED email=ann@example.com name="Ann Lee"' in out
    assert 'email=bob@example.com name="Bob" SUSPENDED' in out
    assert "email=unknown (not in this directory: external or deleted)" in out
    dir_calls = [c for c in calls if "admin.googleapis.com" in c[0]]
    assert len(dir_calls) == 3  # the bot gets no lookup
    # 404 is the only status read as "not in this directory"; 401/403 are surfaced separately
    assert all(c[1] == "DTOK" and 404 in c[2] and 403 in c[2] and 401 in c[2] for c in dir_calls)


def test_members_without_emails_flag_makes_no_directory_call(monkeypatch, capsys):
    def no_dir():
        pytest.fail("must not mint a directory token")
    calls = _stub_members(monkeypatch, lambda url: {"memberships": [_human(1)]}, dir_token=no_dir)
    chat_post.cmd_members(_margs())
    assert all("admin.googleapis.com" not in c[0] for c in calls)
    assert "email=" not in capsys.readouterr().out


def test_members_directory_mint_failure_prints_members_then_exits_1(monkeypatch, capsys):
    def bad():
        raise RefreshError("unauthorized_client: nope")
    calls = _stub_members(monkeypatch, lambda url: {"memberships": [_human(1)]}, dir_token=bad)
    with pytest.raises(SystemExit) as e:
        chat_post.cmd_members(_margs(emails=True))
    assert e.value.code == 1
    cap = capsys.readouterr()
    assert "MEMBER users/1 HUMAN" in cap.out and "email=" not in cap.out
    assert "MEMBERS spaces/S: humans=1" in cap.out
    assert "ERROR: cannot resolve emails: the admin SA's DWD grant lacks admin.directory.user.readonly" in cap.err
    assert all("admin.googleapis.com" not in c[0] for c in calls)


def test_members_directory_403_is_error_not_external(monkeypatch, capsys):
    def handler(url):
        if "/members" in url:
            return {"memberships": [_human(111), _human(222)], }
        return {"__tolerated__": 403} if "/users/111" in url else {"primaryEmail": "b@example.com", "name": {"fullName": "B"}}
    _stub_members(monkeypatch, handler)
    with pytest.raises(SystemExit) as e:
        chat_post.cmd_members(_margs(emails=True))
    assert e.value.code == 1
    cap = capsys.readouterr()
    assert "email=ERROR 403 (Directory API not permitted or not enabled for this admin)" in cap.out
    assert "not in this directory" not in cap.out
    assert "email=b@example.com" in cap.out  # the other member still resolves
    assert cap.out.index("email=ERROR 403") < cap.out.index("MEMBERS spaces/S")  # exit is at the end
    assert "403" in cap.err


def test_members_directory_401_is_error(monkeypatch, capsys):
    def handler(url):
        return {"memberships": [_human(1)]} if "/members" in url else {"__tolerated__": 401}
    _stub_members(monkeypatch, handler)
    with pytest.raises(SystemExit) as e:
        chat_post.cmd_members(_margs(emails=True))
    assert e.value.code == 1
    assert "email=ERROR 401" in capsys.readouterr().out


def test_members_directory_other_refresh_error_not_scope_message(monkeypatch, capsys):
    def bad():
        raise RefreshError("invalid_grant: Invalid JWT Signature " + "z" * 400)
    _stub_members(monkeypatch, lambda url: {"memberships": [_human(1)]}, dir_token=bad)
    with pytest.raises(SystemExit) as e:
        chat_post.cmd_members(_margs(emails=True))
    assert e.value.code == 1
    cap = capsys.readouterr()
    assert "MEMBER users/1 HUMAN" in cap.out
    assert "lacks admin.directory.user.readonly" not in cap.err
    assert "ERROR: cannot resolve emails: invalid_grant" in cap.err
    assert "z" * 200 not in cap.err  # cut at 200 chars


@pytest.mark.parametrize("name", ["", "users/", "bogus"])
def test_members_human_with_malformed_name_gets_no_lookup(monkeypatch, capsys, name):
    ms = {"role": "ROLE_MEMBER", "state": "JOINED", "member": {"name": name, "type": "HUMAN"}}
    calls = _stub_members(monkeypatch, lambda url: {"memberships": [ms]})
    chat_post.cmd_members(_margs(emails=True))
    assert "email=unknown (no user id)" in capsys.readouterr().out
    assert all("admin.googleapis.com" not in c[0] for c in calls)


def test_members_token_neither_scope_exits_one_line(monkeypatch):
    _stub_key(monkeypatch)

    def fake_mint(key, scopes, subject):
        raise RefreshError("unauthorized_client: nope")
    monkeypatch.setattr(chat_post, "_mint", fake_mint)
    with pytest.raises(SystemExit) as e:
        chat_post.members_token()
    assert str(e.value) == ("the admin SA's DWD grant has neither chat.memberships.readonly "
                            "nor chat.memberships for me@example.com")


def test_members_invalid_space_exits(monkeypatch):
    monkeypatch.setattr(chat_post, "members_token", lambda: pytest.fail("must not mint"))
    with pytest.raises(SystemExit):
        chat_post.cmd_members(_margs(space="spaces/S/threads/T"))


def test_directory_user_url():
    assert chat_post.directory_user_url("users/123") == (
        "https://admin.googleapis.com/admin/directory/v1/users/123"
        "?fields=primaryEmail,name/fullName,suspended")


def _stub_key(monkeypatch):
    monkeypatch.setitem(chat_post.CHAT, "admin_sa_secret", "sec")
    monkeypatch.setitem(chat_post.CHAT, "admin_sa_project", "proj")
    monkeypatch.setitem(chat_post.CHAT, "dwd_subject", "me@example.com")
    loads = []
    monkeypatch.setattr(chat_post, "_load_sa_key", lambda s, p=None: loads.append((s, p)) or {"k": 1})
    return loads


def test_members_token_falls_back_to_broad_on_unauthorized_client(monkeypatch):
    loads = _stub_key(monkeypatch)
    minted = []

    def fake_mint(key, scopes, subject):
        minted.append((scopes, subject))
        if scopes == [chat_post.MEMBERS_SCOPE]:
            raise RefreshError("unauthorized_client: Client is unauthorized to retrieve access tokens")
        return "BROAD"
    monkeypatch.setattr(chat_post, "_mint", fake_mint)
    assert chat_post.members_token() == "BROAD"
    assert minted == [([chat_post.MEMBERS_SCOPE], "me@example.com"), ([chat_post.MEMBERS_SCOPE_BROAD], "me@example.com")]
    assert loads == [("sec", "proj")]  # key loaded once


def test_members_token_no_fallback_on_other_error(monkeypatch):
    _stub_key(monkeypatch)
    minted = []

    def fake_mint(key, scopes, subject):
        minted.append(scopes)
        raise RefreshError("invalid_grant: something else")
    monkeypatch.setattr(chat_post, "_mint", fake_mint)
    with pytest.raises(RefreshError):
        chat_post.members_token()
    assert len(minted) == 1


def test_members_token_readonly_success_no_fallback(monkeypatch):
    _stub_key(monkeypatch)
    minted = []
    monkeypatch.setattr(chat_post, "_mint", lambda k, s, sub: minted.append(s) or "NARROW")
    assert chat_post.members_token() == "NARROW"
    assert minted == [[chat_post.MEMBERS_SCOPE]]


def test_directory_token_uses_directory_scope(monkeypatch):
    _stub_key(monkeypatch)
    minted = []
    monkeypatch.setattr(chat_post, "_mint", lambda k, s, sub: minted.append((s, sub)) or "D")
    assert chat_post.directory_token() == "D"
    assert minted == [([chat_post.DIRECTORY_SCOPE], "me@example.com")]
