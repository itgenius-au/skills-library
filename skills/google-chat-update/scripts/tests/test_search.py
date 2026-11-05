#!/usr/bin/env python3
"""Unit tests for chat-post.py `search` (full-history topic search).

Pure-logic tests only: _http and read_token are stubbed, so no network.
"""
import argparse
import datetime
import importlib.util
import pathlib
import urllib.parse

import pytest

MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "chat-post.py"
_spec = importlib.util.spec_from_file_location("chat_post", MOD_PATH)
chat_post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_post)


def _msg(n, ct, text, thread="T1"):
    return {"name": f"spaces/S/messages/{thread}.{n}", "createTime": ct, "text": text,
            "sender": {"name": "users/1"}, "thread": {"name": f"spaces/S/threads/{thread}"}}


def _args(**kw):
    base = dict(space="spaces/S", term="acmewid", terms=None, since="2026-08-25", max_pages=50)
    base.update(kw)
    return argparse.Namespace(**base)


def _stub_pages(monkeypatch, pages):
    """pages: list of response dicts, returned in order. Records the URLs called."""
    calls = []
    it = iter(pages)
    monkeypatch.setattr(chat_post, "read_token", lambda: "TOK")

    def fake_http(method, url, token, *a, **k):
        calls.append(url)
        return next(it)
    monkeypatch.setattr(chat_post, "_http", fake_http)
    return calls


# --- helpers ---

def test_since_iso_explicit():
    assert chat_post.search_since_iso("2026-09-02") == "2026-09-02T00:00:00Z"


def test_since_iso_default_is_180_days():
    today = datetime.date(2026, 10, 10)
    assert chat_post.search_since_iso(None, today=today) == "2026-04-13T00:00:00Z"


def test_since_iso_bad_value_errors():
    with pytest.raises(SystemExit):
        chat_post.search_since_iso("02/09/2026")


def test_search_url_has_quoted_filter_and_token():
    url = chat_post.search_messages_url("spaces/S", "2026-09-02T00:00:00Z", "PT")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["filter"] == ['createTime > "2026-09-02T00:00:00Z"']
    assert q["orderBy"] == ["createTime desc"]
    assert q["pageSize"] == ["1000"]
    assert q["pageToken"] == ["PT"]


def test_search_url_without_token():
    url = chat_post.search_messages_url("spaces/S", "2026-09-02T00:00:00Z")
    assert "pageToken" not in url


def test_message_matches_case_insensitive_any_term():
    m = {"text": "Please check ACMEWID.com"}
    assert chat_post.message_matches(m, ["acmewid"])
    assert chat_post.message_matches(m, ["nope", "check"])
    assert not chat_post.message_matches(m, ["globexcorp"])


def test_message_matches_formatted_text():
    assert chat_post.message_matches({"formattedText": "x acmewid y"}, ["acmewid"])


def test_valid_space_name():
    assert chat_post.valid_space_name("spaces/AAAAexample3")
    assert not chat_post.valid_space_name("spaces/AAAAexample3/threads/x")
    assert not chat_post.valid_space_name("rooms/AAAA")
    assert not chat_post.valid_space_name('spaces/A"B')


# --- cmd_search ---

def test_search_pages_full_history_and_finds_old_thread(monkeypatch, capsys):
    # The match is on page 2, i.e. older than the newest page: the case a
    # `list --limit 100` + grep misses.
    calls = _stub_pages(monkeypatch, [
        {"messages": [_msg(1, "2026-10-07T00:00:00Z", "unrelated", "T9")], "nextPageToken": "P2"},
        {"messages": [_msg(2, "2026-09-02T02:14:18Z", "acmewid.com", "WE1")]},
    ])
    chat_post.cmd_search(_args())
    out = capsys.readouterr().out
    assert len(calls) == 2 and "pageToken=P2" in calls[1]
    assert "thread=spaces/S/threads/WE1" in out
    assert "SEARCHED 2 messages" in out
    assert "oldest seen 2026-09-02T02:14:18Z" in out
    assert "matches=1 in 1 thread(s)" in out
    assert "THREAD spaces/S/threads/WE1 (1 match)" in out


def test_search_extra_terms(monkeypatch, capsys):
    _stub_pages(monkeypatch, [{"messages": [
        _msg(1, "2026-09-03T00:00:00Z", "A&B Rocket Supplies", "A"),
        _msg(2, "2026-09-04T00:00:00Z", "acmewid", "B")]}])
    chat_post.cmd_search(_args(terms=["rocket"]))
    out = capsys.readouterr().out
    assert "matches=2 in 2 thread(s)" in out


def test_search_zero_scanned_warns(monkeypatch, capsys):
    _stub_pages(monkeypatch, [{}])
    chat_post.cmd_search(_args())
    out = capsys.readouterr().out
    assert "SEARCHED 0 messages" in out
    assert "not proof that no thread exists" in out


def test_search_page_cap_warns(monkeypatch, capsys):
    calls = _stub_pages(monkeypatch, [
        {"messages": [_msg(1, "2026-10-01T00:00:00Z", "x")], "nextPageToken": "P2"},
        {"messages": [_msg(2, "2026-09-30T00:00:00Z", "x")], "nextPageToken": "P3"},
    ])
    chat_post.cmd_search(_args(max_pages=2))
    out = capsys.readouterr().out
    assert len(calls) == 2
    assert "older messages were NOT searched" in out


def test_search_rejects_bad_space(monkeypatch):
    monkeypatch.setattr(chat_post, "read_token", lambda: pytest.fail("must not mint"))
    with pytest.raises(SystemExit):
        chat_post.cmd_search(_args(space="spaces/S/threads/T"))


def test_search_rejects_zero_max_pages(monkeypatch):
    monkeypatch.setattr(chat_post, "read_token", lambda: pytest.fail("must not mint"))
    with pytest.raises(SystemExit):
        chat_post.cmd_search(_args(max_pages=0))


def test_search_oldest_is_last_message_not_string_min(monkeypatch, capsys):
    # Newest first. A raw string min would pick "...18.5Z" over "...18Z".
    _stub_pages(monkeypatch, [{"messages": [
        _msg(1, "2026-09-02T02:14:18.5Z", "x"), _msg(2, "2026-09-02T02:14:18Z", "x")]}])
    chat_post.cmd_search(_args())
    assert "oldest seen 2026-09-02T02:14:18Z)" in capsys.readouterr().out


def test_search_argparse_dispatches(monkeypatch):
    seen = {}
    monkeypatch.setattr(chat_post, "cmd_search", lambda a: seen.update(vars(a)))
    monkeypatch.setattr("sys.argv", ["chat-post.py", "search", "spaces/S", "acmewid",
                                     "--term", "rocket", "--since", "2026-08-25"])
    chat_post.main()
    assert seen["term"] == "acmewid"
    assert seen["terms"] == ["rocket"]
    assert seen["since"] == "2026-08-25"
    assert seen["max_pages"] == 50
