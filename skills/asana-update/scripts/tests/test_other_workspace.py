"""Another workspace, the comment shape check, and edit_comment.py.

A hand-written script that posts with a personal token skips the author line,
the comment shape and the task link in the reply. These tests pin the
supported route. No network: request is faked.
"""
import json
import sys
from types import SimpleNamespace

import pytest

import _asana
import append_description
import edit_comment
import find_task
import post_comment
import update_task

ME_HOME = "1200000000000011"
ME_OTHER = "1200000000000012"
TASK = "1200000000000050"
URL = f"https://app.asana.com/0/0/{TASK}/f"
LINE = "Written by Claude for Alex."

GOOD_BODY = (
    "The Q3 report is drafted and waiting for sign-off. Nothing goes out until the "
    'owner approves it. Draft: <a href="https://docs.example.com/x">Q3 report</a>.\n'
    "<hr>\n"
    "<strong>Details</strong>\n"
    "<ul><li>Section 1: revenue, done.</li>"
    "<li>Section 2: costs, waiting on one invoice.</li></ul>"
)
WALL = "STATUS update. " + ("DONE: item one; item two; item three; item four. " * 30)


# --- token options -------------------------------------------------------------

def _ns(**kw):
    base = {"token_secret": None, "token_project": None}
    base.update(kw)
    return SimpleNamespace(**base)


def test_no_token_options_means_the_default_token():
    assert _asana.token_request(_ns()) == {}


def test_secret_and_project_pair():
    assert _asana.token_request(_ns(token_secret="other-ws-token",
                                    token_project="my-gcp-project")) == {
        "secret_name": "other-ws-token", "project": "my-gcp-project"}




@pytest.mark.parametrize("kw, msg", [
    ({"token_project": "p"}, "--token-project needs --token-secret"),
    ({"token_secret": " "}, "--token-secret is empty"),
])
def test_bad_token_options_are_refused_before_any_read(kw, msg):
    with pytest.raises(SystemExit) as exc:
        _asana.token_request(_ns(**kw))
    assert msg in str(exc.value)


def test_fetch_token_reads_the_named_project(monkeypatch):
    seen = []

    def fake_run(cmd, **k):
        seen.append(cmd)
        return SimpleNamespace(stdout="PAT\n")

    monkeypatch.setattr(_asana, "_TOKEN_CACHE", {})
    monkeypatch.setattr(_asana.subprocess, "run", fake_run)
    assert _asana.fetch_token(secret_name="other-ws-token",
                              project="my-gcp-project") == "PAT"
    assert "--project=my-gcp-project" in seen[0]
    assert "--secret=other-ws-token" in seen[0]


# --- another workspace dry run: author line + summary + <hr> + details ----------

def _fake_other(monkeypatch, module, calls):
    def fake_request(method, path, token, data=None, params=None):
        calls.append((method, path, data))
        if path == "/users/me":
            return {"data": {"gid": ME_OTHER, "name": "Alex Lee",
                             "email": "alex@example.org"}}
        if method == "POST":
            return {"data": {"gid": "555"}}
        return {"data": {"name": "Quarterly report"}}

    monkeypatch.setattr(_asana, "MY_USER_GID", ME_HOME)
    monkeypatch.setattr(_asana, "request", fake_request)
    monkeypatch.setattr(module, "request", fake_request)
    monkeypatch.setattr(module, "fetch_token", lambda **k: "PAT" if k else "SVC")


def _payload(out):
    start = out.index("{")
    return json.loads(out[start:out.index("\n}", start) + 2])


def test_other_ws_dry_run_renders_line_summary_hr_details(monkeypatch, tmp_path, capsys):
    calls = []
    _fake_other(monkeypatch, post_comment, calls)
    body = tmp_path / "status.html"
    body.write_text(GOOD_BODY)
    monkeypatch.setattr(sys, "argv", [
        "post_comment.py", TASK, "--html-file", str(body), "--dry-run",
        "--token-secret", "other-ws-token", "--token-project", "my-gcp-project"])
    post_comment.main()
    captured = capsys.readouterr()
    html = _payload(captured.out)["data"]["html_text"]
    assert html.startswith(f"<body><em>{LINE}</em>\nThe Q3 report is drafted")
    summary, details = html.split("<hr>", 1)
    assert '<a href="https://docs.example.com/x">' in summary
    assert "<strong>Details</strong>" in details
    assert "Author line: added" in captured.out
    assert "SHAPE" not in captured.out + captured.err
    assert not any(c[0] in ("POST", "PUT", "DELETE") for c in calls)


def test_other_ws_live_post_carries_the_line_and_prints_the_link(monkeypatch, tmp_path, capsys):
    calls = []
    _fake_other(monkeypatch, post_comment, calls)
    body = tmp_path / "status.html"
    body.write_text(GOOD_BODY)
    monkeypatch.setattr(sys, "argv", [
        "post_comment.py", TASK, "--html-file", str(body),
        "--token-secret", "other-ws-token", "--token-project", "my-gcp-project"])
    post_comment.main()
    posted = [c[2] for c in calls if c[0] == "POST"][0]["data"]["html_text"]
    assert posted.startswith(f"<body><em>{LINE}</em>")
    out = capsys.readouterr().out.splitlines()
    assert out[1] == f"Task: [Quarterly report]({URL})"


# --- the shape check -------------------------------------------------------------

def test_shape_good_body_passes():
    assert _asana.shape_problems(GOOD_BODY) == ([], [])


def test_shape_wall_with_no_hr_blocks():
    blocking, _ = _asana.shape_problems(WALL)
    assert blocking and "no <hr>" in blocking[0]


def test_shape_long_plain_text_blocks():
    blocking, _ = _asana.shape_problems(WALL, is_html=False)
    assert blocking and "--html-file" in blocking[0]


def test_shape_short_plain_text_passes():
    assert _asana.shape_problems("Done, shipped.", is_html=False) == ([], [])


def test_shape_long_summary_and_unlinked_file_warn():
    body = ("x " * 400) + "see notes.md\n<hr>\ndetail"
    blocking, warnings = _asana.shape_problems(body)
    assert blocking == []
    assert any("summary above the <hr>" in w for w in warnings)
    assert any("no link" in w for w in warnings)


def test_post_comment_refuses_a_wall_live(monkeypatch, tmp_path):
    calls = []
    _fake_other(monkeypatch, post_comment, calls)
    body = tmp_path / "wall.html"
    body.write_text(WALL)
    monkeypatch.setattr(sys, "argv", ["post_comment.py", TASK, "--html-file", str(body)])
    with pytest.raises(SystemExit) as exc:
        post_comment.main()
    assert "refusing to post" in str(exc.value) and "<hr>" in str(exc.value)
    assert calls == []


def test_post_comment_skip_shape_check_posts_the_wall(monkeypatch, tmp_path):
    calls = []
    _fake_other(monkeypatch, post_comment, calls)
    body = tmp_path / "wall.html"
    body.write_text(WALL)
    monkeypatch.setattr(sys, "argv", ["post_comment.py", TASK, "--html-file", str(body),
                                      "--skip-shape-check"])
    post_comment.main()
    assert any(c[0] == "POST" for c in calls)


def test_post_comment_dry_run_reports_the_refusal(monkeypatch, tmp_path, capsys):
    calls = []
    _fake_other(monkeypatch, post_comment, calls)
    body = tmp_path / "wall.html"
    body.write_text(WALL)
    monkeypatch.setattr(sys, "argv", ["post_comment.py", TASK, "--html-file", str(body),
                                      "--dry-run"])
    post_comment.main()
    assert "SHAPE: refused when posted live" in capsys.readouterr().out


# --- other scripts take the token options -----------------------------------------

def test_update_task_uses_the_token_options(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(update_task, "fetch_token", lambda **k: seen.append(k) or "PAT")
    monkeypatch.setattr(update_task, "request",
                        lambda *a, **k: {"data": {"name": "Annual filing"}})
    monkeypatch.setattr(sys, "argv", ["update_task.py", TASK, "--complete",
                                      "--token-secret", "s", "--token-project", "p"])
    update_task.main()
    assert seen == [{"secret_name": "s", "project": "p"}]
    assert f"Task: [Annual filing]({URL})" in capsys.readouterr().out


def test_append_description_uses_the_token_options(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(append_description, "fetch_token", lambda **k: seen.append(k) or "PAT")
    monkeypatch.setattr(append_description, "request",
                        lambda *a, **k: {"data": {"html_notes": ""}})
    new = tmp_path / "n.html"
    new.write_text("New section.")
    monkeypatch.setattr(sys, "argv", ["append_description.py", TASK, "--html-file", str(new),
                                      "--dry-run", "--token-secret", "s"])
    append_description.main()
    assert seen == [{"secret_name": "s"}]


def test_find_task_searches_the_config_workspace(monkeypatch):
    paths = []
    monkeypatch.setattr(_asana, "WORKSPACE", "1200000000000020")
    monkeypatch.setattr(find_task, "fetch_token", lambda **k: "PAT")
    monkeypatch.setattr(find_task, "request",
                        lambda m, path, t, params=None: paths.append(path) or {"data": []})
    find_task.main(["--query", "Annual filing"])
    assert paths == ["/workspaces/1200000000000020/tasks/search"]


def test_find_task_workspace_flag_wins(monkeypatch):
    paths = []
    monkeypatch.setattr(find_task, "fetch_token", lambda **k: "PAT")
    monkeypatch.setattr(find_task, "request",
                        lambda m, path, t, params=None: paths.append(path) or {"data": []})
    find_task.main(["--query", "Annual filing", "--workspace", "1200000000000021"])
    assert paths == ["/workspaces/1200000000000021/tasks/search"]


def test_find_task_without_a_workspace_exits_2(monkeypatch):
    monkeypatch.setattr(_asana, "WORKSPACE", "")
    monkeypatch.setattr(find_task, "fetch_token", lambda **k: pytest.fail("read a token"))
    with pytest.raises(SystemExit) as exc:
        find_task.main(["--query", "x"])
    assert exc.value.code == 2


# --- edit_comment.py ----------------------------------------------------------------

STORY = "1200000000000060"


def _fake_story(monkeypatch, author=ME_OTHER, subtype="comment_added", stored=None):
    calls = []

    def fake_request(method, path, token, data=None, params=None):
        calls.append((method, path, data))
        if path == "/users/me":
            return {"data": {"gid": ME_OTHER, "name": "Alex Lee",
                             "email": "alex@example.org"}}
        if path == f"/stories/{STORY}" and method == "GET":
            if params and "resource_subtype" in params.get("opt_fields", ""):
                return {"data": {"resource_subtype": subtype, "type": "comment",
                                 "created_by": {"gid": author, "name": "Alex Lee"},
                                 "target": {"gid": TASK, "name": "Quarterly report"},
                                 "text": "STATUS old wall"}}
            return {"data": {"html_text": stored or "<body>ok</body>"}}
        return {"data": {}}

    monkeypatch.setattr(_asana, "MY_USER_GID", ME_HOME)
    monkeypatch.setattr(_asana, "request", fake_request)
    monkeypatch.setattr(edit_comment, "request", fake_request)
    monkeypatch.setattr(edit_comment, "fetch_token", lambda **k: "PAT")
    return calls


def test_edit_dry_run_shows_old_and_new_and_writes_nothing(monkeypatch, tmp_path, capsys):
    calls = _fake_story(monkeypatch)
    body = tmp_path / "fix.html"
    body.write_text(GOOD_BODY)
    edit_comment.main([STORY, "--html-file", str(body), "--dry-run",
                       "--token-secret", "other-ws-token"])
    out = capsys.readouterr().out
    assert "STATUS old wall" in out
    assert _payload(out.split("--- new payload ---", 1)[1])["data"]["html_text"].startswith(
        f"<body><em>{LINE}</em>")
    assert "DRY RUN - nothing written" in out
    assert not any(c[0] in ("POST", "PUT", "DELETE") for c in calls)


def test_edit_puts_the_marked_body_and_prints_the_link(monkeypatch, tmp_path, capsys):
    calls = _fake_story(monkeypatch)
    body = tmp_path / "fix.html"
    body.write_text(GOOD_BODY)
    edit_comment.main([STORY, "--html-file", str(body)])
    puts = [c for c in calls if c[0] == "PUT"]
    assert puts[0][1] == f"/stories/{STORY}"
    assert puts[0][2]["data"]["html_text"].startswith(f"<body><em>{LINE}</em>")
    out = capsys.readouterr().out
    assert f"Task: [Quarterly report]({URL})" in out


def test_edit_refuses_someone_elses_comment(monkeypatch, tmp_path):
    calls = _fake_story(monkeypatch, author="999")
    body = tmp_path / "fix.html"
    body.write_text(GOOD_BODY)
    with pytest.raises(SystemExit) as exc:
        edit_comment.main([STORY, "--html-file", str(body)])
    assert "only the author" in str(exc.value)
    assert not any(c[0] == "PUT" for c in calls)


def test_edit_refuses_a_system_story(monkeypatch, tmp_path):
    calls = _fake_story(monkeypatch, subtype="due_date_changed")
    body = tmp_path / "fix.html"
    body.write_text(GOOD_BODY)
    with pytest.raises(SystemExit) as exc:
        edit_comment.main([STORY, "--html-file", str(body)])
    assert "not a comment" in str(exc.value)
    assert not any(c[0] == "PUT" for c in calls)


def test_edit_refuses_a_wall_and_an_empty_body(monkeypatch, tmp_path):
    calls = _fake_story(monkeypatch)
    wall = tmp_path / "wall.html"
    wall.write_text(WALL)
    with pytest.raises(SystemExit) as exc:
        edit_comment.main([STORY, "--html-file", str(wall)])
    assert "<hr>" in str(exc.value)
    with pytest.raises(SystemExit) as exc:
        edit_comment.main([STORY, "--text", "  "])
    assert "empty" in str(exc.value)
    assert calls == []


def test_edit_reports_escaped_storage(monkeypatch, tmp_path, capsys):
    _fake_story(monkeypatch, stored="<body>&lt;p&gt;x</body>")
    body = tmp_path / "fix.html"
    body.write_text(GOOD_BODY)
    edit_comment.main([STORY, "--html-file", str(body)])
    assert "escaped text" in capsys.readouterr().err


# --- more cases ---------------------------------------------------------------

def test_every_token_gets_a_line_with_no_identity_configured(monkeypatch):
    """A machine with no user_gid / user_email still marks a person's token,
    whether it came from the config or from --token-secret."""
    monkeypatch.setattr(_asana, "_TOKEN_CACHE", {})
    monkeypatch.setattr(_asana, "GCP_PROJECT", "proj")
    monkeypatch.setattr(_asana.subprocess, "run",
                        lambda cmd, **k: SimpleNamespace(stdout="PAT\n"))
    monkeypatch.setattr(_asana, "request", lambda *a, **k: {"data": {
        "gid": ME_OTHER, "name": "Alex Lee", "email": "alex@example.org"}})
    assert _asana.author_line("SVC") == LINE        # default token, nothing configured
    token = _asana.fetch_token(secret_name="other-ws-token", project="p")
    assert _asana.author_line(token) == LINE


def test_a_summary_that_mentions_the_rule_still_gets_the_line(monkeypatch):
    monkeypatch.setattr(_asana, "MY_USER_GID", ME_HOME)
    monkeypatch.setattr(_asana, "request", lambda *a, **k: {"data": {
        "gid": ME_OTHER, "name": "Alex Lee"}})
    body = "Fixed: personal-PAT comments now always get the Written by Claude line."
    assert _asana.add_author_line(body, "PAT").startswith(f"<em>{LINE}</em>")


def test_other_ws_live_post_reads_the_named_project(monkeypatch, tmp_path):
    calls, seen = [], []
    _fake_other(monkeypatch, post_comment, calls)
    monkeypatch.setattr(post_comment, "fetch_token", lambda **k: seen.append(k) or "PAT")
    body = tmp_path / "status.html"
    body.write_text(GOOD_BODY)
    monkeypatch.setattr(sys, "argv", [
        "post_comment.py", TASK, "--html-file", str(body),
        "--token-secret", "other-ws-token", "--token-project", "my-gcp-project"])
    post_comment.main()
    assert seen == [{"secret_name": "other-ws-token", "project": "my-gcp-project"}]


def test_attach_file_resume_command_keeps_the_token_options():
    import attach_file
    args = SimpleNamespace(files=["a.pdf"], comment="name", body_file=None, mention=[],
                           no_follow=False,
                           token_secret="other-ws-token", token_project="my-gcp-project")
    cmd = attach_file.resume_command(args, TASK, {"a.pdf": "777"})
    assert "--token-secret other-ws-token --token-project my-gcp-project" in cmd
    assert cmd.endswith("--resume 777")


def test_update_task_bad_secret_exits_cleanly(monkeypatch):
    import subprocess

    def boom(**k):
        raise subprocess.CalledProcessError(1, "gcloud", stderr="NOT_FOUND")

    monkeypatch.setattr(update_task, "fetch_token", boom)
    monkeypatch.setattr(sys, "argv", ["update_task.py", TASK, "--complete",
                                      "--token-secret", "nope"])
    with pytest.raises(SystemExit) as exc:
        update_task.main()
    assert "nothing written" in str(exc.value) and "NOT_FOUND" in str(exc.value)


def test_edit_reports_the_edit_when_the_read_back_fails(monkeypatch, tmp_path, capsys):
    calls = _fake_story(monkeypatch)
    real = edit_comment.request

    def flaky(method, path, token, data=None, params=None):
        if method == "GET" and path == f"/stories/{STORY}" and params and \
                params.get("opt_fields") == "text,html_text":
            raise RuntimeError("timeout")
        return real(method, path, token, data=data, params=params)

    monkeypatch.setattr(edit_comment, "request", flaky)
    body = tmp_path / "fix.html"
    body.write_text(GOOD_BODY)
    edit_comment.main([STORY, "--html-file", str(body)])
    captured = capsys.readouterr()
    assert f"Edited story {STORY}" in captured.out
    assert "read-back failed" in captured.err
    assert sum(1 for c in calls if c[0] == "PUT") == 1


def test_edit_dry_run_keeps_the_old_rich_text(monkeypatch, tmp_path, capsys):
    _fake_story(monkeypatch)
    real = edit_comment.request

    def with_html(method, path, token, data=None, params=None):
        out = real(method, path, token, data=data, params=params)
        if path == f"/stories/{STORY}" and params and "resource_subtype" in params["opt_fields"]:
            out["data"]["html_text"] = '<body>old <a href="https://x">link</a></body>'
        return out

    monkeypatch.setattr(edit_comment, "request", with_html)
    body = tmp_path / "fix.html"
    body.write_text(GOOD_BODY)
    edit_comment.main([STORY, "--html-file", str(body), "--dry-run"])
    assert '<a href="https://x">link</a>' in capsys.readouterr().out


def test_edit_comment_is_executable():
    import os
    assert os.access(edit_comment.__file__, os.X_OK)
