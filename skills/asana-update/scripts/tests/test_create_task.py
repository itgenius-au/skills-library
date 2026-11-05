import json
import sys
from unittest.mock import Mock, call

import pytest

import _asana
import create_task


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["create_task.py", *args])
    create_task.main()


def mock_asana(monkeypatch, responses):
    token = Mock(return_value="token")
    api_request = Mock(side_effect=responses)
    monkeypatch.setattr(_asana, "fetch_token", token)
    monkeypatch.setattr(_asana, "request", api_request)
    # Keep the test isolated from the current module-level imports while the
    # implementation is refactored to call the shared helper module directly.
    monkeypatch.setattr(create_task, "fetch_token", token, raising=False)
    monkeypatch.setattr(create_task, "request", api_request, raising=False)
    return token, api_request


def test_project_dedup_detects_duplicate_on_second_page(monkeypatch, capsys):
    _, api_request = mock_asana(
        monkeypatch,
        [
            {"data": [{"gid": "other", "name": "Other", "completed": False}],
             "next_page": {"offset": "page-2"}},
            {"data": [{"gid": "duplicate", "name": " SAME NAME ", "completed": False}]},
        ],
    )

    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "--project", "project-1", "--name", "Same Name")

    assert exc.value.code == 2
    assert "REFUSING: 1 task(s)" in capsys.readouterr().err
    assert api_request.call_args_list == [
        call(
            "GET",
            "/projects/project-1/tasks",
            "token",
            params={"opt_fields": "name,gid,completed", "limit": 100},
        ),
        call(
            "GET",
            "/projects/project-1/tasks",
            "token",
            params={
                "opt_fields": "name,gid,completed",
                "limit": 100,
                "offset": "page-2",
            },
        ),
    ]


def test_subtask_dedup_detects_duplicate_under_parent(monkeypatch, capsys):
    _, api_request = mock_asana(
        monkeypatch,
        [{"data": [{"gid": "duplicate", "name": "Child", "completed": True}]}],
    )

    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "--parent", "parent-1", "--name", "child")

    assert exc.value.code == 2
    assert "under parent parent-1" in capsys.readouterr().err
    api_request.assert_called_once_with(
        "GET",
        "/tasks/parent-1/subtasks",
        "token",
        params={"opt_fields": "name,gid,completed", "limit": 100},
    )


def test_create_error_resumes_existing_task_without_second_post(monkeypatch, capsys):
    _, api_request = mock_asana(
        monkeypatch,
        [
            {"data": []},
            RuntimeError("connection lost after send"),
            {"data": [{"gid": "landed", "name": "Risky create", "completed": False}]},
            {
                "data": {
                    "gid": "landed",
                    "name": "Risky create",
                    "parent": None,
                    "projects": [{"gid": "project-1"}],
                    "memberships": [],
                }
            },
        ],
    )

    run_main(
        monkeypatch,
        "--project",
        "project-1",
        "--name",
        "Risky create",
        "--section",
        "",
    )

    captured = capsys.readouterr()
    assert "resumed: create had already landed" in captured.err
    assert "Created: https://app.asana.com/0/0/landed/f" in captured.out
    assert sum(c.args[0] == "POST" and c.args[1] == "/tasks" for c in api_request.call_args_list) == 1


def test_allow_duplicates_create_error_does_not_adopt_preexisting_task(
    monkeypatch, capsys
):
    old_task = {"gid": "old", "name": "Risky create", "completed": False}
    duplicates = Mock(side_effect=[[old_task], [old_task]])
    api_request = Mock(side_effect=RuntimeError("connection lost after send"))
    monkeypatch.setattr(_asana, "fetch_token", Mock(return_value="token"))
    monkeypatch.setattr(_asana, "request", api_request)
    monkeypatch.setattr(create_task, "find_duplicates", duplicates)

    with pytest.raises(SystemExit) as exc:
        run_main(
            monkeypatch,
            "--project",
            "project-1",
            "--name",
            "Risky create",
            "--section",
            "",
            "--allow-duplicates",
        )

    captured = capsys.readouterr()
    assert "UNCERTAIN:" in str(exc.value)
    assert "https://app.asana.com/0/0/old/f" not in captured.out
    assert "Created:" not in captured.out
    assert duplicates.call_count == 2


def test_allow_duplicates_create_error_resumes_only_genuinely_new_task(
    monkeypatch, capsys
):
    old_task = {"gid": "old", "name": "Risky create", "completed": False}
    new_task = {"gid": "new", "name": "Risky create", "completed": False}
    duplicates = Mock(side_effect=[[old_task], [old_task, new_task]])

    def respond(method, path, token, **kwargs):
        if method == "POST" and path == "/tasks":
            raise RuntimeError("connection lost after send")
        if method == "GET" and path == "/tasks/new":
            return {
                "data": {
                    "gid": "new",
                    "parent": None,
                    "projects": [{"gid": "project-1"}],
                    "memberships": [],
                }
            }
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(_asana, "fetch_token", Mock(return_value="token"))
    monkeypatch.setattr(_asana, "request", Mock(side_effect=respond))
    monkeypatch.setattr(create_task, "find_duplicates", duplicates)

    run_main(
        monkeypatch,
        "--project",
        "project-1",
        "--name",
        "Risky create",
        "--section",
        "",
        "--allow-duplicates",
    )

    captured = capsys.readouterr()
    assert "resumed: create had already landed" in captured.err
    assert "Created: https://app.asana.com/0/0/new/f" in captured.out
    assert "https://app.asana.com/0/0/old/f" not in captured.out


def test_missing_section_is_repaired_and_reverified(monkeypatch, capsys):
    _, api_request = mock_asana(
        monkeypatch,
        [
            {"data": []},
            {"data": {"gid": "new-task"}},
            {"data": {}},
            {
                "data": {
                    "gid": "new-task",
                    "parent": None,
                    "projects": [{"gid": "project-1"}],
                    "memberships": [],
                }
            },
            {"data": {}},
            {
                "data": {
                    "gid": "new-task",
                    "parent": None,
                    "projects": [{"gid": "project-1"}],
                    "memberships": [
                        {
                            "project": {"gid": "project-1"},
                            "section": {"gid": "section-1"},
                        }
                    ],
                }
            },
        ],
    )

    run_main(
        monkeypatch,
        "--project",
        "project-1",
        "--section",
        "section-1",
        "--name",
        "Placed task",
    )

    assert "Created: https://app.asana.com/0/0/new-task/f" in capsys.readouterr().out
    add_project = call(
        "POST",
        "/tasks/new-task/addProject",
        "token",
        data={"data": {"project": "project-1", "section": "section-1"}},
    )
    assert api_request.call_args_list.count(add_project) == 2


def test_unrepaired_section_is_reported_as_partial(monkeypatch, capsys):
    missing_section = {
        "data": {
            "gid": "new-task",
            "parent": None,
            "projects": [{"gid": "project-1"}],
            "memberships": [],
        }
    }
    _, api_request = mock_asana(
        monkeypatch,
        [
            {"data": []},
            {"data": {"gid": "new-task"}},
            {"data": {}},
            missing_section,
            {"data": {}},
            missing_section,
        ],
    )

    with pytest.raises(SystemExit) as exc:
        run_main(
            monkeypatch,
            "--project",
            "project-1",
            "--section",
            "section-1",
            "--name",
            "Partially placed task",
        )

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.err.strip() == (
        "PARTIAL: created https://app.asana.com/0/0/new-task/f but "
        "section section-1 membership in project project-1 did not land"
    )
    assert "Created:" not in captured.out
    assert sum(c.args[1] == "/tasks/new-task/addProject" for c in api_request.call_args_list) == 2


def test_dry_run_prints_payload_without_network(monkeypatch, capsys):
    no_token = Mock(side_effect=AssertionError("dry-run fetched a token"))
    no_request = Mock(side_effect=AssertionError("dry-run made an API request"))
    monkeypatch.setattr(_asana, "fetch_token", no_token)
    monkeypatch.setattr(_asana, "request", no_request)
    monkeypatch.setattr(create_task, "fetch_token", no_token, raising=False)
    monkeypatch.setattr(create_task, "request", no_request, raising=False)

    run_main(
        monkeypatch,
        "--project",
        "project-1",
        "--name",
        "Preview task",
        "--notes",
        "preview only",
        "--dry-run",
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "data": {
            "name": "Preview task",
            "notes": "preview only",
            "workspace": _asana.WORKSPACE,
            "projects": ["project-1"],
        }
    }
    no_token.assert_not_called()
    no_request.assert_not_called()


def test_plain_create_reads_notes_file(monkeypatch, capsys, tmp_path):
    # A dropped --notes-file would hide in a dry run: the payload simply has no notes.
    body = tmp_path / "body.txt"
    body.write_text("Line one.\n\nLine two.\n")
    run_main(monkeypatch, "--parent", "parent-1", "--name", "Subtask", "--notes-file", str(body), "--dry-run")

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["notes"] == "Line one.\n\nLine two."


def test_html_notes_file_is_wrapped(monkeypatch, capsys, tmp_path):
    rich = tmp_path / "body.html"
    rich.write_text("<strong>rich</strong>")
    run_main(monkeypatch, "--parent", "parent-1", "--name", "Subtask",
             "--html-notes-file", str(rich), "--dry-run")

    data = json.loads(capsys.readouterr().out)["data"]
    assert data["html_notes"] == "<body><strong>rich</strong></body>"
    assert "notes" not in data


def test_notes_file_and_html_notes_file_together_are_refused(monkeypatch, tmp_path):
    plain = tmp_path / "body.txt"
    plain.write_text("plain")
    rich = tmp_path / "body.html"
    rich.write_text("<strong>rich</strong>")
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "--parent", "parent-1", "--name", "Subtask", "--notes-file", str(plain),
                 "--html-notes-file", str(rich), "--dry-run")
    assert exc.value.code == 2


def test_html_notes_file_with_a_rejected_tag_is_refused(monkeypatch, tmp_path):
    rich = tmp_path / "body.html"
    rich.write_text("<p>para</p>")
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "--parent", "parent-1", "--name", "Subtask",
                 "--html-notes-file", str(rich), "--dry-run")
    assert exc.value.code == 2


def test_notes_and_notes_file_together_are_refused(monkeypatch, tmp_path):
    body = tmp_path / "body.txt"
    body.write_text("x")
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "--parent", "parent-1", "--name", "Subtask", "--notes", "y",
                 "--notes-file", str(body), "--dry-run")
    assert exc.value.code == 2


def test_empty_notes_file_is_refused(monkeypatch, tmp_path):
    body = tmp_path / "empty.txt"
    body.write_text("  \n")
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "--parent", "parent-1", "--name", "Subtask", "--notes-file", str(body), "--dry-run")
    assert exc.value.code == 2


def test_default_section_from_config_is_used(monkeypatch):
    monkeypatch.setattr(_asana, "DEFAULT_SECTIONS", {"project-1": "inbox-1"})
    args = create_task.parse_args(["--project", "project-1", "--name", "T", "--multi-home", "project-1"])
    placements = create_task.intended_placements(args)
    assert placements[0] == {"project": "project-1", "section": "inbox-1", "add_initially": True}


def test_missing_notes_file_is_refused_before_any_call(monkeypatch, tmp_path):
    no_request = Mock(side_effect=AssertionError("made an API request"))
    monkeypatch.setattr(_asana, "request", no_request)
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "--parent", "parent-1", "--name", "Subtask",
                 "--notes-file", str(tmp_path / "missing.txt"), "--dry-run")
    assert exc.value.code == 2
    no_request.assert_not_called()


# --insert-after: place a new subtask after a given sibling.

SET_PARENT = "/tasks/new-task/setParent"
SET_PARENT_BODY = {"data": {"parent": "parent-1", "insert_after": "111"}}


def insert_after_asana(monkeypatch, readback, set_parent_error=None):
    """Fake the plain subtask create; `readback` is the subtask gid order after setParent."""
    def respond(method, path, token, **kwargs):
        if (method, path) == ("GET", "/tasks/parent-1/subtasks"):
            return {"data": [{"gid": gid} for gid in readback]}
        if (method, path) == ("POST", "/tasks/parent-1/subtasks"):
            return {"data": {"gid": "new-task"}}
        if (method, path) == ("GET", "/tasks/new-task"):
            return {"data": {"gid": "new-task", "parent": {"gid": "parent-1"},
                             "projects": [], "memberships": []}}
        if (method, path) == ("POST", SET_PARENT):
            if set_parent_error:
                raise set_parent_error
            return {"data": {}}
        raise AssertionError(f"unexpected request: {method} {path}")

    api_request = Mock(side_effect=respond)
    monkeypatch.setattr(_asana, "fetch_token", Mock(return_value="token"))
    monkeypatch.setattr(_asana, "request", api_request)
    return api_request


def run_insert_after(monkeypatch, *extra):
    run_main(monkeypatch, "--parent", "parent-1", "--name", "Child",
             "--insert-after", "111", *extra)


def test_insert_after_places_subtask_and_reports_it(monkeypatch, capsys):
    api_request = insert_after_asana(monkeypatch, ["111", "new-task", "222"])

    run_insert_after(monkeypatch)

    captured = capsys.readouterr()
    assert "Created: https://app.asana.com/0/0/new-task/f" in captured.out
    assert "Placed after 111" in captured.out
    assert "WARNING" not in captured.err
    assert call("POST", SET_PARENT, "token", data=SET_PARENT_BODY) in api_request.call_args_list


def test_insert_after_set_parent_failure_warns_and_exits_zero(monkeypatch, capsys):
    api_request = insert_after_asana(
        monkeypatch, ["new-task", "111"], set_parent_error=RuntimeError("boom")
    )

    run_insert_after(monkeypatch)  # no SystemExit: exit 0

    captured = capsys.readouterr()
    assert "Created: https://app.asana.com/0/0/new-task/f" in captured.out
    assert "Placed after" not in captured.out
    assert (
        "WARNING: created new-task but could not place it after 111: boom. "
        "Move it in Asana."
    ) in captured.err
    # Never retry the create, never delete.
    creates = [c for c in api_request.call_args_list if c.args[:2] == ("POST", "/tasks/parent-1/subtasks")]
    assert len(creates) == 1
    assert not [c for c in api_request.call_args_list if c.args[0] == "DELETE"]


@pytest.mark.parametrize(
    "readback",
    [
        ["new-task", "111", "222"],  # left at the top
        ["111", "222", "new-task"],  # after a different sibling
        ["111", "222"],  # missing from the list
    ],
)
def test_insert_after_wrong_readback_order_warns(monkeypatch, capsys, readback):
    insert_after_asana(monkeypatch, readback)

    run_insert_after(monkeypatch)

    captured = capsys.readouterr()
    assert "Created: https://app.asana.com/0/0/new-task/f" in captured.out
    assert "Placed after" not in captured.out
    assert (
        "WARNING: created new-task but could not place it after 111: "
        "the read-back shows a different position. Move it in Asana."
    ) in captured.err


@pytest.mark.parametrize(
    "argv",
    [
        ["--name", "Child", "--project", "project-1", "--insert-after", "111"],  # no --parent
        ["--parent", "parent-1", "--name", "Child", "--project", "project-1", "--insert-after", "111"],
        ["--parent", "parent-1", "--name", "Child", "--insert-after", "11a"],
        ["--parent", "parent-1", "--name", "Child", "--insert-after", ""],
        ["--parent", "parent-1", "--name", "Child", "--insert-after", "https://x/1"],
    ],
)
def test_insert_after_bad_combinations_are_refused_before_any_call(monkeypatch, capsys, argv):
    no_request = Mock(side_effect=AssertionError("made an API request"))
    monkeypatch.setattr(_asana, "request", no_request)
    monkeypatch.setattr(_asana, "fetch_token", Mock(side_effect=AssertionError("fetched a token")))

    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, *argv)

    assert exc.value.code == 2
    assert "--insert-after" in capsys.readouterr().err  # refused by its own guard
    no_request.assert_not_called()


def test_insert_after_dry_run_shows_request_and_writes_nothing(monkeypatch, capsys):
    no_request = Mock(side_effect=AssertionError("dry-run made an API request"))
    monkeypatch.setattr(_asana, "fetch_token", Mock(side_effect=AssertionError("fetched a token")))
    monkeypatch.setattr(_asana, "request", no_request)

    run_insert_after(monkeypatch, "--dry-run")

    out = capsys.readouterr().out
    assert "/tasks/<new-task-gid>/setParent" in out
    assert '"insert_after": "111"' in out
    assert '"parent": "parent-1"' in out
    no_request.assert_not_called()
