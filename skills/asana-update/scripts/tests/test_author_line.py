"""Author line: a write made with the person's own token says an agent wrote it.

No network: _asana.request is faked. conftest.py starts every test with
user_gid, user_email and user_name unset and an empty author cache.
"""
import sys
from types import SimpleNamespace

import pytest

import _asana
import append_description
import attach_file
import create_task
import post_comment

ME = "1200000000000901"
BOT = "1200000000000902"
LINE = "Written by Claude for Jon."
TAG = f"<em>{LINE}</em>\n"


def _fake_users_me(monkeypatch, gid=ME, name="Jon Tester", email="jon@example.com",
                   fail=False, extra=None):
    """Fake _asana.request: /users/me answers as the given user; other calls go to `extra`."""
    calls = []

    def fake(method, path, token, data=None, params=None):
        calls.append((method, path, data))
        if path == "/users/me":
            if fail:
                raise RuntimeError("boom")
            return {"data": {"gid": gid, "name": name, "email": email}}
        if extra:
            return extra(method, path, token, data, params)
        return {"data": {"gid": "555", "name": "My Task", "html_notes": ""}}

    monkeypatch.setattr(_asana, "request", fake)
    return calls


# --- author_line --------------------------------------------------------------

def test_no_identity_configured_still_looks_up_and_adds_the_line(monkeypatch):
    """The usual setup fills in only a token. The token is still looked up
    once, and a person's login gets the line."""
    calls = _fake_users_me(monkeypatch)
    assert _asana.author_line("TOK") == LINE
    assert _asana.author_line("TOK") == LINE
    assert len(calls) == 1


def test_no_identity_configured_agent_account_gets_no_line(monkeypatch):
    monkeypatch.setattr(_asana, "AGENT_USER_GIDS", [BOT])
    _fake_users_me(monkeypatch, gid=BOT, name="Ops Bot")
    assert _asana.author_line("TOK") == ""


def test_failed_lookup_warns_and_adds_the_line(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(_asana, "request", boom)
    assert _asana.author_line("TOK") == "Written by Claude."
    assert "WARNING: could not read who this token belongs to" in capsys.readouterr().err


def test_custom_author_label_is_detected_and_not_doubled(monkeypatch):
    monkeypatch.setattr(_asana, "AUTHOR_LABEL", "Helper")
    _fake_users_me(monkeypatch)
    once = _asana.add_author_line("<body>Done.</body>", "TOK")
    assert once.startswith("<body><em>Written by Helper for Jon.</em>")
    assert _asana.add_author_line(once, "TOK") == once
    assert _asana.starts_with_author_line(once)
    text = _asana.add_author_line_text("Done.", "TOK")
    assert _asana.add_author_line_text(text, "TOK") == text


def test_personal_pat_gets_first_name_line(monkeypatch):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    _fake_users_me(monkeypatch)
    assert _asana.author_line("TOK") == LINE


def test_service_account_gets_no_line(monkeypatch):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    monkeypatch.setattr(_asana, "AGENT_USER_GIDS", [BOT])
    _fake_users_me(monkeypatch, gid=BOT, name="Ops Bot")
    assert _asana.author_line("TOK") == ""


def test_ambient_token_is_looked_up_without_config(monkeypatch):
    monkeypatch.setattr(_asana, "_EXPLICIT_TOKENS", {"TOK"})
    _fake_users_me(monkeypatch)
    assert _asana.author_line("TOK") == LINE


def test_email_fallback_when_user_gid_unset(monkeypatch):
    monkeypatch.setattr(_asana, "MY_EMAIL", "Jon@Example.com")
    _fake_users_me(monkeypatch)
    assert _asana.author_line("TOK") == LINE


def test_email_fallback_other_login_still_gets_a_line(monkeypatch):
    monkeypatch.setattr(_asana, "MY_EMAIL", "jon@example.com")
    _fake_users_me(monkeypatch, gid=BOT, email="bot@example.com")
    assert _asana.author_line("TOK") == LINE


def test_second_login_pat_gets_its_own_first_name(monkeypatch, capsys):
    """A token for another workspace is often a second Asana login (another
    gid). It still gets a line, naming that login."""
    monkeypatch.setattr(_asana, "MY_USER_GID", "1200000000000001")
    _fake_users_me(monkeypatch, gid="1200000000000002", name="Sam Rivera",
                   email="sam@example.org")
    assert _asana.author_line("TOK") == "Written by Claude for Sam."
    assert "NOTE: this token posts as Sam Rivera <sam@example.org>" in capsys.readouterr().err


def test_failed_lookup_still_marks_using_config_name(monkeypatch):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    monkeypatch.setattr(_asana, "MY_NAME", "Jon Tester")
    _fake_users_me(monkeypatch, fail=True)
    assert _asana.author_line("TOK") == LINE


def test_failed_lookup_without_name_marks_without_name(monkeypatch):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    _fake_users_me(monkeypatch, fail=True)
    assert _asana.author_line("TOK") == "Written by Claude."


def test_lookup_is_cached_per_token(monkeypatch):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    calls = _fake_users_me(monkeypatch)
    _asana.author_line("TOK")
    _asana.author_line("TOK")
    assert [c[1] for c in calls] == ["/users/me"]


# --- add_author_line / add_author_line_text / mark_task_data -----------------

@pytest.fixture
def as_person(monkeypatch):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    return _fake_users_me(monkeypatch)


def test_fragment_gets_italic_first_line(as_person):
    assert _asana.add_author_line("Summary here.", "TOK") == TAG + "Summary here."


def test_wrapped_body_keeps_wrapper(as_person):
    out = _asana.add_author_line("<body>Summary.</body>", "TOK")
    assert out == f"<body>{TAG}Summary.</body>"
    assert _asana.wrap_body(out) == out


def test_existing_written_by_claude_line_is_not_doubled(as_person):
    body = "[QA update - written by Claude for Jon]\n\nQA is done."
    assert _asana.add_author_line(body, "TOK") == body
    text = "Written by Claude from Jon's session.\nTLDR: fixed."
    assert _asana.add_author_line_text(text, "TOK") == text


def test_plain_text_gets_plain_line(as_person):
    assert _asana.add_author_line_text("hi", "TOK") == f"{LINE}\nhi"


def test_no_line_leaves_body_untouched(monkeypatch):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    monkeypatch.setattr(_asana, "AGENT_USER_GIDS", [BOT])
    _fake_users_me(monkeypatch, gid=BOT, name="Ops Bot")
    assert _asana.add_author_line("<body>x</body>", "TOK") == "<body>x</body>"
    assert _asana.add_author_line_text("x", "TOK") == "x"


def test_name_is_escaped(monkeypatch):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    _fake_users_me(monkeypatch, name="J<o>n Tester")
    assert _asana.add_author_line("x", "TOK").startswith(
        "<em>Written by Claude for J&lt;o&gt;n.</em>\n")


def test_mark_task_data_html_then_plain_then_none(as_person):
    assert _asana.mark_task_data({"html_notes": "<body>Spec.</body>"}, "TOK") == {
        "html_notes": f"<body>{TAG}Spec.</body>"}
    assert _asana.mark_task_data({"notes": "Spec."}, "TOK") == {"notes": f"{LINE}\nSpec."}
    assert _asana.mark_task_data({"name": "Task"}, "TOK") == {"name": "Task"}


# --- every write path adds the line ------------------------------------------

def test_post_comment_html_and_text(monkeypatch, tmp_path):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    calls = _fake_users_me(monkeypatch)
    monkeypatch.setattr(post_comment, "request", _asana.request)
    monkeypatch.setattr(post_comment, "fetch_token", lambda *a, **k: "TOK")
    monkeypatch.setattr(sys, "argv", ["post_comment.py", "123", "--text", "hi"])
    post_comment.main()
    posted = [c[2] for c in calls if c[0] == "POST"]
    assert posted[-1]["data"]["text"] == f"{LINE}\nhi"
    body = tmp_path / "c.html"
    body.write_text("<strong>Done:</strong> shipped.")
    monkeypatch.setattr(sys, "argv", ["post_comment.py", "123", "--html-file", str(body)])
    post_comment.main()
    posted = [c[2] for c in calls if c[0] == "POST"]
    assert posted[-1]["data"]["html_text"] == f"<body>{TAG}<strong>Done:</strong> shipped.</body>"


def test_post_comment_dry_run_shows_the_author_line(monkeypatch, capsys):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    calls = _fake_users_me(monkeypatch)
    monkeypatch.setattr(post_comment, "fetch_token", lambda *a, **k: "TOK")
    monkeypatch.setattr(sys, "argv", ["post_comment.py", "123", "--text", "hi", "--dry-run"])
    post_comment.main()
    # GET /users/me only: a dry run never writes.
    assert [(c[0], c[1]) for c in calls] == [("GET", "/users/me")]
    out = capsys.readouterr().out
    assert "Author line: added" in out
    assert json_text(out) == f"{LINE}\nhi"


def test_post_comment_dry_run_without_a_token_still_prints(monkeypatch, capsys):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    calls = _fake_users_me(monkeypatch)

    def no_token(*a, **k):
        raise _asana.SetupError("no Asana token")

    monkeypatch.setattr(post_comment, "fetch_token", no_token)
    monkeypatch.setattr(sys, "argv", ["post_comment.py", "123", "--text", "hi", "--dry-run"])
    post_comment.main()
    assert calls == []
    out = capsys.readouterr().out
    assert "Author line: unknown" in out and '"text": "hi"' in out


def json_text(out):
    import json
    start = out.index("{")
    return json.loads(out[start:out.index("\n}", start) + 2])["data"]["text"]


def test_attach_file_post_story(as_person):
    attach_file.post_story("TOK", "123", "Hand-over files below.")
    posted = [c[2] for c in as_person if c[0] == "POST"][-1]["data"]["html_text"]
    assert posted == f"<body>{TAG}Hand-over files below.</body>"


def test_create_task_marks_description_before_create(monkeypatch, as_person):
    seen = {}
    monkeypatch.setattr(create_task, "find_duplicates", lambda *a, **k: [])
    monkeypatch.setattr(create_task, "add_followers_or_warn", lambda *a, **k: None)

    def fake_create(args, token, payload, preexisting):
        seen["payload"] = payload
        return "999"

    monkeypatch.setattr(create_task, "create_or_resume", fake_create)
    payload = {"data": {"name": "T", "html_notes": "<body>Spec.</body>"}}
    args = SimpleNamespace(project="p", name="T", parent=None, allow_duplicates=False)
    assert create_task.create_with_duplicate_guard(args, "TOK", payload) == "999"
    assert seen["payload"]["data"]["html_notes"] == f"<body>{TAG}Spec.</body>"
    # Same dict: a later description restore writes the marked body too.
    assert payload["data"]["html_notes"] == f"<body>{TAG}Spec.</body>"


def test_append_description_marks_new_section(monkeypatch, tmp_path):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)

    def extra(method, path, token, data, params):
        return {"data": {"html_notes": "<body>Old spec.</body>"}}

    calls = _fake_users_me(monkeypatch, extra=extra)
    monkeypatch.setattr(append_description, "request", _asana.request)
    monkeypatch.setattr(append_description, "fetch_token", lambda *a, **k: "TOK")
    new = tmp_path / "new.html"
    new.write_text("New section.")
    monkeypatch.setattr(sys, "argv", ["append_description.py", "123", "--html-file", str(new)])
    append_description.main()
    put = [c[2] for c in calls if c[0] == "PUT"][-1]["data"]["html_notes"]
    assert put == f"<body>Old spec.<hr>{TAG}New section.</body>"


# --- follow-ups: placeholders, the no-line warning, the attach_file echo -------

def test_template_placeholders_count_as_unset():
    assert _asana._cfg_str("you@example.com") == ""
    assert _asana._cfg_str("Your Name") == ""
    assert _asana._cfg_str("your_workspace_gid") == ""
    assert _asana._cfg_str(" Jon Tester ") == "Jon Tester"
    assert _asana._cfg_str(None) == ""
    assert _asana._cfg_str(123) == ""


def test_person_token_mismatch_marks_and_notes_once(monkeypatch, capsys):
    monkeypatch.setattr(_asana, "MY_EMAIL", "jon@example.com")
    _fake_users_me(monkeypatch, gid=BOT, name="Jon Tester", email="jon@example.org")
    assert _asana.author_line("TOK") == LINE
    assert _asana.author_line("TOK") == LINE
    err = capsys.readouterr().err
    assert err.count("NOTE: this token posts as") == 1
    assert "Jon Tester <jon@example.org>" in err


def test_wrong_user_gid_still_marks(monkeypatch, capsys):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    _fake_users_me(monkeypatch, gid=BOT, name="Robin Quill")
    assert _asana.author_line("TOK") == "Written by Claude for Robin."
    assert "NOTE: this token posts as Robin Quill" in capsys.readouterr().err


def test_agent_accounts_stay_quiet(monkeypatch, capsys):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    monkeypatch.setattr(_asana, "AGENT_USER_GIDS", [BOT])
    _fake_users_me(monkeypatch, gid=BOT, name="Automation")
    assert _asana.author_line("TOK") == ""
    assert capsys.readouterr().err == ""


def test_attach_file_echo_shows_the_posted_text(monkeypatch, tmp_path, capsys):
    from test_attach_file import TASK, FakeTask, make

    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    _fake_users_me(monkeypatch)
    fake = FakeTask().install(monkeypatch, agent=False)
    f = make(tmp_path, ("qa.png", b"\x89PNG"))
    body = tmp_path / "b.html"
    body.write_text("QA screenshot.")
    assert attach_file.main([TASK, "--file", f[0], "--comment", "link",
                             "--body-file", str(body)]) == 0
    assert fake.stories[0].startswith(TAG + "QA screenshot.")
    out = capsys.readouterr().out
    assert f"Posted story 777:\n{TAG}QA screenshot." in out


# --- empty bodies: no author-line-only posts -----------------------------------

@pytest.mark.parametrize("body", ["", "   \n", "<body></body>", "<body>\n </body>"])
def test_empty_bodies_are_empty(body):
    assert _asana.is_empty_body(body)


@pytest.mark.parametrize("body", ["x", '<a data-asana-gid="1200000000000405"/>', "<body>Done.</body>"])
def test_real_bodies_are_not_empty(body):
    assert not _asana.is_empty_body(body)


def test_no_line_on_an_empty_body(as_person):
    assert _asana.add_author_line("<body></body>", "TOK") == "<body></body>"
    assert _asana.add_author_line("  ", "TOK") == "  "
    assert _asana.add_author_line_text("", "TOK") == ""
    assert _asana.mark_task_data({"html_notes": "<body></body>"}, "TOK") == {"html_notes": "<body></body>"}


def test_mention_only_comment_still_gets_the_line(as_person):
    mention = '<a data-asana-gid="1200000000000405"/>'
    assert _asana.add_author_line(mention, "TOK") == TAG + mention


@pytest.mark.parametrize("argv", [["--text", ""], ["--text", "  "], ["--html-file", "EMPTY"]])
def test_post_comment_refuses_an_empty_comment(monkeypatch, tmp_path, argv):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    calls = _fake_users_me(monkeypatch)
    monkeypatch.setattr(post_comment, "request", _asana.request)
    monkeypatch.setattr(post_comment, "fetch_token", lambda *a, **k: "TOK")
    empty = tmp_path / "empty.html"
    empty.write_text("\n")
    argv = [str(empty) if a == "EMPTY" else a for a in argv]
    monkeypatch.setattr(sys, "argv", ["post_comment.py", "123", *argv])
    with pytest.raises(SystemExit) as exc:
        post_comment.main()
    assert "empty" in str(exc.value)
    assert calls == []


def test_plain_text_that_looks_like_markup_still_posts(monkeypatch):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    calls = _fake_users_me(monkeypatch)
    monkeypatch.setattr(post_comment, "request", _asana.request)
    monkeypatch.setattr(post_comment, "fetch_token", lambda *a, **k: "TOK")
    monkeypatch.setattr(sys, "argv", ["post_comment.py", "123", "--text", "<body></body>"])
    post_comment.main()
    posted = [c[2] for c in calls if c[0] == "POST"]
    assert posted[-1]["data"]["text"] == f"{LINE}\n<body></body>"


def test_append_description_refuses_an_empty_section(monkeypatch, tmp_path):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME)
    calls = _fake_users_me(monkeypatch)
    monkeypatch.setattr(append_description, "request", _asana.request)
    monkeypatch.setattr(append_description, "fetch_token", lambda *a, **k: "TOK")
    empty = tmp_path / "empty.html"
    empty.write_text("<body></body>\n")
    monkeypatch.setattr(sys, "argv", ["append_description.py", "123", "--html-file", str(empty)])
    with pytest.raises(SystemExit) as exc:
        append_description.main()
    assert "empty" in str(exc.value)
    assert calls == []
