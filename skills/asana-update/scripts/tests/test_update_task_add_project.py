"""update_task.py --add-project: cross-post an existing task, with a read before and after."""
import json
import sys

import pytest

import update_task

TASK = "1234567890"
MEMBERSHIP_FIELDS = (
    "memberships.project.gid",
    "memberships.project.name",
    "memberships.section.gid",
    "memberships.section.name",
)


class FakeAsana:
    """Holds the task's memberships. Like Asana, addProject on a project that holds the task moves it."""

    def __init__(self, memberships=(), lose_response=False, lose_write=False, refuse=(), fail_reads=()):
        self.memberships = {m[0]: m[1] for m in memberships}
        self.lose_response = lose_response  # the write lands, its response is lost
        self.lose_write = lose_write  # the write never lands, and the call fails
        self.refuse = refuse  # project gids Asana refuses
        self.fail_reads = fail_reads  # 1 = the first read fails, 2 = the second
        self.reads = 0
        self.calls = []
        self.posts = []
        self.puts = []

    def request(self, method, path, token, data=None, params=None):
        self.calls.append(method)
        if method == "GET":
            assert path == f"/tasks/{TASK}"
            for field in MEMBERSHIP_FIELDS:
                assert field in params["opt_fields"]
            self.reads += 1
            if self.reads in self.fail_reads:
                raise RuntimeError("Asana request failed after 5 attempts")
            return {"data": {"memberships": [
                {"project": {"gid": p, "name": f"Board {p}"},
                 "section": {"gid": s, "name": f"Section {s}"} if s else None}
                for p, s in self.memberships.items()
            ]}}
        if method == "PUT":
            self.puts.append(data)
            return {"data": {"name": "An idea"}}
        assert method == "POST" and path == f"/tasks/{TASK}/addProject"
        body = data["data"]
        self.posts.append(body)
        if body["project"] in self.refuse:
            raise RuntimeError("HTTP 403")
        if self.lose_write:
            raise TimeoutError("the request was lost")
        self.memberships[body["project"]] = body.get("section", "last")
        if self.lose_response:
            raise TimeoutError("the response was lost")
        return {"data": {}}


def run(monkeypatch, fake, *argv):
    monkeypatch.setattr(update_task, "request", fake.request)
    monkeypatch.setattr(update_task, "fetch_token", lambda **kwargs: "token")
    monkeypatch.setattr(sys, "argv", ["update_task.py", TASK, *argv])
    update_task.main()


def no_io(*args, **kwargs):
    raise AssertionError("a dry run must not touch Asana or the secret store")


def test_dry_run_shows_the_placement_and_touches_nothing(monkeypatch, capsys):
    monkeypatch.setattr(update_task, "request", no_io)
    monkeypatch.setattr(update_task, "fetch_token", no_io)
    monkeypatch.setattr(sys, "argv", ["update_task.py", TASK, "--add-project", "11=22", "--dry-run"])
    update_task.main()
    out = json.loads(capsys.readouterr().out)
    assert out["add_project"] == [{"project": "11", "section": "22"}]


@pytest.mark.parametrize("value", ["Empower", "11=", "=22", "11=22=33", "٣"])
def test_a_bad_value_is_refused_before_any_io(monkeypatch, capsys, value):
    monkeypatch.setattr(update_task, "request", no_io)
    monkeypatch.setattr(update_task, "fetch_token", no_io)
    monkeypatch.setattr(sys, "argv", ["update_task.py", TASK, "--add-project", value])
    with pytest.raises(SystemExit) as exc:
        update_task.main()
    assert exc.value.code == 2
    assert "bad --add-project" in capsys.readouterr().err


def test_cross_post_alone_sends_no_put(monkeypatch, capsys):
    fake = FakeAsana(memberships=[("99", "1")])
    run(monkeypatch, fake, "--add-project", "11=22")
    assert fake.posts == [{"project": "11", "section": "22"}]
    assert fake.puts == []
    assert "Cross-posted: Board 11 / Section 22" in capsys.readouterr().out


def test_no_section_sends_no_section_key(monkeypatch, capsys):
    fake = FakeAsana()
    run(monkeypatch, fake, "--add-project", "11")
    assert fake.posts == [{"project": "11"}]


def test_a_field_and_two_boards_land_field_first(monkeypatch, capsys):
    fake = FakeAsana()
    run(monkeypatch, fake, "--custom-field", "5=6", "--add-project", "11=22", "--add-project", "33=44")
    assert fake.puts == [{"data": {"custom_fields": {"5": "6"}}}]
    assert fake.posts == [{"project": "11", "section": "22"}, {"project": "33", "section": "44"}]
    assert fake.calls.index("PUT") < fake.calls.index("POST")


def test_a_board_the_task_was_moved_on_is_left_where_it_is(monkeypatch, capsys):
    fake = FakeAsana(memberships=[("11", "99")])
    run(monkeypatch, fake, "--add-project", "11=22")
    assert fake.posts == []
    assert fake.memberships == {"11": "99"}
    assert "Already on: Board 11 / Section 99" in capsys.readouterr().out


def test_a_membership_with_no_section_is_left_alone(monkeypatch, capsys):
    fake = FakeAsana(memberships=[("11", None)])
    run(monkeypatch, fake, "--add-project", "11=22")
    assert fake.posts == []
    assert "Already on: Board 11 / None" in capsys.readouterr().out


def test_no_section_given_leaves_a_task_already_on_the_board_alone(monkeypatch, capsys):
    fake = FakeAsana(memberships=[("11", "22")])
    run(monkeypatch, fake, "--add-project", "11")
    assert fake.posts == []
    assert fake.memberships == {"11": "22"}


def test_a_lost_response_that_landed_counts_as_landed(monkeypatch, capsys):
    fake = FakeAsana(lose_response=True)
    run(monkeypatch, fake, "--add-project", "11=22")
    captured = capsys.readouterr()
    assert "Cross-posted: Board 11" in captured.out
    assert "reading the task to check" in captured.err


def test_a_lost_write_that_did_not_land_prints_partial(monkeypatch, capsys):
    fake = FakeAsana(lose_write=True)
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, fake, "--add-project", "11=22")
    assert "PARTIAL" in str(exc.value.code)
    captured = capsys.readouterr()
    assert "reading the task to check" in captured.err
    assert "Cross-posted" not in captured.out


def test_a_task_on_the_board_in_the_wrong_section_after_the_write_prints_partial(monkeypatch, capsys):
    fake = FakeAsana(lose_write=True)
    real = fake.request

    def wrong_section(method, path, token, data=None, params=None):
        if method == "POST":
            fake.memberships["11"] = "77"
        return real(method, path, token, data=data, params=params)

    fake.request = wrong_section
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, fake, "--add-project", "11=22")
    assert "PARTIAL" in str(exc.value.code)


def test_one_refused_board_names_only_that_board(monkeypatch, capsys):
    fake = FakeAsana(refuse=("33",))
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, fake, "--add-project", "11=22", "--add-project", "33=44")
    assert "PARTIAL" in str(exc.value.code)
    assert "33" in str(exc.value.code)
    assert "11" not in str(exc.value.code).replace(TASK, "")
    captured = capsys.readouterr()
    assert "Cross-posted: Board 11 / Section 22" in captured.out
    assert "HTTP 403" in captured.err


def test_a_task_that_cannot_be_read_writes_nothing(monkeypatch, capsys):
    fake = FakeAsana(fail_reads=(1,))
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, fake, "--add-project", "11=22")
    assert "nothing cross-posted" in str(exc.value.code)
    assert fake.posts == []


def test_a_failed_read_back_prints_uncertain_not_success(monkeypatch, capsys):
    fake = FakeAsana(fail_reads=(2,))
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, fake, "--add-project", "11=22")
    assert "UNCERTAIN" in str(exc.value.code)
    assert "Cross-posted" not in capsys.readouterr().out
