"""update_task.py: custom-field parsing, incl. multi-enum fields (for example the escalation
board's Teams Involved), which Asana only accepts as a LIST of option gids."""
import json
import sys

import pytest

import update_task


def run_dry(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["update_task.py", "1234567890", *argv, "--dry-run"])
    update_task.main()
    return json.loads(capsys.readouterr().out)


def test_single_enum_stays_a_string(monkeypatch, capsys):
    out = run_dry(monkeypatch, capsys, "--custom-field", "111=222")
    assert out == {"data": {"custom_fields": {"111": "222"}}}


def test_date_field_is_wrapped(monkeypatch, capsys):
    out = run_dry(monkeypatch, capsys, "--custom-field", "111=2026-10-12")
    assert out["data"]["custom_fields"]["111"] == {"date": "2026-10-12"}


def test_multi_field_sends_a_list(monkeypatch, capsys):
    out = run_dry(monkeypatch, capsys, "--multi-field", "999=223,222")
    assert out == {"data": {"custom_fields": {"999": ["223", "222"]}}}


def test_multi_field_strips_spaces_and_drops_empties(monkeypatch, capsys):
    out = run_dry(monkeypatch, capsys, "--multi-field", "999= 223 , 222 ,")
    assert out["data"]["custom_fields"]["999"] == ["223", "222"]


def test_multi_and_single_fields_combine(monkeypatch, capsys):
    out = run_dry(monkeypatch, capsys, "--custom-field", "111=222", "--multi-field", "999=223,222")
    assert out["data"]["custom_fields"] == {"111": "222", "999": ["223", "222"]}


def test_multi_field_needs_at_least_one_option(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["update_task.py", "1", "--multi-field", "999=", "--dry-run"])
    with pytest.raises(SystemExit):
        update_task.main()
    assert "no option gids" in capsys.readouterr().err


def test_same_field_in_both_flags_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["update_task.py", "1", "--custom-field", "999=1",
                                      "--multi-field", "999=2,3", "--dry-run"])
    with pytest.raises(SystemExit):
        update_task.main()
    assert "both --custom-field and --multi-field" in capsys.readouterr().err


def test_unassign_sends_a_null_assignee(monkeypatch, capsys):
    out = run_dry(monkeypatch, capsys, "--unassign")
    assert out == {"data": {"assignee": None}}


def test_unassign_with_assignee_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["update_task.py", "1", "--assignee", "42", "--unassign", "--dry-run"])
    with pytest.raises(SystemExit):
        update_task.main()
    assert "--unassign" in capsys.readouterr().err


def test_unassign_combines_with_other_fields(monkeypatch, capsys):
    out = run_dry(monkeypatch, capsys, "--unassign", "--due", "2026-10-30")
    assert out == {"data": {"assignee": None, "due_on": "2026-10-30"}}


def test_unassign_with_an_empty_assignee_is_still_refused(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["update_task.py", "1", "--assignee", "", "--unassign", "--dry-run"])
    with pytest.raises(SystemExit):
        update_task.main()
    assert "--unassign" in capsys.readouterr().err


def test_status_option_sets_the_custom_type_status(monkeypatch, capsys):
    out = run_dry(monkeypatch, capsys, "--status-option", "1200000000000600")
    assert out == {"data": {"custom_type_status_option": "1200000000000600"}}


def test_status_option_combines_with_fields_and_assignee(monkeypatch, capsys):
    out = run_dry(monkeypatch, capsys, "--status-option", "55", "--custom-field", "111=222", "--assignee", "42")
    assert out["data"] == {"assignee": "42", "custom_fields": {"111": "222"}, "custom_type_status_option": "55"}


def test_status_option_must_be_a_gid(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["update_task.py", "1", "--status-option", "In Progress", "--dry-run"])
    with pytest.raises(SystemExit) as exc:
        update_task.main()
    assert exc.value.code == 2
    assert "bad --status-option" in capsys.readouterr().err
