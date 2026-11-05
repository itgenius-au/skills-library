#!/usr/bin/env python3
"""Tests for `read-thread` and `who-reacted` (chat-post.py). The real _http runs; urlopen and the token are stubbed."""
import importlib.util
import io
import json
import pathlib
import types
import urllib.parse

import pytest

MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "chat-post.py"
_spec = importlib.util.spec_from_file_location("chat_post", MOD_PATH)
chat_post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_post)

THREAD = "spaces/AAAAexample1/threads/exThread001"
OPENER = "spaces/AAAAexample1/messages/exThread001.exThread001"


def msg(n, text, **extra):
    return {"name": f"spaces/AAAAexample1/messages/exThread001.m{n}", "createTime": f"2026-11-0{n}T00:00:00Z",
            "sender": {"name": "users/1", "type": "HUMAN"}, "text": text, **extra}


@pytest.fixture
def api(monkeypatch):
    """Stub the token and urlopen. `pages` maps a pageToken ("" for the first page) to the reply."""
    state = types.SimpleNamespace(pages={}, calls=[], tokens=[])

    def urlopen(req, timeout=None):
        state.calls.append((req.get_method(), req.full_url))
        query = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
        return io.BytesIO(json.dumps(state.pages[query.get("pageToken", [""])[0]]).encode())

    monkeypatch.setattr(chat_post, "CHAT", {})
    monkeypatch.setattr(chat_post, "read_token", lambda: state.tokens.append(1) or "TOK")
    monkeypatch.setattr(chat_post.urllib.request, "urlopen", urlopen)
    return state


def _read(thread=THREAD, full=False, as_json=False):
    chat_post.cmd_read_thread(types.SimpleNamespace(thread=thread, full=full, json=as_json))


def _who(message=OPENER):
    chat_post.cmd_who_reacted(types.SimpleNamespace(message=message))


# ---------- read-thread ----------

def test_read_thread_reads_every_page_oldest_first_with_get_only(api, capsys):
    api.pages[""] = {"messages": [msg(1, "first")], "nextPageToken": "p2"}
    api.pages["p2"] = {"messages": [msg(2, "second")]}
    _read()
    out = capsys.readouterr().out
    assert out.splitlines()[:2] == [
        "2026-11-01T00:00:00Z | name=spaces/AAAAexample1/messages/exThread001.m1 | sender=users/1 (HUMAN)", "first"]
    assert out.index("first") < out.index("second")
    assert f"TOTAL 2 message(s) in {THREAD}" in out
    assert [c[0] for c in api.calls] == ["GET", "GET"]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(api.calls[0][1]).query)
    assert query["filter"] == [f'thread.name = "{THREAD}"'] and query["orderBy"] == ["createTime ASC"]


def test_read_thread_shows_attachments_and_reactions_without_downloading(api, capsys):
    attachment = {"name": "spaces/S/messages/T.M/attachments/A", "contentName": "shot.png",
                  "contentType": "image/png", "source": "UPLOADED_CONTENT"}
    api.pages[""] = {"messages": [msg(1, "", attachment=[attachment],
                                     emojiReactionSummaries=[{"emoji": {"unicode": "👁"}, "reactionCount": 2},
                                                             {"emoji": {"customEmoji": {"uid": "c1"}},
                                                              "reactionCount": 1}])]}
    _read()
    out = capsys.readouterr().out
    assert f"  attachment: shot.png | image/png | UPLOADED_CONTENT | {attachment['name']}" in out
    assert "  reaction: 👁 x2" in out and "  reaction: custom:c1 x1" in out
    assert len(api.calls) == 1  # metadata only: no media download


def test_read_thread_cuts_each_text_unless_full(api, capsys):
    api.pages[""] = {"messages": [msg(1, "x" * 300 + "\nsecond line")]}
    _read()
    short = capsys.readouterr().out
    _read(full=True)
    whole = capsys.readouterr().out
    assert "x" * 201 not in short and "second line" not in short
    assert "x" * 300 in whole and "second line" in whole


def test_read_thread_falls_back_to_formatted_text(api, capsys):
    api.pages[""] = {"messages": [{**msg(1, ""), "text": None, "formattedText": "*bold* only"}]}
    _read()
    assert "*bold* only" in capsys.readouterr().out.splitlines()


def test_read_thread_keeps_each_short_text_on_one_line(api, capsys):
    api.pages[""] = {"messages": [msg(1, "line one\nline two")]}
    _read()
    assert "line one / line two" in capsys.readouterr().out.splitlines()


def test_read_thread_json_prints_each_raw_message_and_the_total_on_stderr(api, capsys):
    raw = msg(1, "seen 👁 é", attachment=[{"name": "a"}])
    api.pages[""] = {"messages": [raw]}
    _read(as_json=True)
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert len(lines) == 1 and json.loads(lines[0]) == raw and "👁 é" in lines[0]   # not \u-escaped
    assert "TOTAL 1 message(s)" in captured.err


def test_read_thread_refuses_a_message_name_with_no_call(api):
    with pytest.raises(SystemExit) as e:
        _read(thread=OPENER)
    assert "spaces/<SPACE_ID>/threads/<THREAD_ID>" in str(e.value) and api.calls == [] and api.tokens == []


def test_read_thread_with_no_messages_fails_loudly(api):
    api.pages[""] = {}
    with pytest.raises(SystemExit) as e:
        _read()
    assert "No messages" in str(e.value)


def test_read_thread_stops_at_the_page_cap_and_says_it_is_incomplete(api, monkeypatch, capsys):
    monkeypatch.setattr(chat_post, "THREAD_READ_MAX_PAGES", 2)
    api.pages[""] = {"messages": [msg(1, "a")], "nextPageToken": "p2"}
    api.pages["p2"] = {"messages": [msg(2, "b")], "nextPageToken": "p3"}
    with pytest.raises(SystemExit) as e:
        _read()
    assert e.value.code == 4 and "READ INCOMPLETE" in capsys.readouterr().err


# ---------- who-reacted ----------

def test_who_reacted_lists_each_reaction_on_every_page(api, capsys):
    api.pages[""] = {"reactions": [{"emoji": {"unicode": "👁"}, "user": {"name": "users/113", "type": "HUMAN"}}],
                     "nextPageToken": "p2"}
    api.pages["p2"] = {"reactions": [{"emoji": {"customEmoji": {"uid": "c1"}}, "user": {"name": "users/9", "type": "BOT"}},
                                     {"emoji": {"unicode": "✅"}, "user": {"name": "users/113", "type": "HUMAN"}}]}
    _who()
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["👁 | users/113 | HUMAN", "custom:c1 | users/9 | BOT", "✅ | users/113 | HUMAN",
                     "Names: chat-post.py whois users/113"]
    assert [c[0] for c in api.calls] == ["GET", "GET"]
    assert api.calls[0][1].startswith(f"https://chat.googleapis.com/v1/{OPENER}/reactions?")
    assert urllib.parse.parse_qs(urllib.parse.urlparse(api.calls[0][1]).query)["pageSize"] == ["200"]


def test_who_reacted_with_only_bots_prints_no_whois_line(api, capsys):
    api.pages[""] = {"reactions": [{"emoji": {"unicode": "👍"}, "user": {"name": "users/9", "type": "BOT"}}]}
    _who()
    assert capsys.readouterr().out.splitlines() == ["👍 | users/9 | BOT"]


def test_who_reacted_with_no_reactions_says_so(api, capsys):
    api.pages[""] = {}
    _who()
    assert capsys.readouterr().out.strip() == f"No reactions on {OPENER}."


@pytest.mark.parametrize("bad", ["spaces/S/messages/T/M", "spaces/S/messages/T.M#ignored", "spaces/S/messages/T.M x",
                                 'spaces/S/messages/T.M"', "spaces/S/messages/TM"])
def test_who_reacted_refuses_a_malformed_message_name_with_no_call(api, bad):
    with pytest.raises(SystemExit) as e:
        _who(bad)
    assert "dot-joined" in str(e.value) and api.calls == [] and api.tokens == []


def test_who_reacted_stops_at_the_page_cap(api, monkeypatch, capsys):
    monkeypatch.setattr(chat_post, "THREAD_READ_MAX_PAGES", 1)
    api.pages[""] = {"reactions": [{"emoji": {"unicode": "👁"}, "user": {"name": "users/1", "type": "HUMAN"}}],
                     "nextPageToken": "p2"}
    with pytest.raises(SystemExit) as e:
        _who()
    assert e.value.code == 4 and "READ INCOMPLETE" in capsys.readouterr().err


def test_read_thread_runs_from_the_command_line(api, monkeypatch, capsys):
    api.pages[""] = {"messages": [msg(1, "hello " + "y" * 250)]}
    monkeypatch.setattr(chat_post.sys, "argv", ["chat-post.py", "read-thread", THREAD, "--full"])
    chat_post.main()
    assert "y" * 250 in capsys.readouterr().out


def test_read_thread_json_runs_from_the_command_line(api, monkeypatch, capsys):
    api.pages[""] = {"messages": [msg(1, "raw")]}
    monkeypatch.setattr(chat_post.sys, "argv", ["chat-post.py", "read-thread", THREAD, "--json"])
    chat_post.main()
    assert json.loads(capsys.readouterr().out.splitlines()[0])["text"] == "raw"


def test_who_reacted_runs_from_the_command_line(api, monkeypatch, capsys):
    api.pages[""] = {"reactions": [{"emoji": {"unicode": "👁"}, "user": {"name": "users/7", "type": "HUMAN"}}]}
    monkeypatch.setattr(chat_post.sys, "argv", ["chat-post.py", "who-reacted", OPENER])
    chat_post.main()
    assert capsys.readouterr().out.splitlines()[0] == "👁 | users/7 | HUMAN"
