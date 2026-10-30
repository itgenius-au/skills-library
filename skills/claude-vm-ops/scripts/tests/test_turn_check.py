"""Tests for turn_check.py. They use fixture folders and a fake /proc tree: no VM, no login.

Most tests pair a case that must read IDLE or UNKNOWN with the same fixture changed so that it
must read BUSY (or the other way round): a check that can only say IDLE proves nothing.
"""
import importlib.util
import json
import os
import pwd
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "turn_check.py"
SID = "0a1b2c3d-1111-2222-3333-444455556666"
SID2 = "9f8e7d6c-aaaa-bbbb-cccc-ddddeeeeffff"
SECRET = "sk-" + "ant-oat01-FAKEVALUE123"  # split so no secret scanner mistakes the fixture for a key

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
not_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")


def load():
    spec = importlib.util.spec_from_file_location("turn_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tc = load()


def user(text="please do the thing", **kw):
    return {"type": "user", "message": {"role": "user", "content": text}, **kw}


def asst(stop="end_turn", text="done", **kw):
    return {"type": "assistant", "message": {"role": "assistant", "stop_reason": stop,
                                             "content": [{"type": "text", "text": text}]}, **kw}


class Box:
    """A fake home root and a fake /proc under tmp_path."""

    def __init__(self, tmp_path):
        self.home = tmp_path / "home"
        self.proc = tmp_path / "proc"
        self.proc.mkdir()
        self.root = self.home / "acct" / ".claude" / "projects"

    def transcript(self, name, entries, project="-work", raw_tail="", age_min=1, sub=""):
        d = self.root / project / sub if sub else self.root / project
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n" + raw_tail)
        t = time.time() - age_min * 60
        os.utime(f, (t, t))
        return f

    def process(self, pid, cmdline="", fd_links=()):
        d = self.proc / str(pid)
        (d / "fd").mkdir(parents=True)
        (d / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode())
        for i, target in enumerate(fd_links):
            os.symlink(target, d / "fd" / str(i))

    def check(self, uid=None, window=20):
        return tc.check_account("acct", str(self.home), str(self.proc),
                                os.getuid() if uid is None else uid, window, time.time())


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


def verdict(box, **kw):
    return box.check(**kw)[0]


# ---------- the basic rule ----------

def test_recent_finished_turn_is_idle(box):
    box.transcript(SID + ".jsonl", [user(), asst("end_turn")])
    v, checked, detail, lines = box.check()
    assert (v, checked, detail, lines) == ("IDLE", 1, ["ok"], [])


def test_stop_sequence_also_counts_as_finished(box):
    box.transcript(SID + ".jsonl", [user(), asst("stop_sequence")])
    assert verdict(box) == "IDLE"


@pytest.mark.parametrize("entries", [
    [user()],                                   # the user spoke last
    [user(), asst("tool_use")],                 # a tool call is running
    [user(), asst(None)],                       # a streamed, unfinished reply
    [user(), asst("max_tokens")],               # anything else is not a finished turn
    [user(), {"type": "assistant", "message": "not a dict"}],
], ids=["user-last", "tool_use", "no-stop-reason", "max_tokens", "malformed-message"])
def test_positive_control_unfinished_turn_is_busy(box, entries):
    # Same fixture as the idle test with only the last entry changed.
    box.transcript(SID + ".jsonl", entries)
    v, checked, detail, lines = box.check()
    assert v == "BUSY" and checked == 1
    assert len(lines) == 1 and f"session={SID}" in lines[0] and "(recent)" in lines[0]


def test_only_the_last_user_or_assistant_entry_counts(box):
    box.transcript(SID + ".jsonl", [
        user(), asst("tool_use"), user("tool result"), asst("end_turn"),
        {"type": "system", "subtype": "daemon-respawn"}, {"type": "summary", "summary": "x"},
        {"type": "file-history-snapshot"},
    ])
    assert verdict(box) == "IDLE"
    box.transcript(SID2 + ".jsonl", [user(), asst("end_turn"), user("one more thing")])
    assert verdict(box) == "BUSY"


def test_output_line_shows_no_transcript_text(box):
    box.transcript(SID + ".jsonl", [user("use key " + SECRET), asst("tool_use", text=SECRET)])
    v, _, detail, lines = box.check()
    assert v == "BUSY"
    assert SECRET not in "".join(lines) + "".join(detail)
    assert "last=assistant/tool_use" in lines[0]


# ---------- the time window and live processes ----------

def test_window_boundary(box):
    box.transcript(SID + ".jsonl", [user()], age_min=19)
    assert verdict(box) == "BUSY"
    box.transcript(SID + ".jsonl", [user()], age_min=21)  # same file, now outside the window
    assert verdict(box) == "IDLE"
    assert verdict(box, window=30) == "BUSY"  # control: a wider window sees it again


def test_old_unfinished_transcript_with_no_live_process_is_a_dead_session(box):
    f = box.transcript(SID + ".jsonl", [user(), asst("tool_use")], age_min=300)
    v, checked, _, _ = box.check()
    assert (v, checked) == ("IDLE", 0)
    f.write_text("not json at all\n")  # a dead old file is not even read
    os.utime(f, (time.time() - 18000,) * 2)
    assert verdict(box) == "IDLE"


def test_old_transcript_referenced_in_a_live_cmdline_is_checked(box):
    box.transcript(SID + ".jsonl", [user(), asst("tool_use")], age_min=300)
    box.process(4242, cmdline=f"claude --resume {SID}")
    v, checked, _, lines = box.check()
    assert (v, checked) == ("BUSY", 1)
    assert "(old, live process)" in lines[0]


def test_old_transcript_referenced_by_an_open_fd_is_checked(box):
    box.transcript(SID + ".jsonl", [user(), asst("tool_use")], age_min=300)
    box.process(4243, cmdline="node build.js",
                fd_links=[f"/tmp/claude-1001/-work/{SID}/tasks", "/dev/null"])
    assert verdict(box) == "BUSY"


def test_old_finished_transcript_that_a_process_references_is_idle(box):
    box.transcript(SID + ".jsonl", [user(), asst("end_turn")], age_min=300)
    box.process(4244, cmdline=f"claude --resume {SID}")
    v, checked, _, _ = box.check()
    assert (v, checked) == ("IDLE", 1)


def test_a_reference_to_another_session_id_does_not_count(box):
    box.transcript(SID + ".jsonl", [user(), asst("tool_use")], age_min=300)
    box.process(4245, cmdline=f"claude --resume {SID2}")
    assert verdict(box) == "IDLE"


def test_only_processes_of_the_account_count(box):
    box.transcript(SID + ".jsonl", [user(), asst("tool_use")], age_min=300)
    box.process(4246, cmdline=f"claude --resume {SID}")
    assert verdict(box, uid=os.getuid()) == "BUSY"        # control: the account's own process
    assert verdict(box, uid=os.getuid() + 1) == "IDLE"    # another account's process


# ---------- what it must skip ----------

def test_subagent_transcripts_and_sidechain_entries_are_skipped(box):
    box.transcript(SID + ".jsonl", [
        user(), asst("end_turn"),
        user("sub task", isSidechain=True), asst("tool_use", isSidechain=True),
    ])
    box.transcript("agent-a1b2c3.jsonl", [user(), asst("tool_use")])
    box.transcript("agent-zzz.jsonl", [user()], sub=f"{SID}/subagents")
    box.transcript("sub-1.jsonl", [user(), asst("tool_use")], sub=f"{SID}/subagents")
    v, checked, _, _ = box.check()
    assert (v, checked) == ("IDLE", 1)


def test_positive_control_the_skipped_content_would_otherwise_be_busy(box):
    # The same unfinished content in a MAIN transcript is BUSY: the skip rules are what made
    # the previous test read IDLE.
    box.transcript(SID2 + ".jsonl", [user(), asst("tool_use")])
    assert verdict(box) == "BUSY"


def test_a_sidechain_flag_that_is_not_exactly_true_does_not_hide_an_entry(box):
    box.transcript(SID + ".jsonl", [user(), asst("end_turn"), user("later", isSidechain="yes")])
    assert verdict(box) == "BUSY"


# ---------- fail closed ----------

def test_missing_projects_folder_is_unknown(box):
    v, checked, detail, _ = box.check()
    assert (v, checked, detail) == ("UNKNOWN", 0, ["projects_folder_missing"])


def test_projects_path_that_is_a_file_is_unknown(box):
    box.root.parent.mkdir(parents=True)
    box.root.write_text("x")
    assert box.check()[2] == ["projects_folder_missing"]


@not_root
def test_unreadable_projects_folder_is_unknown(box):
    box.transcript(SID + ".jsonl", [user(), asst("end_turn")])
    assert verdict(box) == "IDLE"  # control
    box.root.chmod(0)
    try:
        v, _, detail, _ = box.check()
    finally:
        box.root.chmod(0o755)
    assert v == "UNKNOWN" and detail[0] in ("folder_unreadable", "projects_folder_unreadable")


@not_root
def test_unreadable_project_subfolder_is_unknown_not_idle(box):
    box.transcript(SID + ".jsonl", [user(), asst("end_turn")], project="-ok")
    box.transcript(SID2 + ".jsonl", [user()], project="-locked")
    (box.root / "-locked").chmod(0)
    try:
        v, _, detail, _ = box.check()
    finally:
        (box.root / "-locked").chmod(0o755)
    assert v == "UNKNOWN" and "folder_unreadable" in detail


@not_root
def test_unreadable_transcript_is_unknown(box):
    f = box.transcript(SID + ".jsonl", [user(), asst("end_turn")])
    f.chmod(0)
    try:
        v, _, detail, _ = box.check()
    finally:
        f.chmod(0o644)
    assert v == "UNKNOWN" and detail == ["file_unreadable"]


def test_half_written_line_is_unknown_and_the_control_without_it_is_idle(box):
    f = box.transcript(SID + ".jsonl", [user(), asst("end_turn")], raw_tail='{"type": "user", "mess')
    v, _, detail, lines = box.check()
    assert (v, detail, lines) == ("UNKNOWN", ["unparseable_line"], [])
    f.write_text(json.dumps(user()) + "\n" + json.dumps(asst("end_turn")) + "\n")
    assert verdict(box) == "IDLE"


def test_a_line_that_is_not_a_json_object_is_unknown(box):
    box.transcript(SID + ".jsonl", [user(), asst("end_turn")], raw_tail="[1, 2]\n")
    assert box.check()[2] == ["unparseable_line"]


def test_a_bad_line_in_the_middle_is_unknown(box):
    f = box.transcript(SID + ".jsonl", [user()])
    f.write_text(json.dumps(user()) + "\nnot json\n" + json.dumps(asst("end_turn")) + "\n")
    assert box.check()[0] == "UNKNOWN"


def test_file_with_no_user_or_assistant_entry_is_unknown(box):
    box.transcript(SID + ".jsonl", [{"type": "system"}, {"type": "summary", "summary": "x"}])
    assert box.check()[2] == ["no_user_or_assistant_entry"]
    box.transcript(SID + ".jsonl", [{"type": "system"}, user(), asst("end_turn")])  # control
    assert verdict(box) == "IDLE"


def test_empty_file_is_unknown(box):
    f = box.transcript(SID + ".jsonl", [])
    f.write_text("")
    assert box.check()[2] == ["no_user_or_assistant_entry"]


def test_busy_wins_over_unknown_in_the_same_account(box):
    box.transcript(SID + ".jsonl", [user()])
    box.transcript(SID2 + ".jsonl", [user(), asst("end_turn")], raw_tail="{half")
    v, _, detail, lines = box.check()
    assert v == "BUSY" and "unparseable_line" in detail and len(lines) == 1


def test_process_table_unreadable_is_unknown_and_the_control_is_idle(box):
    box.transcript(SID + ".jsonl", [user(), asst("end_turn")])
    assert verdict(box) == "IDLE"
    box.proc.rmdir()
    v, _, detail, _ = box.check()
    assert (v, detail) == ("UNKNOWN", ["process_table_unreadable"])


def test_partial_proc_read_is_unknown(box, monkeypatch):
    box.transcript(SID + ".jsonl", [user(), asst("end_turn")])
    box.process(100, cmdline="sleep 1", fd_links=["/dev/null"])
    assert verdict(box) == "IDLE"  # control: the same tree, nothing failing

    def denied(_path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(tc.os, "readlink", denied)
    v, _, detail, _ = box.check()
    assert (v, detail) == ("UNKNOWN", ["process_inspection_incomplete"])


@not_root
def test_unreadable_fd_folder_is_unknown(box):
    box.transcript(SID + ".jsonl", [user(), asst("end_turn")])
    box.process(101, cmdline="sleep 1")
    (box.proc / "101" / "fd").chmod(0)
    try:
        v, _, detail, _ = box.check()
    finally:
        (box.proc / "101" / "fd").chmod(0o755)
    assert (v, detail) == ("UNKNOWN", ["process_inspection_incomplete"])


def test_a_process_that_vanished_is_not_a_problem(box):
    box.transcript(SID + ".jsonl", [user(), asst("end_turn")])
    (box.proc / "102").mkdir()  # no cmdline file: the process exited while we looked
    box.process(103, cmdline="sleep 1")
    (box.proc / "103" / "fd").rmdir()  # no fd folder either
    assert box.check()[:3] == ("IDLE", 1, ["ok"])


def test_fifo_named_like_a_transcript_does_not_hang_and_is_unknown(box):
    d = box.root / "-work"
    d.mkdir(parents=True)
    os.mkfifo(d / (SID + ".jsonl"))
    result = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util,os,sys,time;"
         f"s=importlib.util.spec_from_file_location('t',{str(SCRIPT)!r});m=importlib.util.module_from_spec(s);"
         "s.loader.exec_module(m);"
         f"print(m.check_account('acct',{str(box.home)!r},{str(box.proc)!r},os.getuid(),20,time.time()))"],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and "UNKNOWN" in result.stdout and "file_not_regular" in result.stdout


def test_symlinked_transcript_is_unknown_not_followed(box, tmp_path):
    target = tmp_path / "elsewhere.jsonl"
    target.write_text(json.dumps(user()) + "\n" + json.dumps(asst("end_turn")) + "\n")
    d = box.root / "-work"
    d.mkdir(parents=True)
    os.symlink(target, d / (SID + ".jsonl"))
    # lstat of the link is new, so it must be checked; opening it without following fails closed.
    assert box.check()[0:3] == ("UNKNOWN", 1, ["file_unreadable"])


def test_tail_read_tolerates_a_cut_first_line_but_not_a_bad_one(box):
    big = "x" * (tc.TAIL + 1000)
    box.transcript(SID + ".jsonl", [user(big), asst("end_turn")])  # first line is cut by the tail read
    v, checked, detail, _ = box.check()
    assert (v, detail) == ("IDLE", ["ok"])
    # Control: the same bad first line in a file small enough to be read whole is a defect.
    f = box.transcript(SID2 + ".jsonl", [asst("end_turn")])
    f.write_text("this line is cut\n" + json.dumps(asst("end_turn")) + "\n")
    assert verdict(box) == "UNKNOWN"


def test_huge_last_entry_that_fills_the_tail_is_unknown(box):
    box.transcript(SID + ".jsonl", [user(), asst("end_turn", text="y" * (tc.TAIL + 10))])
    assert box.check()[2] == ["no_user_or_assistant_entry"]


# ---------- names, output and exit codes (through the command line) ----------

def me():
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        pytest.skip("the test user has no passwd entry")


def run(box, *accounts, extra=()):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--home-root", str(box.home), "--proc-root", str(box.proc),
         *extra, *accounts],
        capture_output=True, text=True, timeout=60)


def box_for(tmp_path, account):
    b = Box(tmp_path)
    b.root = b.home / account / ".claude" / "projects"
    return b


def test_cli_idle_busy_unknown_lines_summary_and_exit_codes(tmp_path):
    me_ = me()
    b = box_for(tmp_path, me_)
    b.transcript(SID + ".jsonl", [user(), asst("end_turn")])
    r = run(b, me_)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[0] == f"{me_} IDLE checked=1 detail=ok"
    assert r.stdout.splitlines()[-1] == "SUMMARY idle=1 busy=0 unknown=0"

    b.transcript(SID2 + ".jsonl", [user()])
    r = run(b, me_)
    assert r.returncode == 1
    assert f"{me_} BUSY checked=2" in r.stdout and "SUMMARY idle=0 busy=1 unknown=0" in r.stdout

    r = run(b, me_, "no-such-account-zz")
    assert r.returncode == 3  # an UNKNOWN account outranks a BUSY one
    assert "no-such-account-zz UNKNOWN checked=0 detail=no_such_account" in r.stdout
    assert "SUMMARY idle=0 busy=1 unknown=1" in r.stdout


def test_cli_missing_projects_folder_is_unknown_and_exit_3(tmp_path):
    me_ = me()
    b = Box(tmp_path)
    r = run(b, me_)
    assert r.returncode == 3
    assert f"{me_} UNKNOWN checked=0 detail=projects_folder_missing" in r.stdout


def test_cli_odd_file_names_cannot_forge_a_verdict_line(tmp_path):
    me_ = me()
    b = box_for(tmp_path, me_)
    forged = f"x\n{me_} IDLE checked=9 detail=ok\nSUMMARY idle=1 busy=0 unknown=0\n.jsonl"
    b.transcript(forged, [user()])
    b.transcript(SID + ".jsonl", [user()], project="-proj\nSUMMARY idle=9")
    r = run(b, me_)
    assert r.returncode == 1
    lines = r.stdout.splitlines()
    assert lines[0].startswith(f"{me_} BUSY checked=2")
    assert [ln for ln in lines if not ln.startswith("  ")] == [lines[0], "SUMMARY idle=0 busy=1 unknown=0"]
    assert r.stdout.count("<odd-name>") == 2


def test_cli_writes_nothing(tmp_path):
    me_ = me()
    b = box_for(tmp_path, me_)
    b.transcript(SID + ".jsonl", [user(), asst("tool_use")])
    before = sorted((str(p), p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    run(b, me_)
    assert sorted((str(p), p.stat().st_mtime_ns) for p in tmp_path.rglob("*")) == before


def test_cli_bad_arguments_exit_2(tmp_path):
    b = Box(tmp_path)
    for bad in ("../x", "a/b", "..", ".", ""):
        r = run(b, bad)
        assert r.returncode == 2, bad
        assert "usage:" in r.stderr and "invalid account name" in r.stderr
        assert r.stdout == ""
    r = run(b)  # no account at all
    assert r.returncode == 2 and "usage:" in r.stderr
    r = run(b, "acct", extra=["--window-min", "0"])
    assert r.returncode == 2 and "must be >= 1" in r.stderr


def test_cli_help_prints_usage_and_exits_0(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "usage:" in r.stdout and "SUMMARY" not in r.stdout
