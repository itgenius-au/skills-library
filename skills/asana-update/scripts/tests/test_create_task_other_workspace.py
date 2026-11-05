"""create_task.py and log_time.py with a token for another workspace.

These tests pin the token options on a create: no default workspace in the
request, and the duplicate check, the placement check and the author line all
still run. No network: request is faked.
"""
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

import _asana
import create_task
import log_time

ME_HOME = "1200000000000011"
ME_OTHER = "1200000000000012"
OTHER_WS = "1200000000000020"
PROJECT = "1200000000000030"
SECTION = "1200000000000031"
PARENT = "1200000000000040"
NEW = "1200000000000099"
LINE = "Written by Claude for Alex."
SECRET = ["--token-secret", "other-ws-token", "--token-project", "my-gcp-project"]


class FakeAsana:
    """Answers the calls a create makes; records every call."""

    def __init__(self, existing=(), workspace=OTHER_WS, users=(), lose_create=False,
                 section_lands_on_repair=False, fail_workspace_read=False):
        self.calls = []
        self.existing = list(existing)
        self.workspace = workspace
        self.users = list(users)
        self.created = None
        self.lose_create = lose_create          # the create lands, its response is lost
        self.section_adds = 0                   # addProject calls seen
        self.section_lands_on_repair = section_lands_on_repair
        self.fail_workspace_read = fail_workspace_read

    def __call__(self, method, path, token, data=None, params=None):
        self.calls.append((method, path, data, params))
        if path == "/users/me":
            return {"data": {"gid": ME_OTHER, "name": "Alex Lee",
                             "email": "alex@example.org"}}
        if method == "GET" and (path.endswith("/subtasks") or path.endswith("/tasks")) \
                and not path.startswith("/workspaces"):
            rows = list(self.existing)
            if self.created:
                rows.append({"gid": NEW, "name": self.created, "completed": False})
            return {"data": rows}
        if method == "GET" and path.startswith("/workspaces/"):
            return {"data": self.users}
        if method == "POST" and path in ("/tasks", f"/tasks/{PARENT}/subtasks"):
            self.created = data["data"]["name"]
            if self.lose_create:
                raise TimeoutError("response lost")
            return {"data": {"gid": NEW}}
        if method == "POST" and path == f"/tasks/{NEW}/addProject":
            self.section_adds += 1
            return {"data": {}}
        if method == "POST":
            return {"data": {}}
        if method == "GET" and path == f"/tasks/{NEW}":
            landed = self.section_adds >= (2 if self.section_lands_on_repair else 1)
            section = {"gid": SECTION} if landed else None
            memberships = [{"project": {"gid": PROJECT}, "section": section}]
            return {"data": {"name": self.created, "parent": {"gid": PARENT},
                             "projects": [{"gid": PROJECT}], "memberships": memberships}}
        if method == "GET" and path in (f"/projects/{PROJECT}", f"/tasks/{PARENT}"):
            if self.fail_workspace_read:
                raise RuntimeError("HTTP 403")
            return {"data": {"workspace": {"gid": self.workspace}}}
        raise AssertionError(f"unexpected call {method} {path}")

    def posts(self, path):
        return [c[2] for c in self.calls if c[0] == "POST" and c[1] == path]


def run(monkeypatch, fake, *argv, token="PAT"):
    seen = []

    def fake_fetch(**kw):
        seen.append(kw)
        if kw.get("secret_name"):
            _asana._EXPLICIT_TOKENS.add(token)
        return token

    monkeypatch.setattr(_asana, "MY_USER_GID", ME_HOME)
    monkeypatch.setattr(_asana, "request", fake)
    monkeypatch.setattr(_asana, "paginate",
                        lambda path, tok, params=None: fake("GET", path, tok, params=params)["data"])
    monkeypatch.setattr(_asana, "fetch_token", fake_fetch)
    monkeypatch.setattr(sys, "argv", ["create_task.py", *argv])
    create_task.main()
    return seen


# --- a create in another workspace ---------------------------------------------------

def test_project_create_sends_no_default_workspace(monkeypatch, capsys):
    fake = FakeAsana()
    seen = run(monkeypatch, fake, "--project", PROJECT, "--section", SECTION,
               "--name", "Offsite 2027", "--assignee", "me", "--due", "2027-03-31",
               "--start-on", "2027-03-29", *SECRET)
    assert seen == [{"secret_name": "other-ws-token", "project": "my-gcp-project"}]
    [body] = fake.posts("/tasks")
    assert "workspace" not in body["data"]
    assert body["data"]["projects"] == [PROJECT]
    assert body["data"]["start_on"] == "2027-03-29" and body["data"]["due_on"] == "2027-03-31"
    assert body["data"]["assignee"] == "me"   # Asana reads "me" as the token's owner
    assert fake.posts(f"/tasks/{NEW}/addProject") == [
        {"data": {"project": PROJECT, "section": SECTION}}]
    assert f"Created: {_asana.task_url(NEW)}" in capsys.readouterr().out


def test_workspace_flag_is_sent_with_a_token_option():
    args = create_task.parse_args(["--project", PROJECT, "--name", "X", *SECRET,
                                   "--workspace", OTHER_WS])
    assert create_task.build_payload(args)["data"]["workspace"] == OTHER_WS


def test_no_token_option_sends_the_config_workspace():
    args = create_task.parse_args(["--project", "1", "--name", "X"])
    assert args.token_kwargs == {}
    assert create_task.build_payload(args)["data"]["workspace"] == _asana.WORKSPACE


def test_subtask_create_gets_the_author_line(monkeypatch):
    fake = FakeAsana()
    run(monkeypatch, fake, "--parent", PARENT, "--name", "Book the venue",
        "--notes", "Shortlist attached.", *SECRET)
    [body] = fake.posts(f"/tasks/{PARENT}/subtasks")
    assert body["data"]["notes"] == f"{LINE}\nShortlist attached."
    assert "workspace" not in body["data"] and "projects" not in body["data"]


def test_duplicate_check_still_refuses(monkeypatch, capsys):
    """Positive control: the other-workspace path keeps the duplicate guard."""
    fake = FakeAsana(existing=[{"gid": "5", "name": "Offsite 2027", "completed": False}])
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, fake, "--project", PROJECT, "--name", "Offsite 2027", *SECRET)
    assert exc.value.code == 2
    assert fake.posts("/tasks") == []
    assert "REFUSING" in capsys.readouterr().err


def test_follower_email_is_looked_up_in_the_tasks_workspace(monkeypatch):
    fake = FakeAsana(users=[{"gid": "777", "email": "zee@example.org"}])
    run(monkeypatch, fake, "--parent", PARENT, "--name", "Arrival transfer",
        "--follower", "zee@example.org", *SECRET)
    gets = [c[1] for c in fake.calls if c[0] == "GET"]
    assert f"/tasks/{PARENT}" in gets
    assert f"/workspaces/{OTHER_WS}/users" in gets
    assert f"/workspaces/{_asana.WORKSPACE}/users" not in gets
    assert fake.posts(f"/tasks/{NEW}/addFollowers") == [{"data": {"followers": ["777"]}}]


def test_follower_gids_need_no_lookup(monkeypatch):
    fake = FakeAsana()
    run(monkeypatch, fake, "--project", PROJECT, "--name", "Offsite 2027",
        "--follower", "777", *SECRET)
    assert not any(c[1].startswith("/workspaces/") or c[1] == f"/projects/{PROJECT}"
                   for c in fake.calls)


def test_lost_create_response_is_resumed_not_posted_twice(monkeypatch, capsys):
    fake = FakeAsana(lose_create=True)
    run(monkeypatch, fake, "--project", PROJECT, "--section", SECTION, "--name", "Offsite 2027", *SECRET)
    assert len(fake.posts("/tasks")) == 1
    captured = capsys.readouterr()
    assert "resumed: create had already landed" in captured.err
    assert f"Created: {_asana.task_url(NEW)}" in captured.out


def test_missing_section_is_repaired_and_checked(monkeypatch, capsys):
    fake = FakeAsana(section_lands_on_repair=True)
    run(monkeypatch, fake, "--project", PROJECT, "--section", SECTION, "--name", "Offsite 2027", *SECRET)
    assert fake.section_adds == 2
    assert [c[1] for c in fake.calls if c[1] == f"/tasks/{NEW}"] == [f"/tasks/{NEW}"] * 2
    assert "Created:" in capsys.readouterr().out


def test_known_workspace_skips_the_workspace_read(monkeypatch):
    fake = FakeAsana(users=[{"gid": "777", "email": "zee@example.org"}], fail_workspace_read=True)
    run(monkeypatch, fake, "--parent", PARENT, "--name", "Arrival transfer",
        "--follower", "zee@example.org", *SECRET, "--workspace", OTHER_WS)
    gets = [c[1] for c in fake.calls if c[0] == "GET"]
    assert f"/workspaces/{OTHER_WS}/users" in gets and f"/tasks/{PARENT}" not in gets


def test_failed_workspace_read_creates_nothing(monkeypatch):
    fake = FakeAsana(fail_workspace_read=True)
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, fake, "--parent", PARENT, "--name", "Arrival transfer",
            "--follower", "zee@example.org", *SECRET)
    assert "nothing created" in str(exc.value) and "--workspace" in str(exc.value)
    assert not [c for c in fake.calls if c[0] == "POST"]


def test_bad_secret_creates_nothing(monkeypatch):
    def boom(**kw):
        raise subprocess.CalledProcessError(1, "gcloud", stderr="NOT_FOUND")

    fake = FakeAsana()
    monkeypatch.setattr(_asana, "request", fake)
    monkeypatch.setattr(_asana, "fetch_token", boom)
    monkeypatch.setattr(sys, "argv", ["create_task.py", "--project", PROJECT, "--name", "X",
                                      "--token-secret", "nope"])
    with pytest.raises(SystemExit) as exc:
        create_task.main()
    assert "nothing created" in str(exc.value) and "NOT_FOUND" in str(exc.value)
    assert fake.calls == []


# --- dry run --------------------------------------------------------------------

def _payload(out):
    start = out.index("{")
    return json.loads(out[start:])


def test_dry_run_shows_the_author_line(monkeypatch, capsys):
    fake = FakeAsana()
    run(monkeypatch, fake, "--parent", PARENT, "--name", "Vehicle hire",
        "--notes", "Ref ABC123.", "--dry-run", *SECRET)
    out = capsys.readouterr().out
    assert "Author line: added" in out
    assert _payload(out)["data"]["notes"] == f"{LINE}\nRef ABC123."
    assert [c[1] for c in fake.calls] == ["/users/me"]


def test_dry_run_with_no_description_reads_nothing(monkeypatch, capsys):
    fake = FakeAsana()
    seen = run(monkeypatch, fake, "--parent", PARENT, "--name", "Vehicle hire",
               "--dry-run", *SECRET)
    assert "Author line: none (the task has no description)" in capsys.readouterr().out
    assert seen == [] and fake.calls == []


# --- refusals, before any read ------------------------------------------------------

@pytest.mark.parametrize("argv, msg", [
    (["--project", "1", "--name", "X", "--start-on", "2027-03-29"], "--start-on needs --due"),
    (["--project", "1", "--name", "X", "--start-on", "29/03", "--due", "2027-03-31"],
     "YYYY-MM-DD"),
    (["--project", "1", "--name", "X", "--start-on", "20270329", "--due", "2027-03-31"],
     "YYYY-MM-DD"),
    (["--project", "1", "--name", "X", "--start-on", "2027-03-29", "--due", "31/03/2027"],
     "YYYY-MM-DD"),
    (["--project", "1", "--name", "X", "--start-on", "2027-04-05", "--due", "2027-03-31"],
     "is after --due"),
    (["--project", "1", "--name", "X", "--workspace", "acme"], "digits only"),
    (["--name", "X"], "--project or --parent is required"),
    (["--parent", "1", "--name", "X", "--section", "2"], "--section needs --project"),
])
def test_refused_before_any_read(monkeypatch, capsys, argv, msg):
    monkeypatch.setattr(_asana, "fetch_token",
                        lambda **k: pytest.fail("read a token before refusing"))
    with pytest.raises(SystemExit):
        create_task.parse_args(argv)
    assert msg in capsys.readouterr().err


def test_bad_token_combination_is_refused():
    with pytest.raises(SystemExit) as exc:
        create_task.parse_args(["--project", "1", "--name", "X", "--token-project", "x"])
    assert "--token-project needs --token-secret" in str(exc.value)


# --- log_time.py ----------------------------------------------------------------------

def test_log_time_uses_the_named_token(monkeypatch, capsys):
    seen, calls = [], []
    monkeypatch.setattr(log_time, "fetch_token", lambda **k: seen.append(k) or "PAT")
    monkeypatch.setattr(log_time, "request",
                        lambda m, p, t, data=None, params=None:
                        calls.append((m, p, data)) or {"data": {"gid": "9"}})
    monkeypatch.setattr(sys, "argv", ["log_time.py", PARENT, "--minutes", "30",
                                      "--date", "2027-03-27", *SECRET])
    log_time.main()
    assert seen == [{"personal": True, "secret_name": "other-ws-token",
                     "project": "my-gcp-project"}]
    assert calls == [("POST", f"/tasks/{PARENT}/time_tracking_entries",
                      {"data": {"duration_minutes": 30, "entered_on": "2027-03-27"}})]


def test_log_time_default_is_the_personal_token(monkeypatch):
    seen = []
    monkeypatch.setattr(log_time, "fetch_token", lambda **k: seen.append(k) or "PAT")
    monkeypatch.setattr(log_time, "request", lambda *a, **k: {"data": {"gid": "9"}})
    monkeypatch.setattr(sys, "argv", ["log_time.py", PARENT, "--minutes", "5"])
    log_time.main()
    assert seen == [{"personal": True}]


def test_log_time_bad_secret_logs_nothing(monkeypatch):
    def boom(**k):
        raise subprocess.CalledProcessError(1, "gcloud", stderr="PERMISSION_DENIED")

    monkeypatch.setattr(log_time, "fetch_token", boom)
    monkeypatch.setattr(log_time, "request", lambda *a, **k: pytest.fail("posted"))
    monkeypatch.setattr(sys, "argv", ["log_time.py", PARENT, "--minutes", "5",
                                      "--token-secret", "nope"])
    with pytest.raises(SystemExit) as exc:
        log_time.main()
    assert "nothing logged" in str(exc.value)


def test_namespace_built_by_hand_still_builds():
    args = SimpleNamespace(name="X", assignee=None, notes=None, notes_file=None,
                           html_notes_file=None, due=None, start_on=None, parent=None,
                           project="1", workspace_gid=_asana.WORKSPACE)
    assert create_task.build_payload(args)["data"]["workspace"] == _asana.WORKSPACE
