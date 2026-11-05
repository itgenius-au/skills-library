"""post_comment.py: the task link printed after a post. No network; request is faked."""
import sys

import pytest

import post_comment as pc

GID = "1200000000000300"
URL = f"https://app.asana.com/0/0/{GID}/f"


def _run(monkeypatch, argv, name="My Task", lookup_fails=False):
    calls = []

    def fake_request(method, path, token, data=None, params=None):
        calls.append((method, path))
        if method == "POST":
            return {"data": {"gid": "555"}}
        if lookup_fails:
            raise RuntimeError("boom")
        return {"data": {"name": name}}

    monkeypatch.setattr(pc, "request", fake_request)
    monkeypatch.setattr(pc, "fetch_token", lambda *a, **k: "TOK")
    monkeypatch.setattr(sys, "argv", ["post_comment.py", GID, *argv])
    pc.main()
    return calls


def test_success_prints_named_link_and_bare_url(monkeypatch, capsys):
    _run(monkeypatch, ["--text", "hi"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"Posted story 555 to {URL}"
    assert lines[1] == f"Task: [My Task]({URL})"
    assert lines[2] == URL


def test_name_lookup_failure_still_prints_bare_url(monkeypatch, capsys):
    _run(monkeypatch, ["--text", "hi"], lookup_fails=True)
    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == "Task: (name lookup failed)"
    assert lines[2] == URL


def test_dry_run_prints_neither(monkeypatch, capsys):
    calls = _run(monkeypatch, ["--text", "hi", "--dry-run"])
    out = capsys.readouterr().out
    assert "Task:" not in out and URL not in out
    assert calls == []


# --- @mentions become followers ---

BODY = ('<a data-asana-gid="111"/> <a data-asana-gid="222"/> please look. '
        'See <a data-asana-gid="333"/>.')
# What Asana stores: each anchor expanded and typed. 333 is a task link.
STORED = ('<body><a data-asana-gid="111" data-asana-type="user">@Kim</a> '
          '<a data-asana-gid="222" data-asana-type="user">@Lou</a> please look. '
          'See <a data-asana-gid="333" data-asana-type="task">Task</a>.</body>')


def _run_routed(monkeypatch, tmp_path, argv, followers=("111", "222"),
                fail_add=False, fail_story=False):
    """A fake that answers by route, so the follower calls can be checked."""
    calls = []
    names = {"111": "Kim", "222": "Lou"}

    def fake_request(method, path, token, data=None, params=None):
        calls.append((method, path, data))
        if method == "POST" and path.endswith("/stories"):
            return {"data": {"gid": "555"}}
        if path == "/stories/555":
            if fail_story:
                raise RuntimeError("story read failed")
            return {"data": {"html_text": STORED}}
        if path.endswith("/addFollowers"):
            if fail_add:
                raise RuntimeError("403")
            return {"data": {}}
        if params and "followers" in params.get("opt_fields", ""):
            return {"data": {"followers": [{"gid": g, "name": names[g]} for g in followers]}}
        return {"data": {"name": "My Task"}}

    body_file = tmp_path / "body.html"
    body_file.write_text(BODY)
    monkeypatch.setattr(pc, "request", fake_request)
    monkeypatch.setattr(pc, "fetch_token", lambda *a, **k: "TOK")
    monkeypatch.setattr(sys, "argv",
                        ["post_comment.py", GID, "--html-file", str(body_file), *argv])
    pc.main()
    return calls


def _add_calls(calls):
    return [c for c in calls if c[1].endswith("/addFollowers")]


def test_mentioned_users_become_followers_and_are_read_back(monkeypatch, tmp_path, capsys):
    calls = _run_routed(monkeypatch, tmp_path, [])
    adds = _add_calls(calls)
    assert len(adds) == 1
    assert adds[0][1] == f"/tasks/{GID}/addFollowers"
    # The task link (333) is not a user, so it is never added.
    assert adds[0][2] == {"data": {"followers": ["111", "222"]}}
    out = capsys.readouterr()
    lines = out.out.splitlines()
    # The paste-ready link lines stay first.
    assert lines[0] == f"Posted story 555 to {URL}"
    assert lines[2] == URL
    assert "Following: Kim, Lou" in out.out
    assert "PARTIAL" not in out.err


def test_comment_without_mentions_makes_no_follower_calls(monkeypatch, tmp_path):
    body_file = tmp_path / "plain.html"
    body_file.write_text("<strong>No one tagged</strong>")
    calls = []

    def fake_request(method, path, token, data=None, params=None):
        calls.append((method, path))
        return {"data": {"gid": "555"}} if method == "POST" else {"data": {"name": "T"}}

    monkeypatch.setattr(pc, "request", fake_request)
    monkeypatch.setattr(pc, "fetch_token", lambda *a, **k: "TOK")
    monkeypatch.setattr(sys, "argv", ["post_comment.py", GID, "--html-file", str(body_file)])
    pc.main()
    assert calls == [("POST", f"/tasks/{GID}/stories"), ("GET", f"/tasks/{GID}")]


def test_no_follow_skips_the_follower_calls(monkeypatch, tmp_path, capsys):
    calls = _run_routed(monkeypatch, tmp_path, ["--no-follow"])
    assert _add_calls(calls) == []
    assert not any(c[1] == "/stories/555" for c in calls)
    assert "Following:" not in capsys.readouterr().out


def test_add_followers_failure_is_partial_and_never_reposts(monkeypatch, tmp_path, capsys):
    calls = _run_routed(monkeypatch, tmp_path, [], fail_add=True)
    posts = [c for c in calls if c[0] == "POST" and c[1].endswith("/stories")]
    assert len(posts) == 1
    err = capsys.readouterr().err
    assert "PARTIAL" in err and "addFollowers failed" in err
    assert "111, 222" in err
    assert "do not post the comment again" in err.lower()


def test_follower_missing_after_read_back_is_reported(monkeypatch, tmp_path, capsys):
    _run_routed(monkeypatch, tmp_path, [], followers=("111",))
    out = capsys.readouterr()
    assert "Following: Kim" in out.out
    assert "PARTIAL" in out.err and "222" in out.err


def test_story_read_failure_falls_back_to_the_written_mentions(monkeypatch, tmp_path, capsys):
    calls = _run_routed(monkeypatch, tmp_path, [], fail_story=True)
    adds = _add_calls(calls)
    # Untyped anchors as written all count, the task link included. If Asana
    # rejects the call for that, the PARTIAL line lists everyone to add by hand.
    assert adds[0][2] == {"data": {"followers": ["111", "222", "333"]}}
    assert "could not read the comment back" in capsys.readouterr().err


def test_dry_run_lists_the_planned_followers(monkeypatch, tmp_path, capsys):
    calls = _run_routed(monkeypatch, tmp_path, ["--dry-run"])
    assert calls == []
    assert ("Will add as followers (after the post, users only): 111, 222, 333"
            in capsys.readouterr().out)


def test_dry_run_with_no_follow_says_followers_are_unchanged(monkeypatch, tmp_path, capsys):
    _run_routed(monkeypatch, tmp_path, ["--dry-run", "--no-follow"])
    out = capsys.readouterr().out
    assert "Will add as followers" not in out
    assert "Followers: not changed (--no-follow)" in out


# --- --token-secret: post with another token (a personal PAT in another workspace) ---

def _run_token(monkeypatch, argv):
    """Record the fetch_token arguments and the token each request uses."""
    fetched, tokens, calls = [], [], []

    def fake_fetch(*a, **k):
        fetched.append((a, k))
        return "PAT" if k.get("secret_name") else "SVC"

    def fake_request(method, path, token, data=None, params=None):
        tokens.append(token)
        calls.append((method, path, data))
        if method == "POST":
            return {"data": {"gid": "555"}}
        return {"data": {"name": "My Task"}}

    monkeypatch.setattr(pc, "request", fake_request)
    monkeypatch.setattr(pc, "fetch_token", fake_fetch)
    monkeypatch.setattr(sys, "argv", ["post_comment.py", GID, *argv])
    pc.main()
    return fetched, tokens, calls


def test_default_run_fetches_the_default_token(monkeypatch):
    fetched, tokens, _ = _run_token(monkeypatch, ["--text", "hi"])
    assert fetched == [((), {})]
    assert set(tokens) == {"SVC"}


def test_token_secret_posts_with_that_secret(monkeypatch, capsys):
    fetched, tokens, calls = _run_token(
        monkeypatch, ["--text", "hi", "--token-secret", "my-pat-secret"])
    assert fetched == [((), {"secret_name": "my-pat-secret"})]
    assert set(tokens) == {"PAT"}
    assert calls[0][:2] == ("POST", f"/tasks/{GID}/stories")
    assert capsys.readouterr().out.splitlines()[0] == f"Posted story 555 to {URL}"


def test_token_secret_keeps_the_author_line(monkeypatch):
    monkeypatch.setattr(pc, "add_author_line_text",
                        lambda text, token: f"LINE[{token}]\n{text}")
    _, _, calls = _run_token(monkeypatch, ["--text", "hi", "--token-secret", "s"])
    assert calls[0][2]["data"]["text"] == "LINE[PAT]\nhi"


def test_token_secret_keeps_the_wrap_body_refusal(monkeypatch, tmp_path):
    body = tmp_path / "bad.html"
    body.write_text("<p>no</p>")
    with pytest.raises(SystemExit) as exc:
        _run_token(monkeypatch, ["--html-file", str(body), "--token-secret", "s"])
    assert "refusing to post" in str(exc.value)


def test_token_secret_keeps_the_follower_step_with_the_same_token(monkeypatch, tmp_path):
    seen = []

    def fake_follow(task_gid, story_gid, html, token, request_fn=None):
        seen.append((task_gid, story_gid, token))

    monkeypatch.setattr(pc, "follow_mentions", fake_follow)
    body = tmp_path / "m.html"
    body.write_text('<a data-asana-gid="111"/> look')
    _run_token(monkeypatch, ["--html-file", str(body), "--token-secret", "s"])
    assert seen == [(GID, "555", "PAT")]


def test_token_secret_dry_run_reads_the_token_and_posts_nothing(monkeypatch, capsys):
    fetched, _, calls = _run_token(
        monkeypatch, ["--text", "hi", "--dry-run", "--token-secret", "s"])
    # The token is read so the dry run can show the author line; nothing is written.
    assert fetched == [((), {"secret_name": "s"})]
    assert not any(c[0] in ("POST", "PUT", "DELETE") for c in calls)
    out = capsys.readouterr().out
    assert '"text": "' in out and 'hi"' in out


def test_empty_token_secret_is_refused(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _run_token(monkeypatch, ["--text", "hi", "--token-secret", "  "])
    assert "--token-secret is empty" in str(exc.value)


def test_unreadable_token_secret_posts_nothing(monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "gcloud", stderr="NOT_FOUND: secret")

    calls = []
    monkeypatch.setattr(pc, "request", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(pc, "fetch_token", boom)
    monkeypatch.setattr(sys, "argv",
                        ["post_comment.py", GID, "--text", "hi", "--token-secret", "nope"])
    with pytest.raises(SystemExit) as exc:
        pc.main()
    assert "nothing posted" in str(exc.value) and "NOT_FOUND" in str(exc.value)
    assert calls == []
