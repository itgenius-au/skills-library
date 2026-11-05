#!/usr/bin/env python3
"""Unit tests for the `delete` subcommand of chat-post.py (self messages only).

Mocked I/O only: no network, no gcloud, no Secret Manager. Same import + mocking style as
test_react_opener.py.
"""
import importlib.util
import pathlib

import pytest

MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "chat-post.py"
_spec = importlib.util.spec_from_file_location("chat_post", MOD_PATH)
chat_post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_post)

MSG = "spaces/S/messages/T.M"


class _Args:
    def __init__(self, message=MSG, yes=False, dry_run=False):
        self.message = message
        self.yes = yes
        self.dry_run = dry_run


def _setup(monkeypatch, sender="users/1", listed_after_delete=False, text="hello world"):
    monkeypatch.setattr(chat_post, "CHAT", {"self_user_id": "users/1"})
    monkeypatch.setattr(chat_post, "delete_token", lambda: "TOK")
    calls = []

    def fake_http(method, url, token, body=None, tolerate=()):
        calls.append((method, url))
        if method == "GET" and url.endswith("/" + MSG):
            return {"name": MSG, "text": text, "sender": {"name": sender, "displayName": "Alex"}}
        if method == "DELETE":
            return {}
        if method == "GET" and "filter=" in url:
            return {"messages": [{"name": MSG}] if listed_after_delete else [{"name": "spaces/S/messages/T.T"}]}
        raise AssertionError(f"unexpected call {method} {url}")

    monkeypatch.setattr(chat_post, "_http", fake_http)
    return calls


def test_rejects_slash_form(monkeypatch):
    calls = _setup(monkeypatch)
    with pytest.raises(SystemExit) as e:
        chat_post.cmd_delete(_Args("spaces/S/messages/T/M", yes=True))
    assert "Invalid message resource name" in str(e.value)
    assert calls == []


def test_refuses_non_self_sender(monkeypatch, capsys):
    calls = _setup(monkeypatch, sender="users/9")
    with pytest.raises(SystemExit) as e:
        chat_post.cmd_delete(_Args(yes=True))
    assert e.value.code != 0
    assert "REFUSED" in capsys.readouterr().err
    assert not any(m == "DELETE" for m, _ in calls)


def test_no_yes_means_no_delete(monkeypatch, capsys):
    calls = _setup(monkeypatch)
    chat_post.cmd_delete(_Args(yes=False))
    out = capsys.readouterr().out
    assert "WOULD DELETE" in out and "hello world" in out and "Alex" in out
    assert not any(m == "DELETE" for m, _ in calls)


def test_dry_run_makes_no_network_call(monkeypatch, capsys):
    monkeypatch.setattr(chat_post, "CHAT", {})

    def boom(*a, **k):
        raise AssertionError("dry-run must not touch the network or mint a token")

    monkeypatch.setattr(chat_post, "_http", boom)
    monkeypatch.setattr(chat_post, "delete_token", boom)
    chat_post.cmd_delete(_Args(dry_run=True, yes=True))
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "DELETE https://chat.googleapis.com/v1/" + MSG in out


def test_success_is_verified_by_thread_list(monkeypatch, capsys):
    calls = _setup(monkeypatch, listed_after_delete=False)
    chat_post.cmd_delete(_Args(yes=True))
    assert f"DELETED {MSG}" in capsys.readouterr().out
    assert [m for m, _ in calls] == ["GET", "DELETE", "GET"]
    assert "thread.name" in __import__("urllib.parse").parse.unquote_plus(calls[-1][1])


def test_thread_still_lists_message_is_failure(monkeypatch, capsys):
    _setup(monkeypatch, listed_after_delete=True)
    with pytest.raises(SystemExit) as e:
        chat_post.cmd_delete(_Args(yes=True))
    assert e.value.code != 0
    cap = capsys.readouterr()
    assert "DELETED " not in cap.out
    assert "NOT VERIFIED" in cap.err


def test_refuses_when_self_user_id_unset(monkeypatch):
    monkeypatch.setattr(chat_post, "CHAT", {})
    monkeypatch.setattr(chat_post, "delete_token", lambda: "TOK")
    monkeypatch.setattr(chat_post, "_http", lambda *a, **k: pytest.fail("no HTTP expected"))
    with pytest.raises(SystemExit):
        chat_post.cmd_delete(_Args(yes=True))


def test_client_assigned_name_is_accepted_and_verified_via_response_thread(monkeypatch, capsys):
    cmsg = "spaces/S/messages/client-my-id"
    canon = "spaces/S/messages/T.M"
    monkeypatch.setattr(chat_post, "CHAT", {"self_user_id": "users/1"})
    monkeypatch.setattr(chat_post, "delete_token", lambda: "TOK")
    calls = []

    def fake_http(method, url, token, body=None, tolerate=()):
        calls.append((method, url))
        if method == "GET" and url.endswith("/" + cmsg):
            return {"name": canon, "text": "hi", "thread": {"name": "spaces/S/threads/T"},
                    "sender": {"name": "users/1", "displayName": "Alex"}}
        if method == "DELETE":
            assert url.endswith("/" + cmsg)
            return {}
        if "filter=" in url:
            return {"messages": []}
        raise AssertionError(f"unexpected call {method} {url}")

    monkeypatch.setattr(chat_post, "_http", fake_http)
    chat_post.cmd_delete(_Args(cmsg, yes=True))
    assert f"DELETED {cmsg}" in capsys.readouterr().out
    assert [m for m, _ in calls] == ["GET", "DELETE", "GET"]


def test_client_name_with_bad_chars_rejected():
    assert not chat_post.valid_delete_target('spaces/S/messages/client-a"b')
    assert not chat_post.valid_delete_target("spaces/S/messages/notclient")
