"""Tests for scan_casualties.py. Runs the script as a subprocess against tmp_path fixtures."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scan_casualties.py"
SINCE = "2025-03-04T20:21:21Z"
SINCE_TXT = "since=2025-03-04T20:21:21Z"
ERR = "Failed to authenticate: OAuth session expired and could not be refreshed"


def run(tmp_path, *args, since=SINCE, account="acct"):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--home-root", str(tmp_path), "--since", since, *args, account],
        capture_output=True, text=True)


def summary(sessions, stopped, recovered, partial=0, unreadable=0, files=None):
    files = sessions if files is None else files
    return (f"SUMMARY {SINCE_TXT} sessions={sessions} files={files} stopped={stopped} recovered={recovered} "
            f"partial={partial} unreadable={unreadable}")


def user(text, ts="2025-03-04T21:00:00Z", **kw):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}, **kw}


def asst(text, ts="2025-03-04T21:01:00Z", **kw):
    return {"type": "assistant", "timestamp": ts,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}, **kw}


def err(ts="2025-03-04T21:01:00Z", text=ERR, **kw):
    """The real harness error entry shape."""
    kw.setdefault("isApiErrorMessage", True)
    kw.setdefault("error", "authentication_failed")
    return asst(text, ts=ts, **kw)


def write_session(tmp_path, name, entries, project="proj", raw_tail="", account="acct"):
    d = tmp_path / account / ".claude" / "projects" / project
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text("\n".join(json.dumps(e) for e in entries) + "\n" + raw_tail)
    return f


def test_stopped_with_ask(tmp_path):
    write_session(tmp_path, "s1.jsonl", [
        user("<system-reminder>ignore</system-reminder>", ts="2025-03-04T20:50:00Z"),
        user('Fix the "login"\n\tpage please', ts="2025-03-04T21:00:00Z"),
        asst("working on it", ts="2025-03-04T21:00:30Z"),
        err(ts="2025-03-04T21:01:00Z"),
    ])
    r = run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert ('STOPPED s1 project=proj first_error=2025-03-04T21:01:00Z '
            "last_entry=2025-03-04T21:01:00Z ask=\"Fix the 'login' page please\"") in r.stdout
    assert summary(1, 1, 0) in r.stdout


def test_recovered(tmp_path):
    write_session(tmp_path, "s2.jsonl", [
        user("do the thing"), err(ts="2025-03-04T21:01:00Z"),
        user("/login done", ts="2025-03-04T22:00:00Z"),
        asst("ok", ts="2025-03-04T22:05:00Z"),
    ])
    r = run(tmp_path)
    assert r.returncode == 0
    assert "RECOVERED s2 project=proj first_error=2025-03-04T21:01:00Z last_entry=2025-03-04T22:05:00Z" in r.stdout
    assert summary(1, 0, 1) in r.stdout


def test_phrase_in_tool_result_not_flagged(tmp_path):
    tr = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x", "content": ERR}]}}
    tu = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "x", "name": "Bash", "input": {"command": "echo " + ERR}}]}}
    write_session(tmp_path, "s3.jsonl", [user("hi"), tu, tr, asst("fine")])
    r = run(tmp_path)
    assert r.returncode == 0
    assert "STOPPED" not in r.stdout and "RECOVERED" not in r.stdout
    assert summary(1, 0, 0) in r.stdout


def test_phrase_in_user_entry_not_flagged(tmp_path):
    write_session(tmp_path, "s4.jsonl", [user("I saw: " + ERR, isApiErrorMessage=True), asst("ok")])
    r = run(tmp_path)
    assert r.returncode == 0 and "STOPPED" not in r.stdout
    assert summary(1, 0, 0) in r.stdout


def test_assistant_prose_quoting_phrase_not_flagged(tmp_path):
    write_session(tmp_path, "prose.jsonl", [user("what does it mean?"), asst("It says: " + ERR)])
    r = run(tmp_path)
    assert r.returncode == 0 and "STOPPED" not in r.stdout
    assert summary(1, 0, 0) in r.stdout


def test_flag_plus_error_code_with_other_wording_flagged(tmp_path):
    write_session(tmp_path, "code.jsonl", [user("go"), err(text="Please run /login")])
    r = run(tmp_path)
    assert r.returncode == 1
    assert "STOPPED code " in r.stdout


def test_flag_plus_phrase_without_error_code_flagged(tmp_path):
    e = err()
    del e["error"]
    write_session(tmp_path, "phrase.jsonl", [user("go"), e])
    assert "STOPPED phrase " in run(tmp_path).stdout


def test_flag_without_phrase_or_code_not_flagged(tmp_path):
    write_session(tmp_path, "other.jsonl", [user("go"), err(text="Rate limited", error="rate_limit")])
    r = run(tmp_path)
    assert r.returncode == 0 and "STOPPED" not in r.stdout
    assert summary(1, 0, 0) in r.stdout  # the fixture was judged, not skipped
    # positive control: same layout, real auth error, is flagged
    write_session(tmp_path, "real.jsonl", [user("go"), err()])
    r = run(tmp_path)
    assert r.returncode == 1 and "STOPPED real " in r.stdout and "STOPPED other " not in r.stdout
    assert summary(2, 1, 0) in r.stdout


def test_sidechain_error_ignored(tmp_path):
    write_session(tmp_path, "s5.jsonl", [user("hi"), asst("done"), err(isSidechain=True)])
    r = run(tmp_path)
    assert r.returncode == 0 and "STOPPED" not in r.stdout
    assert summary(1, 0, 0) in r.stdout
    write_session(tmp_path, "s6.jsonl", [user("hi"), err()])  # positive control
    r = run(tmp_path)
    assert r.returncode == 1 and "STOPPED s6 " in r.stdout and "s5" not in r.stdout.split("SUMMARY")[0]


def test_agent_file_ignored(tmp_path):
    write_session(tmp_path, "agent-abc.jsonl", [user("hi"), err()])
    r = run(tmp_path)
    assert r.returncode == 0
    assert summary(0, 0, 0) in r.stdout


def test_old_mtime_skipped_with_positive_control(tmp_path):
    old = write_session(tmp_path, "old.jsonl", [user("hi"), err()])
    write_session(tmp_path, "new.jsonl", [user("hi"), err()])
    os.utime(old, (1_700_000_000, 1_700_000_000))
    r = run(tmp_path)
    assert "STOPPED new " in r.stdout and "STOPPED old " not in r.stdout
    assert summary(1, 1, 0) in r.stdout


def test_bad_middle_line_unreadable(tmp_path):
    f = write_session(tmp_path, "bad.jsonl", [user("hi")])
    f.write_text(json.dumps(user("hi")) + "\n{broken\n" + json.dumps(err()) + "\n")
    r = run(tmp_path)
    assert r.returncode == 3
    assert f"UNREADABLE {f} bad_json_line=2" in r.stdout
    assert "STOPPED" not in r.stdout
    assert summary(1, 0, 0, unreadable=1) in r.stdout


def test_bad_last_line_is_partial_but_still_analysed(tmp_path):
    f = write_session(tmp_path, "tail.jsonl", [user("go"), err()], raw_tail='{"type": "assi')
    r = run(tmp_path)
    assert r.returncode == 3
    assert "STOPPED tail " in r.stdout
    assert f"PARTIAL {f} bad_last_line=3" in r.stdout
    assert summary(1, 1, 0, partial=1) in r.stdout


def test_only_line_bad_is_unreadable(tmp_path):
    f = write_session(tmp_path, "only.jsonl", [], raw_tail="{broken")
    r = run(tmp_path)
    assert r.returncode == 3
    assert f"UNREADABLE {f} bad_json_line=" in r.stdout
    assert "PARTIAL" not in r.stdout
    assert summary(1, 0, 0, unreadable=1) in r.stdout


def test_only_line_not_an_object_is_unreadable(tmp_path):
    f = write_session(tmp_path, "arr.jsonl", [], raw_tail="[1, 2]")
    r = run(tmp_path)
    assert r.returncode == 3 and f"UNREADABLE {f} bad_json_line=" in r.stdout


@pytest.mark.skipif(os.getuid() == 0, reason="root ignores directory permissions")
def test_unreadable_project_folder_does_not_abort_scan(tmp_path):
    write_session(tmp_path, "good.jsonl", [user("hi"), err()], project="p-good")
    bad = write_session(tmp_path, "hidden.jsonl", [user("hi"), err()], project="p-bad").parent
    os.chmod(bad, 0)
    try:
        r = run(tmp_path)
    finally:
        os.chmod(bad, 0o755)
    assert r.returncode == 3
    assert f"UNREADABLE {bad} PermissionError" in r.stdout
    assert "STOPPED good " in r.stdout
    assert summary(1, 1, 0, unreadable=1) in r.stdout


def test_invalid_since_exits_2(tmp_path):
    r = run(tmp_path, since="yesterday")
    assert r.returncode == 2
    assert "usage:" in r.stderr and "invalid time" in r.stderr


def test_since_formats_accepted(tmp_path):
    write_session(tmp_path, "s.jsonl", [user("hi"), err()])
    cases = {
        "2025-03-04T20:21:21+00:00": "2025-03-04T20:21:21Z",
        "2025-03-04 20:21": "2025-03-04T20:21:00Z",
        "2025-03-04 20:21:21": "2025-03-04T20:21:21Z",
        "2025-03-04T20:21:21Z": "2025-03-04T20:21:21Z",
    }
    for since, want in cases.items():
        r = run(tmp_path, since=since)
        assert r.returncode == 1, since
        assert f"since={want} " in r.stdout, since


def test_since_stat_form_parses_to_utc(tmp_path):
    write_session(tmp_path, "s.jsonl", [user("hi"), err()])
    r = run(tmp_path, since="2025-03-04 20:21:21.663934721 +0000")
    assert SINCE_TXT in r.stdout


def test_since_stat_form_offset_converts(tmp_path):
    write_session(tmp_path, "s.jsonl", [user("hi"), err()])
    assert SINCE_TXT in run(tmp_path, since="2025-03-04 21:21:21.5 +0100").stdout
    assert SINCE_TXT in run(tmp_path, since="2025-03-04 15:51:21 -0430").stdout


def test_since_iso_offset_converts(tmp_path):
    write_session(tmp_path, "s.jsonl", [user("hi"), err()])
    assert SINCE_TXT in run(tmp_path, since="2025-03-04T22:21:21+02:00").stdout


def test_bad_account_exits_2(tmp_path):
    for bad in ("../x", "a/b", ".."):
        r = run(tmp_path, account=bad)
        assert r.returncode == 2, bad
        assert "usage:" in r.stderr and "invalid account name" in r.stderr
        assert r.stdout == ""


def test_missing_projects_folder_exits_3(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 3
    assert r.stdout.startswith("UNREADABLE ")


def test_summary_counts_mixed(tmp_path):
    write_session(tmp_path, "a.jsonl", [user("q1"), err()], project="p1")
    write_session(tmp_path, "b.jsonl", [user("q2"), err()], project="p2")
    write_session(tmp_path, "c.jsonl", [user("q3"), err(), user("again"), asst("ok")])
    write_session(tmp_path, "d.jsonl", [user("q4"), asst("fine")])
    r = run(tmp_path)
    assert r.returncode == 1
    assert summary(4, 2, 1) in r.stdout


SID = "11111111-2222-3333-4444-555555555555"


def test_fragments_in_two_projects_recovered(tmp_path):
    write_session(tmp_path, SID + ".jsonl", [user("start the job"), err(ts="2025-03-04T21:01:00Z")],
                  project="proj-a")
    write_session(tmp_path, SID + ".jsonl", [user("/login done", ts="2025-03-04T22:00:00Z"),
                                             asst("continuing", ts="2025-03-04T22:01:00Z")],
                  project="proj-b")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith(("STOPPED", "RECOVERED"))]
    assert len(lines) == 1
    assert lines[0].startswith(f"RECOVERED {SID} project=proj-a,proj-b first_error=2025-03-04T21:01:00Z "
                               "last_entry=2025-03-04T22:01:00Z")
    assert summary(1, 0, 1, files=2) in r.stdout


def test_fragments_continuation_before_error_is_stopped(tmp_path):
    write_session(tmp_path, SID + ".jsonl", [user("start the job"), err(ts="2025-03-04T21:01:00Z")],
                  project="proj-a")
    write_session(tmp_path, SID + ".jsonl", [user("earlier work", ts="2025-03-04T20:30:00Z"),
                                             asst("earlier reply", ts="2025-03-04T20:31:00Z")],
                  project="proj-b")
    r = run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert f"STOPPED {SID} project=proj-a,proj-b " in r.stdout
    assert summary(1, 1, 0, files=2) in r.stdout


def test_group_included_when_only_continuation_is_fresh(tmp_path):
    old = write_session(tmp_path, SID + ".jsonl", [user("start"), err(ts="2025-03-04T21:01:00Z")],
                        project="proj-a")
    write_session(tmp_path, SID + ".jsonl", [user("back", ts="2025-03-04T22:00:00Z"),
                                             asst("ok", ts="2025-03-04T22:01:00Z")],
                  project="proj-b")
    os.utime(old, (1_700_000_000, 1_700_000_000))
    r = run(tmp_path)
    assert f"RECOVERED {SID} project=proj-a,proj-b " in r.stdout
    assert summary(1, 0, 1, files=2) in r.stdout


def test_group_skipped_when_all_fragments_old(tmp_path):
    for proj in ("proj-a", "proj-b"):
        f = write_session(tmp_path, SID + ".jsonl", [user("x"), err()], project=proj)
        os.utime(f, (1_700_000_000, 1_700_000_000))
    r = run(tmp_path)
    assert r.returncode == 0 and summary(0, 0, 0, files=0) in r.stdout


def test_unreadable_fragment_still_judges_from_readable_ones(tmp_path):
    write_session(tmp_path, SID + ".jsonl", [user("start"), err(ts="2025-03-04T21:01:00Z")],
                  project="proj-a")
    bad = write_session(tmp_path, SID + ".jsonl", [user("x")], project="proj-b")
    bad.write_text("{broken\n" + json.dumps(user("x")) + "\n")
    r = run(tmp_path)
    assert r.returncode == 3
    assert f"UNREADABLE {bad} bad_json_line=1" in r.stdout
    assert f"STOPPED {SID} project=proj-a " in r.stdout
    assert summary(1, 1, 0, unreadable=1, files=2) in r.stdout


# --- RECOVERED needs a real assistant continuation ---

def status_lines(r):
    return [ln for ln in r.stdout.splitlines() if ln.startswith(("STOPPED", "RECOVERED"))]


def test_error_then_only_user_message_is_stopped(tmp_path):
    write_session(tmp_path, "u1.jsonl", [user("start"), err(ts="2025-03-04T21:01:00Z"),
                                         user("hello?", ts="2025-03-04T21:05:00Z")])
    r = run(tmp_path)
    assert r.returncode == 1 and status_lines(r)[0].startswith("STOPPED u1 ")
    assert 'ask="start"' in r.stdout
    assert summary(1, 1, 0) in r.stdout


def test_error_then_task_notification_only_is_stopped(tmp_path):
    write_session(tmp_path, "u2.jsonl", [
        user("start"), err(ts="2025-03-04T21:01:00Z"),
        user("<task-notification>done</task-notification>", ts="2025-03-04T21:05:00Z")])
    r = run(tmp_path)
    assert r.returncode == 1 and status_lines(r)[0].startswith("STOPPED u2 ")


def test_error_user_then_assistant_reply_is_recovered(tmp_path):
    write_session(tmp_path, "u3.jsonl", [
        user("start"), err(ts="2025-03-04T21:01:00Z"),
        user("again", ts="2025-03-04T21:05:00Z"), asst("sure", ts="2025-03-04T21:06:00Z")])
    r = run(tmp_path)
    assert r.returncode == 0 and status_lines(r)[0].startswith("RECOVERED u3 ")
    assert summary(1, 0, 1) in r.stdout


def test_error_then_another_error_is_stopped(tmp_path):
    write_session(tmp_path, "u4.jsonl", [
        user("start"), err(ts="2025-03-04T21:01:00Z"),
        user("retry", ts="2025-03-04T21:02:00Z"), err(ts="2025-03-04T21:03:00Z")])
    r = run(tmp_path)
    assert r.returncode == 1 and status_lines(r)[0].startswith("STOPPED u4 ")
    assert 'ask="retry"' in r.stdout


# --- malformed relevant entries fail closed ---

def test_content_not_str_or_list_is_malformed(tmp_path):
    f = write_session(tmp_path, "m1.jsonl", [
        user("hi"), {"type": "assistant", "message": {"role": "assistant", "content": 42}}, err()])
    r = run(tmp_path)
    assert r.returncode == 3
    assert f"UNREADABLE {f} malformed_entry=2" in r.stdout
    assert "STOPPED" not in r.stdout
    assert summary(1, 0, 0, unreadable=1) in r.stdout


def test_message_not_dict_is_malformed(tmp_path):
    f = write_session(tmp_path, "m2.jsonl", [{"type": "user", "message": "oops"}])
    r = run(tmp_path)
    assert r.returncode == 3 and f"UNREADABLE {f} malformed_entry=1" in r.stdout


def test_api_error_without_code_or_text_is_malformed(tmp_path):
    e = err(text="")
    del e["error"]
    f = write_session(tmp_path, "m3.jsonl", [user("hi"), e])
    r = run(tmp_path)
    assert r.returncode == 3 and f"UNREADABLE {f} malformed_entry=2" in r.stdout


def test_system_entry_with_odd_fields_ignored(tmp_path):
    odd = {"type": "system", "message": 42, "content": None, "timestamp": 7, "isApiErrorMessage": True}
    write_session(tmp_path, "m4.jsonl", [user("hi"), odd, err()])
    r = run(tmp_path)
    assert r.returncode == 1 and "STOPPED m4 " in r.stdout
    assert summary(1, 1, 0) in r.stdout


# --- never print credentials or raw file text ---

def test_secret_in_ask_redacted(tmp_path):
    write_session(tmp_path, "c1.jsonl", [user("sk-" + "ant-oat01-FAKESECRET123abc please fix it"), err()])
    r = run(tmp_path)
    assert "STOPPED c1 " in r.stdout
    assert "FAKESECRET" not in r.stdout + r.stderr
    assert 'ask="[REDACTED] please fix it"' in r.stdout


def test_long_token_like_run_redacted(tmp_path):
    token = "A1b2" * 10  # 40 chars
    write_session(tmp_path, "c2.jsonl", [user(f"key is {token} ok"), err()])
    r = run(tmp_path)
    assert token not in r.stdout and 'ask="key is [REDACTED] ok"' in r.stdout
    short = "x" * 31
    write_session(tmp_path, "c3.jsonl", [user(f"short {short} ok"), err()])
    assert short in run(tmp_path).stdout  # 31 chars is below the threshold


def test_garbage_timestamp_prints_unknown_and_no_extra_lines(tmp_path):
    bad_ts = "2025-03-04T21:01:00Z\nINJECTED LINE sk-ant-LEAK"
    write_session(tmp_path, "c4.jsonl", [user("start", ts="2025-03-04T21:00:00Z"), err(ts=bad_ts)])
    r = run(tmp_path)
    assert "INJECTED" not in r.stdout and "LEAK" not in r.stdout
    assert "first_error=unknown" in r.stdout
    assert len(r.stdout.splitlines()) == 2  # session line + SUMMARY
    assert "STOPPED c4 " in r.stdout


def test_timestamp_printed_normalised_to_utc(tmp_path):
    write_session(tmp_path, "c5.jsonl", [user("start"), err(ts="2025-03-04T23:01:00+02:00")])
    assert "first_error=2025-03-04T21:01:00Z" in run(tmp_path).stdout


# --- round 2: recovery evidence, block shapes, discriminator, harness tags ---

def test_flagged_rate_limit_after_error_is_not_recovery(tmp_path):
    write_session(tmp_path, "r1.jsonl", [
        user("start"), err(ts="2025-03-04T21:01:00Z"),
        user("retry", ts="2025-03-04T21:02:00Z"),
        err(ts="2025-03-04T21:03:00Z", text="Rate limited", error="rate_limit")])
    r = run(tmp_path)
    assert r.returncode == 1 and status_lines(r)[0].startswith("STOPPED r1 ")
    assert summary(1, 1, 0) in r.stdout


def test_bad_content_blocks_are_malformed(tmp_path):
    for i, content in enumerate(([42], [{"type": "text", "text": 42}], [{"text": "no type"}])):
        f = write_session(tmp_path, f"b{i}.jsonl", [
            user("hi"), {"type": "assistant", "message": {"role": "assistant", "content": content}}])
        r = run(tmp_path)
        assert f"UNREADABLE {f} malformed_entry=2" in r.stdout, content
        assert r.returncode == 3
        f.unlink()


def test_tool_use_and_tool_result_exchange_stays_valid(tmp_path):
    tu = {"type": "assistant", "timestamp": "2025-03-04T21:00:10Z", "message": {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "hm"},
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}}
    tr = {"type": "user", "timestamp": "2025-03-04T21:00:20Z", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "a b"},
        {"type": "image", "source": {}}]}}
    write_session(tmp_path, "v1.jsonl", [user("go"), tu, tr, err(ts="2025-03-04T21:01:00Z")])
    r = run(tmp_path)
    assert r.returncode == 1 and "STOPPED v1 " in r.stdout and 'ask="go"' in r.stdout
    assert summary(1, 1, 0) in r.stdout


def test_missing_or_numeric_type_is_malformed(tmp_path):
    f = write_session(tmp_path, "t1.jsonl", [user("hi"), {"message": {"content": "x"}}])
    r = run(tmp_path)
    assert r.returncode == 3 and f"UNREADABLE {f} malformed_entry=2" in r.stdout
    f.unlink()
    f = write_session(tmp_path, "t2.jsonl", [user("hi"), {"type": 7}])
    r = run(tmp_path)
    assert r.returncode == 3 and f"UNREADABLE {f} malformed_entry=2" in r.stdout


def test_ask_keeps_plain_markup_and_skips_harness_tags(tmp_path):
    write_session(tmp_path, "h1.jsonl", [user("<div>please fix</div>"), err()])
    r = run(tmp_path)
    assert 'ask="<div>please fix</div>"' in r.stdout
    write_session(tmp_path, "h2.jsonl", [
        user("real request"), user("<task-notification>x</task-notification>"),
        user("<system-reminder>y</system-reminder>"), user("<command-name>/foo</command-name>"), err()])
    r = run(tmp_path)
    assert [ln for ln in r.stdout.splitlines() if ln.startswith("STOPPED h2")][0].endswith('ask="real request"')
    write_session(tmp_path, "h3.jsonl", [user("<task>do it</task>"), err()])
    assert 'ask="<task>do it</task>"' in run(tmp_path).stdout
