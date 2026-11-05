#!/usr/bin/env python3
"""Tests for `whois` (chat-post.py). The real _http runs; urlopen and the token are stubbed."""
import importlib.util
import io
import json
import pathlib
import types
import urllib.error
import urllib.parse

import pytest

MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "chat-post.py"
_spec = importlib.util.spec_from_file_location("chat_post", MOD_PATH)
chat_post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_post)

SAM, ALEX = "users/111111111111", "users/222222222222"
USERS = {"111111111111": {"primaryEmail": "sam@example.com", "orgUnitPath": "/Staff",
                                   "name": {"fullName": "Sam Sample"}, "suspended": False},
         "222222222222": {"primaryEmail": "alex@example.com", "orgUnitPath": "/Admins",
                                   "name": {"fullName": "Alex Example"}, "suspended": True}}


@pytest.fixture
def api(monkeypatch):
    """Stub the token and urlopen: users/403 and users/404 answer with that HTTP error."""
    calls = []

    def urlopen(req, timeout=None):
        calls.append((req.get_method(), req.full_url))
        n = req.full_url.split("/users/", 1)[1].split("?", 1)[0]
        if n in ("403", "404"):
            raise urllib.error.HTTPError(req.full_url, int(n), "x", {}, io.BytesIO(b"{}"))
        return io.BytesIO(json.dumps(USERS[n]).encode())

    monkeypatch.setattr(chat_post, "CHAT", {})
    monkeypatch.setattr(chat_post, "directory_token", lambda: "TOK")
    monkeypatch.setattr(chat_post.urllib.request, "urlopen", urlopen)
    return calls


def _whois(*ids):
    chat_post.cmd_whois(types.SimpleNamespace(users=list(ids)))


def test_success_lines_come_from_one_read_only_admin_view_get_each(api, capsys):
    _whois(SAM, ALEX)
    assert capsys.readouterr().out.splitlines() == [
        f"{SAM} | sam@example.com | Sam Sample | /Staff | suspended=no",
        f"{ALEX} | alex@example.com | Alex Example | /Admins | suspended=yes"]
    assert [c[0] for c in api] == ["GET", "GET"]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(api[0][1]).query)
    assert q["viewType"] == ["admin_view"] and "orgUnitPath" in q["fields"][0]


def test_403_404_and_invalid_ids_print_a_line_and_the_next_id_still_runs(api, capsys):
    with pytest.raises(SystemExit) as e:
        _whois("users/403", "users/404", "users/abc", ALEX)
    assert e.value.code == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("users/403 | FORBIDDEN (403)") and lines[1].startswith("users/404 | NOT FOUND (404)")
    assert lines[2].startswith("users/abc | INVALID") and lines[3].startswith(f"{ALEX} | alex@example.com")
    assert len(api) == 3  # the invalid id made no call


def test_token_failure_is_one_plain_line(monkeypatch):
    from google.auth.exceptions import RefreshError

    monkeypatch.setattr(chat_post, "directory_token", lambda: (_ for _ in ()).throw(
        RefreshError("unauthorized_client: scope not granted")))
    with pytest.raises(SystemExit) as e:
        _whois(SAM)
    assert chat_post.DIRECTORY_SCOPE in str(e.value) and "unauthorized_client" in str(e.value)
