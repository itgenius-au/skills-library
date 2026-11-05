#!/usr/bin/env python3
"""Unit tests for the `react-opener` subcommand of chat-post.py.

Reacts the pickup emoji on a THREAD'S OPENING (root) message, and skips only when
the operator's OWN emoji is already on that opener. Pure-logic + mocked-I/O only:
no network, no gcloud, no Secret Manager. Mirrors test_chat_post.py's import + mocking style.
"""
import importlib.util
import io
import pathlib
import urllib.error
import urllib.parse
import sys

import pytest

MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "chat-post.py"
_spec = importlib.util.spec_from_file_location("chat_post", MOD_PATH)
chat_post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_post)


# --- thread-name validation: spaces/<S>/threads/<T> (mirrors cmd_reply's check) ---

def test_valid_thread_name_ok():
    assert chat_post.valid_thread_name("spaces/AAAA/threads/TTTT")


def test_valid_thread_name_rejects_message_form():
    assert not chat_post.valid_thread_name("spaces/AAAA/messages/T.M")


def test_valid_thread_name_rejects_missing_threads_segment():
    assert not chat_post.valid_thread_name("spaces/AAAA")


def test_valid_thread_name_rejects_no_spaces_prefix():
    assert not chat_post.valid_thread_name("threads/TTTT")


def test_valid_thread_name_rejects_trailing_slash_extra_segment():
    assert not chat_post.valid_thread_name("spaces/AAAA/threads/TTTT/extra")


def test_valid_thread_name_accepts_real_id_charset():
    # real Chat ids use letters, digits, - and _ (e.g. AAAAexample2 / exThread002)
    assert chat_post.valid_thread_name("spaces/AAAAexample2/threads/exThread002")


def test_valid_thread_name_rejects_quote_in_id():
    # a quote would break out of the double-quoted filter literal
    assert not chat_post.valid_thread_name('spaces/AAA"OR/threads/BBB')


def test_valid_thread_name_rejects_space_in_id():
    # a space would raise an unhandled InvalidURL in the URL path
    assert not chat_post.valid_thread_name("spaces/AA A/threads/BBB")


# --- URL builders: thread.name value MUST be double-quoted (AIP-160 / prior art) ---

def test_thread_messages_list_url_quotes_thread_name_and_orders_asc():
    url = chat_post.thread_messages_list_url("spaces/S/threads/T")
    assert url.startswith("https://chat.googleapis.com/v1/spaces/S/messages?")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["filter"] == ['thread.name = "spaces/S/threads/T"']   # DOUBLE-QUOTED value
    assert q["orderBy"] == ["createTime ASC"]                       # oldest first = opener
    assert q["pageSize"] == ["1"]


def test_own_reactions_list_url_filters_by_user_only():
    # user.name-only filter (NOT emoji) so BOTH the bare and the variation-selector
    # eye forms come back for a Python-side normalized compare (the FE0F fix).
    url = chat_post.own_reactions_list_url("spaces/S/messages/T.OPENER", "users/1")
    assert url.startswith("https://chat.googleapis.com/v1/spaces/S/messages/T.OPENER/reactions?")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["filter"] == ['user.name = "users/1"']


# --- emoji normalization: strip variation selectors so 👁 and 👁️ compare equal ---

def test_emoji_key_strips_variation_selector():
    assert chat_post._emoji_key("\U0001F441️") == chat_post._emoji_key("\U0001F441")


def test_emoji_key_distinguishes_different_emoji():
    assert chat_post._emoji_key("\U0001F441") != chat_post._emoji_key("✅")  # eye vs check


# --- find_thread_opener: oldest returned message, empty -> hard fail ---

def test_find_thread_opener_returns_first_message(monkeypatch):
    captured = {}

    def fake_http(method, url, token, body=None, tolerate=()):
        captured["url"] = url
        captured["method"] = method
        return {"messages": [
            {"name": "spaces/S/messages/T.ROOT", "createTime": "2026-01-01T00:00:00Z"},
            {"name": "spaces/S/messages/T.REPLY", "createTime": "2026-01-02T00:00:00Z"},
        ]}

    monkeypatch.setattr(chat_post, "_http", fake_http)
    opener = chat_post.find_thread_opener("spaces/S/threads/T", "TOK")
    assert opener["name"] == "spaces/S/messages/T.ROOT"
    assert captured["method"] == "GET"
    q = urllib.parse.parse_qs(urllib.parse.urlparse(captured["url"]).query)
    assert q["filter"] == ['thread.name = "spaces/S/threads/T"']   # quoted, correctly encoded


def test_find_thread_opener_empty_hard_fails(monkeypatch):
    monkeypatch.setattr(chat_post, "_http", lambda *a, **k: {"messages": []})
    with pytest.raises(SystemExit):
        chat_post.find_thread_opener("spaces/S/threads/T", "TOK")


def test_find_thread_opener_missing_key_hard_fails(monkeypatch):
    # a response with no `messages` key must also hard-fail, not IndexError
    monkeypatch.setattr(chat_post, "_http", lambda *a, **k: {})
    with pytest.raises(SystemExit):
        chat_post.find_thread_opener("spaces/S/threads/T", "TOK")


# --- own_reaction_present: filtered reactions.list, truthy iff a reaction is returned ---

def test_own_reaction_present_true_exact(monkeypatch):
    monkeypatch.setattr(chat_post, "_http",
        lambda *a, **k: {"reactions": [{"user": {"name": "users/1"}, "emoji": {"unicode": "\U0001F441"}}]})
    assert chat_post.own_reaction_present("spaces/S/messages/T.ROOT", "\U0001F441", "users/1", "TOK") is True


def test_own_reaction_present_true_stored_has_variation_selector(monkeypatch):
    # stored as the Chat-UI form 👁️ (eye + U+FE0F); target is bare 👁 -> MUST still match (FE0F fix)
    monkeypatch.setattr(chat_post, "_http",
        lambda *a, **k: {"reactions": [{"user": {"name": "users/1"}, "emoji": {"unicode": "\U0001F441️"}}]})
    assert chat_post.own_reaction_present("spaces/S/messages/T.ROOT", "\U0001F441", "users/1", "TOK") is True


def test_own_reaction_present_true_target_has_variation_selector(monkeypatch):
    # symmetric: target carries U+FE0F, stored is bare -> match
    monkeypatch.setattr(chat_post, "_http",
        lambda *a, **k: {"reactions": [{"user": {"name": "users/1"}, "emoji": {"unicode": "\U0001F441"}}]})
    assert chat_post.own_reaction_present("spaces/S/messages/T.ROOT", "\U0001F441️", "users/1", "TOK") is True


def test_own_reaction_present_false_different_emoji(monkeypatch):
    # a different emoji by the operator must NOT count as the pickup eye
    monkeypatch.setattr(chat_post, "_http",
        lambda *a, **k: {"reactions": [{"user": {"name": "users/1"}, "emoji": {"unicode": "✅"}}]})
    assert chat_post.own_reaction_present("spaces/S/messages/T.ROOT", "\U0001F441", "users/1", "TOK") is False


def test_own_reaction_present_false_other_user_same_emoji(monkeypatch):
    # a DIFFERENT user's eye must NOT read as yours (client-side user-scope check),
    # even if the server-side user.name filter were ever ignored
    monkeypatch.setattr(chat_post, "_http",
        lambda *a, **k: {"reactions": [{"user": {"name": "users/OTHER"}, "emoji": {"unicode": "\U0001F441"}}]})
    assert chat_post.own_reaction_present("spaces/S/messages/T.ROOT", "\U0001F441", "users/1", "TOK") is False


def test_own_reaction_present_false_empty(monkeypatch):
    monkeypatch.setattr(chat_post, "_http", lambda *a, **k: {"reactions": []})
    assert chat_post.own_reaction_present("spaces/S/messages/T.ROOT", "\U0001F441", "users/1", "TOK") is False


def test_own_reaction_present_false_missing_reactions_key(monkeypatch):
    monkeypatch.setattr(chat_post, "_http", lambda *a, **k: {})
    assert chat_post.own_reaction_present("spaces/S/messages/T.ROOT", "\U0001F441", "users/1", "TOK") is False


def test_own_reaction_present_false_reaction_missing_emoji_field(monkeypatch):
    # a reaction dict with no `emoji` key must not crash and must not match
    monkeypatch.setattr(chat_post, "_http",
        lambda *a, **k: {"reactions": [{"user": {"name": "users/1"}}]})
    assert chat_post.own_reaction_present("spaces/S/messages/T.ROOT", "\U0001F441", "users/1", "TOK") is False


# --- _http tolerate: an already-exists status is swallowed, not a hard exit ---

def _fake_urlopen_raising(code, body=b"{}"):
    def _raise(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(body))
    return _raise


def test_http_tolerate_returns_sentinel_on_409(monkeypatch):
    monkeypatch.setattr(chat_post.urllib.request, "urlopen",
                        _fake_urlopen_raising(409, b'{"error":"ALREADY_EXISTS"}'))
    out = chat_post._http("POST", "https://x/y", "TOK", {"a": 1}, tolerate=(409,))
    assert out.get("__tolerated__") == 409


def test_http_without_tolerate_still_hard_exits_on_409(monkeypatch):
    monkeypatch.setattr(chat_post.urllib.request, "urlopen", _fake_urlopen_raising(409))
    with pytest.raises(SystemExit):
        chat_post._http("POST", "https://x/y", "TOK", {"a": 1})


def test_http_tolerate_does_not_swallow_other_errors(monkeypatch):
    monkeypatch.setattr(chat_post.urllib.request, "urlopen", _fake_urlopen_raising(403))
    with pytest.raises(SystemExit):
        chat_post._http("POST", "https://x/y", "TOK", {"a": 1}, tolerate=(409,))


# --- cmd_react_opener: skip / react / fallback / dry-run / validation ---

class _OpenerArgs:
    def __init__(self, thread, emoji="👁", dry_run=False):
        self.thread = thread
        self.emoji = emoji
        self.dry_run = dry_run


def _stub_common(monkeypatch, opener_name="spaces/S/messages/T.ROOT"):
    monkeypatch.setattr(chat_post, "resolve_react_plan", lambda *a, **k: {"source": "admin_dwd"})
    monkeypatch.setattr(chat_post, "react_token", lambda plan: "TOK")
    monkeypatch.setattr(chat_post, "find_thread_opener",
                        lambda thread, token: {"name": opener_name, "createTime": "t",
                                               "sender": {"name": "users/9"}})


def test_cmd_react_opener_skips_when_own_eye_present(monkeypatch, capsys):
    monkeypatch.setattr(chat_post, "CHAT", {"self_user_id": "users/1"})
    _stub_common(monkeypatch)
    monkeypatch.setattr(chat_post, "own_reaction_present", lambda *a, **k: True)

    def no_post(method, url, token, body=None, tolerate=()):
        raise AssertionError("must NOT POST a reaction when the operator's eye is already present")

    monkeypatch.setattr(chat_post, "_http", no_post)
    chat_post.cmd_react_opener(_OpenerArgs("spaces/S/threads/T"))
    out = capsys.readouterr().out
    assert "kipping" in out                       # "skipping" reported


def test_cmd_react_opener_reacts_when_absent(monkeypatch, capsys):
    monkeypatch.setattr(chat_post, "CHAT", {"self_user_id": "users/1"})
    _stub_common(monkeypatch)
    monkeypatch.setattr(chat_post, "own_reaction_present", lambda *a, **k: False)
    posted = {}

    def cap_http(method, url, token, body=None, tolerate=()):
        posted["method"] = method
        posted["url"] = url
        posted["body"] = body
        return {"name": "r1", "user": {"name": "users/1"}, "emoji": {"unicode": "👁"}}

    monkeypatch.setattr(chat_post, "_http", cap_http)
    chat_post.cmd_react_opener(_OpenerArgs("spaces/S/threads/T"))
    assert posted["method"] == "POST"
    # reacts on the OPENER's message name, not any individual message
    assert posted["url"] == "https://chat.googleapis.com/v1/spaces/S/messages/T.ROOT/reactions"
    assert posted["body"] == {"emoji": {"unicode": "👁"}}


def test_cmd_react_opener_unset_self_id_warns_and_still_reacts(monkeypatch, capsys):
    # self_user_id unset -> cannot check own eye -> LOUD warn AND still react (never a silent skip)
    monkeypatch.setattr(chat_post, "CHAT", {})
    _stub_common(monkeypatch)

    def boom_present(*a, **k):
        raise AssertionError("must not call own_reaction_present when self_user_id is unset")

    monkeypatch.setattr(chat_post, "own_reaction_present", boom_present)
    posted = {}

    def cap_http(method, url, token, body=None, tolerate=()):
        posted["url"] = url
        return {"name": "r1", "user": {"name": "users/1"}, "emoji": {"unicode": "👁"}}

    monkeypatch.setattr(chat_post, "_http", cap_http)
    chat_post.cmd_react_opener(_OpenerArgs("spaces/S/threads/T"))
    err = capsys.readouterr().err
    assert "self_user_id" in err                  # loud warning names the missing config
    assert posted["url"] == "https://chat.googleapis.com/v1/spaces/S/messages/T.ROOT/reactions"


def test_cmd_react_opener_tolerates_already_exists(monkeypatch, capsys):
    monkeypatch.setattr(chat_post, "CHAT", {"self_user_id": "users/1"})
    _stub_common(monkeypatch)
    monkeypatch.setattr(chat_post, "own_reaction_present", lambda *a, **k: False)

    def tolerated_http(method, url, token, body=None, tolerate=()):
        assert tolerate  # cmd must pass a tolerate set for the react POST
        return {"__tolerated__": 409}

    monkeypatch.setattr(chat_post, "_http", tolerated_http)

    def boom_verify(*a, **k):
        raise AssertionError("must not verify a tolerated (already-exists) response")

    monkeypatch.setattr(chat_post, "_verify_reaction", boom_verify)
    chat_post.cmd_react_opener(_OpenerArgs("spaces/S/threads/T"))
    assert "kipping" in capsys.readouterr().out


def test_cmd_react_opener_dry_run_never_mints(monkeypatch, capsys):
    monkeypatch.setattr(chat_post, "CHAT", {"self_user_id": "users/1"})

    def boom(*a, **k):
        raise AssertionError("dry-run must not mint a token, resolve the opener, or POST")

    monkeypatch.setattr(chat_post, "react_token", boom)
    monkeypatch.setattr(chat_post, "_http", boom)
    monkeypatch.setattr(chat_post, "find_thread_opener", boom)
    monkeypatch.setattr(chat_post, "own_reaction_present", boom)
    monkeypatch.setattr(chat_post, "resolve_react_plan", lambda *a, **k: {"source": "admin_dwd"})
    chat_post.cmd_react_opener(_OpenerArgs("spaces/S/threads/T", emoji="✅", dry_run=True))
    assert "DRY-RUN react-opener ✅" in capsys.readouterr().out


def test_cmd_react_opener_dry_run_without_credential(monkeypatch, capsys):
    monkeypatch.setattr(chat_post, "CHAT", {})

    def raise_exit(*a, **k):
        raise SystemExit("no cred")

    monkeypatch.setattr(chat_post, "resolve_react_plan", raise_exit)
    monkeypatch.setattr(chat_post, "react_token", raise_exit)
    monkeypatch.setattr(chat_post, "_http", raise_exit)
    monkeypatch.setattr(chat_post, "find_thread_opener", raise_exit)
    chat_post.cmd_react_opener(_OpenerArgs("spaces/S/threads/T", dry_run=True))
    assert "no react credential configured" in capsys.readouterr().out


def test_cmd_react_opener_rejects_message_name(monkeypatch):
    # a message resource name (dot form) is NOT a valid thread name. Mock every
    # downstream dep to BOOM so the test pins the validation guard specifically:
    # if the guard were removed, execution would hit boom (AssertionError), not a
    # SystemExit - and this keeps the test pure (no token mint, no gcloud, no network).
    def boom(*a, **k):
        raise AssertionError("validation must happen before any token/opener/HTTP work")

    monkeypatch.setattr(chat_post, "resolve_react_plan", boom)
    monkeypatch.setattr(chat_post, "react_token", boom)
    monkeypatch.setattr(chat_post, "find_thread_opener", boom)
    monkeypatch.setattr(chat_post, "own_reaction_present", boom)
    monkeypatch.setattr(chat_post, "_http", boom)
    with pytest.raises(SystemExit):
        chat_post.cmd_react_opener(_OpenerArgs("spaces/S/messages/T.M"))


def test_react_opener_argparse_dispatches(monkeypatch):
    called = {}
    monkeypatch.setattr(chat_post, "cmd_react_opener",
                        lambda a: called.update(thread=a.thread, emoji=a.emoji, dry=a.dry_run))
    monkeypatch.setattr(sys, "argv",
                        ["chat-post.py", "react-opener", "spaces/S/threads/T", "✅", "--dry-run"])
    chat_post.main()
    assert called == {"thread": "spaces/S/threads/T", "emoji": "✅", "dry": True}
