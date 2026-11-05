#!/usr/bin/env python3
"""main() tests for post and reply: a --text-file with backticks, `$` and a mention reaches the payload
exactly; an option between the target and the text still parses. No network."""
import importlib.util
import json
import pathlib
import sys

import pytest

MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "chat-post.py"
_spec = importlib.util.spec_from_file_location("chat_post", MOD_PATH)
chat_post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_post)

THREAD = "spaces/S/threads/T"
NASTY = 'Fix `x` for <users/111111111111>: costs $5, "quoted" and \'single\'.\n  indented\n\nlast'


def _run(monkeypatch, capsys, *argv):
    monkeypatch.setattr(chat_post, "CHAT", {})
    monkeypatch.setattr(sys, "argv", ["chat-post.py", *argv])
    chat_post.main()
    head, body = capsys.readouterr().out.split("\n", 1)
    return head, json.loads(body)


def test_text_file_with_backticks_dollar_and_mention_reaches_the_payload(monkeypatch, capsys, tmp_path):
    f = tmp_path / "m.txt"
    f.write_text(NASTY + "\n", encoding="utf-8")
    assert _run(monkeypatch, capsys, "reply", THREAD, "--text-file", str(f), "--dry-run")[1] == {
        "text": NASTY, "thread": {"name": THREAD}}


@pytest.mark.parametrize("argv, head", [
    (["post", "spaces/S", "--identity", "self", "hello", "--dry-run"], "DRY-RUN post as self"),
    (["post", "spaces/S", "--dry-run", "hello"], "DRY-RUN post as bot"),
    (["reply", THREAD, "--identity", "bot", "hello", "--dry-run"], "DRY-RUN reply as bot"),
])
def test_option_between_target_and_text_still_parses(monkeypatch, capsys, argv, head):
    got_head, body = _run(monkeypatch, capsys, *argv)
    assert got_head.startswith(head) and body["text"] == "hello"


@pytest.mark.parametrize("argv", [["post", "spaces/S", "--dry-runn"], ["post", "spaces/S", "--dry-run", "a", "b"],
                                  ["list", "spaces/S", "stray"]])
def test_stray_arguments_are_still_an_error(monkeypatch, capsys, argv):
    with pytest.raises(SystemExit) as e:
        _run(monkeypatch, capsys, *argv)
    assert e.value.code == 2
