"""read_task.py: a read-only read of one task (parents, fields, notes, stories, subtasks)."""
import io
import json
import subprocess
import urllib.error
from unittest.mock import Mock

import pytest

import _asana
import read_task


class FakeAsana:
    """Answers GET requests by path, with paging. Records every call. Fails on a non-GET."""

    def __init__(self, tasks, stories=None, subtasks=None, errors=None):
        self.tasks = tasks
        self.stories = stories or {}      # gid -> list of pages (each a list of stories)
        self.subtasks = subtasks or {}    # gid -> list of pages (each a list of subtask rows)
        self.errors = errors or {}        # path -> HTTP code
        self.calls = []

    def __call__(self, method, path, token, data=None, params=None):
        assert method == "GET", f"read_task must only GET, got {method} {path}"
        assert data is None
        self.calls.append((path, dict(params or {})))
        if path in self.errors:
            # urlopen raises with the full URL, query included
            url = f"{_asana.BASE_URL}{path}?opt_fields=x"
            raise urllib.error.HTTPError(url, self.errors[path], "err", {}, io.BytesIO(b"{}"))
        parts = path.strip("/").split("/")
        gid = parts[1]
        if len(parts) == 2:
            return {"data": dict(self.tasks[gid])}
        pages = {"stories": self.stories, "subtasks": self.subtasks}[parts[2]].get(gid, [[]])
        idx = int((params or {}).get("offset", "0") or 0)
        nxt = {"offset": str(idx + 1)} if idx + 1 < len(pages) else None
        return {"data": pages[idx], "next_page": nxt}


def comment(gid, text, who="Ana"):
    return {"gid": gid, "type": "comment", "resource_subtype": "comment_added",
            "created_at": "2026-11-04T00:00:00Z", "created_by": {"name": who},
            "html_text": f"<body>{text}</body>"}


def system(gid, text):
    return {"gid": gid, "type": "system", "resource_subtype": "assigned",
            "created_at": "2026-11-03T00:00:00Z", "created_by": {"name": "Bot"},
            "html_text": text}


@pytest.fixture
def run(monkeypatch, capsys):
    def _run(fake, argv):
        monkeypatch.setattr(read_task, "fetch_token", Mock(return_value="token"))
        monkeypatch.setattr(read_task, "request", fake)
        read_task.main(argv)
        return capsys.readouterr()
    return _run


def basic_tasks():
    return {
        "100": {"gid": "100", "name": "Child", "html_notes": "<body>child notes</body>",
                "parent": {"gid": "50", "name": "Mid"}, "assignee": {"name": "Ana"}},
        "50": {"gid": "50", "name": "Mid", "html_notes": "<body>mid notes</body>",
               "parent": {"gid": "10", "name": "Root"}},
        "10": {"gid": "10", "name": "Root", "html_notes": "<body>root notes</body>", "parent": None},
    }


def tree_tasks():
    tasks = basic_tasks()
    tasks["200"] = {"gid": "200", "name": "Sub", "html_notes": "<body>sub notes</body>"}
    tasks["300"] = {"gid": "300", "name": "Grand", "html_notes": "<body>grand notes</body>"}
    subtasks = {"100": [[{"gid": "200", "name": "Sub"}]],
                "200": [[{"gid": "300", "name": "Grand"}]]}
    stories = {"200": [[comment("s9", "sub comment")]], "300": [[comment("s8", "grand comment")]]}
    return tasks, stories, subtasks


def test_reads_every_story_page_including_system_stories(run):
    fake = FakeAsana(basic_tasks(), stories={"100": [
        [comment("s1", "first page"), system("s2", "assigned to Dee")],
        [comment("s3", "second page")],
    ]})
    out = run(fake, ["100"]).out
    assert "first page" in out and "second page" in out and "assigned to Dee" in out
    assert "--- stories (3):" in out
    story_calls = [p for path, p in fake.calls if path == "/tasks/100/stories"]
    assert [c.get("offset") for c in story_calls] == [None, "1"]


def test_comments_only_leaves_out_system_stories(run):
    fake = FakeAsana(basic_tasks(), stories={"100": [[comment("s1", "kept"), system("s2", "assigned to Dee")]]})
    out = run(fake, ["100", "--comments-only"]).out
    assert "kept" in out and "assigned to Dee" not in out
    assert "--- comments (1):" in out


def test_requests_notes_for_the_task_and_its_parents(run):
    fake = FakeAsana(basic_tasks())
    run(fake, ["100"])
    fields = {path: p.get("opt_fields", "") for path, p in fake.calls if path.count("/") == 2}
    for path in ("/tasks/100", "/tasks/50", "/tasks/10"):
        assert "html_notes" in fields[path].split(","), path


def test_walks_parents_to_the_root_with_notes(run):
    out = run(FakeAsana(basic_tasks()), ["100"]).out
    assert "PARENT 1 (direct parent) 50: Mid" in out
    assert "PARENT 2 (root) 10: Root" in out
    assert "mid notes" in out and "root notes" in out
    assert out.index("PARENT 2") < out.index("=== TASK 100")


def test_parent_loop_stops(run):
    tasks = basic_tasks()
    tasks["10"]["parent"] = {"gid": "50", "name": "Mid"}  # 50 -> 10 -> 50 ...
    fake = FakeAsana(tasks)
    run(fake, ["100"])
    parent_reads = [path for path, _ in fake.calls if path in ("/tasks/50", "/tasks/10")]
    assert parent_reads == ["/tasks/50", "/tasks/10"]


def test_unreadable_parent_does_not_hide_the_task(run):
    fake = FakeAsana(basic_tasks(), errors={"/tasks/50": 403})
    out = run(fake, ["100"]).out
    assert "cannot read (HTTP 403)" in out
    assert "=== TASK 100: Child" in out and "child notes" in out


def test_unreadable_upper_parent_is_not_called_root(run):
    out = run(FakeAsana(basic_tasks(), errors={"/tasks/10": 403}), ["100"]).out
    assert "PARENT 2 (unreadable) 10: Root" in out
    assert "(root)" not in out


def test_default_depth_expands_one_level_and_lists_the_next(run):
    tasks, stories, subtasks = tree_tasks()
    out = run(FakeAsana(tasks, stories=stories, subtasks=subtasks), ["100"]).out
    assert "=== SUBTASK 200: Sub" in out and "sub notes" in out and "sub comment" in out
    assert "=== SUBTASK 300: Grand" in out and "not expanded" in out
    assert "grand notes" not in out


def test_depth_two_expands_grand_subtasks(run):
    tasks, stories, subtasks = tree_tasks()
    out = run(FakeAsana(tasks, stories=stories, subtasks=subtasks), ["100", "--depth", "2"]).out
    assert "grand notes" in out and "grand comment" in out
    assert "not expanded" not in out


def test_depth_zero_lists_subtasks_only(run):
    tasks, stories, subtasks = tree_tasks()
    out = run(FakeAsana(tasks, stories=stories, subtasks=subtasks), ["100", "--depth", "0"]).out
    assert "=== SUBTASK 200: Sub" in out and "not expanded" in out
    assert "sub notes" not in out


def test_reads_every_page_of_subtasks(run):
    tasks = basic_tasks()
    tasks["201"] = {"gid": "201", "name": "First"}
    tasks["202"] = {"gid": "202", "name": "Second"}
    fake = FakeAsana(tasks, subtasks={"100": [[{"gid": "201", "name": "First"}],
                                              [{"gid": "202", "name": "Second"}]]})
    out = run(fake, ["100"]).out
    assert "SUBTASK 201: First" in out and "SUBTASK 202: Second" in out
    assert "--- subtasks (2):" in out


def test_accepts_a_focus_permalink(run):
    fake = FakeAsana(basic_tasks())
    url = "https://app.asana.com/1/1200000000000000/project/1200000000000001/task/100?focus=true"
    run(fake, [url])
    assert fake.calls[0][0] == "/tasks/100"


def test_json_output(run):
    fake = FakeAsana(basic_tasks(), stories={"100": [[comment("s1", "hello")]]})
    doc = json.loads(run(fake, ["100", "--json"]).out)
    assert doc["task"]["gid"] == "100"
    assert [p["gid"] for p in doc["parents"]] == ["50", "10"]
    assert doc["stories"][0]["gid"] == "s1"


def test_forbidden_task_exits_with_a_token_hint(monkeypatch):
    monkeypatch.setattr(read_task, "fetch_token", Mock(return_value="token"))
    monkeypatch.setattr(read_task, "request", FakeAsana({}, errors={"/tasks/100": 403}))
    with pytest.raises(SystemExit) as exc:
        read_task.main(["100"])
    msg = str(exc.value)
    assert "HTTP 403 on GET /tasks/100." in msg and "--token-secret" in msg
    assert "check the gid" in msg


def test_subtask_error_names_the_subtask_and_gives_no_token_hint(monkeypatch, capsys):
    tasks, stories, subtasks = tree_tasks()
    fake = FakeAsana(tasks, stories=stories, subtasks=subtasks, errors={"/tasks/200": 404})
    monkeypatch.setattr(read_task, "fetch_token", Mock(return_value="token"))
    monkeypatch.setattr(read_task, "request", fake)
    with pytest.raises(SystemExit) as exc:
        read_task.main(["100"])
    msg = str(exc.value)
    assert "HTTP 404 on GET /tasks/200." in msg and "nothing printed" in msg
    assert "--token-secret" not in msg
    assert capsys.readouterr().out == ""


def test_secret_read_failure_exits_before_any_request(monkeypatch):
    monkeypatch.setattr(read_task, "fetch_token", Mock(
        side_effect=subprocess.CalledProcessError(1, ["gcloud"], stderr="PERMISSION_DENIED")))
    fake = FakeAsana({})
    monkeypatch.setattr(read_task, "request", fake)
    with pytest.raises(SystemExit) as exc:
        read_task.main(["100"])
    assert "nothing read" in str(exc.value) and "PERMISSION_DENIED" in str(exc.value)
    assert fake.calls == []


@pytest.mark.parametrize("argv, expected", [
    (["--token-secret", "s", "--token-project", "p"], {"secret_name": "s", "project": "p"}),
    ([], {}),
])
def test_token_options_reach_fetch_token(monkeypatch, capsys, argv, expected):
    fetch = Mock(return_value="token")
    monkeypatch.setattr(read_task, "fetch_token", fetch)
    monkeypatch.setattr(read_task, "request", FakeAsana(basic_tasks()))
    read_task.main(["100", *argv])
    assert fetch.call_args.kwargs == expected


def test_prints_start_and_completion_dates(run):
    tasks = basic_tasks()
    tasks["100"].update({"start_on": "2026-11-01", "completed_at": "2026-11-04T05:00:00Z"})
    out = run(FakeAsana(tasks), ["100"]).out
    assert "start: 2026-11-01" in out and "completed at: 2026-11-04T05:00:00Z" in out


def test_retries_used_up_exits_with_nothing_printed(monkeypatch, capsys):
    fake = FakeAsana(basic_tasks())

    def flaky(method, path, token, data=None, params=None):
        if path == "/tasks/100/stories":
            raise RuntimeError("Asana request failed after 5 attempts")
        return fake(method, path, token, data=data, params=params)

    monkeypatch.setattr(read_task, "fetch_token", Mock(return_value="token"))
    monkeypatch.setattr(read_task, "request", flaky)
    with pytest.raises(SystemExit) as exc:
        read_task.main(["100"])
    assert "nothing printed (task 100)" in str(exc.value)
    assert "failed after 5 attempts" in str(exc.value)
    assert capsys.readouterr().out == ""


def test_negative_depth_is_a_usage_error(run):
    with pytest.raises(SystemExit) as exc:
        run(FakeAsana(basic_tasks()), ["100", "--depth", "-1"])
    assert exc.value.code == 2
