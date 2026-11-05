import sys
from unittest.mock import Mock, call

import _asana
import create_task
import find_task


def run_create(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["create_task.py", *args])
    create_task.main()


def mock_asana(monkeypatch, responses):
    token = Mock(return_value="token")
    api_request = Mock(side_effect=responses)
    monkeypatch.setattr(_asana, "fetch_token", token)
    monkeypatch.setattr(_asana, "request", api_request)
    monkeypatch.setattr(create_task, "fetch_token", token, raising=False)
    monkeypatch.setattr(create_task, "request", api_request, raising=False)
    return api_request


def subtask_verify_response(gid, parent):
    return {
        "data": {
            "gid": gid,
            "name": "Child",
            "parent": {"gid": parent},
            "projects": [],
            "memberships": [],
        }
    }


def test_followers_are_added_after_create(monkeypatch, capsys):
    api_request = mock_asana(
        monkeypatch,
        [
            {"data": []},  # dedup: no same-name subtask
            {"data": {"gid": "new"}},  # create
            {"data": {}},  # addFollowers
            subtask_verify_response("new", "parent-1"),
        ],
    )

    run_create(
        monkeypatch, "--parent", "parent-1", "--name", "Child", "--assignee", "111",
        "--follower", "111", "--follower", "222",
    )

    assert call(
        "POST", "/tasks/new/addFollowers", "token",
        data={"data": {"followers": ["111", "222"]}},
    ) in api_request.call_args_list
    out = capsys.readouterr()
    assert "Created: https://app.asana.com/0/0/new/f" in out.out
    assert "NOTE: unassigned" not in out.out


def test_follower_failure_warns_but_create_succeeds(monkeypatch, capsys):
    mock_asana(
        monkeypatch,
        [
            {"data": []},
            {"data": {"gid": "new"}},
            RuntimeError("403"),  # addFollowers fails
            subtask_verify_response("new", "parent-1"),
        ],
    )

    run_create(
        monkeypatch, "--parent", "parent-1", "--name", "Child", "--assignee", "111",
        "--follower", "222",
    )

    out = capsys.readouterr()
    assert "PARTIAL: created https://app.asana.com/0/0/new/f but addFollowers failed" in out.err
    assert "Created: https://app.asana.com/0/0/new/f" in out.out


def test_no_followers_makes_no_follower_call(monkeypatch):
    api_request = mock_asana(
        monkeypatch,
        [{"data": []}, {"data": {"gid": "new"}}, subtask_verify_response("new", "parent-1")],
    )

    run_create(monkeypatch, "--parent", "parent-1", "--name", "Child", "--assignee", "111")

    assert not any("addFollowers" in c.args[1] for c in api_request.call_args_list)


def test_missing_assignee_prints_note_after_link(monkeypatch, capsys):
    mock_asana(
        monkeypatch,
        [{"data": []}, {"data": {"gid": "new"}}, subtask_verify_response("new", "parent-1")],
    )

    run_create(monkeypatch, "--parent", "parent-1", "--name", "Child")

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Created: https://app.asana.com/0/0/new/f"
    assert lines[1].startswith("NOTE: unassigned")


def test_find_task_lists_exact_match_first_and_warns_at_cap(monkeypatch, capsys):
    hits = [{"gid": str(i), "name": f"Weekly check-in | P{i}"} for i in range(99)]
    hits.append({"gid": "target", "name": " weekly check-in |  sam "})
    monkeypatch.setattr(find_task, "fetch_token", Mock(return_value="token"))
    api_request = Mock(return_value={"data": hits})
    monkeypatch.setattr(find_task, "request", api_request)

    find_task.main(["--query", "Weekly check-in | Sam"])

    out = capsys.readouterr()
    assert out.out.splitlines()[0] == "[ ] https://app.asana.com/0/0/target/f"
    assert "WARNING: 100 hits = the cap" in out.err
    assert api_request.call_args.kwargs["params"]["limit"] == 100


def test_find_task_clamps_limit_to_asana_cap(monkeypatch, capsys):
    monkeypatch.setattr(find_task, "fetch_token", Mock(return_value="token"))
    api_request = Mock(return_value={"data": []})
    monkeypatch.setattr(find_task, "request", api_request)

    find_task.main(["--query", "anything", "--limit", "500"])

    assert api_request.call_args.kwargs["params"]["limit"] == 100
    assert "not proof of absence" in capsys.readouterr().out
