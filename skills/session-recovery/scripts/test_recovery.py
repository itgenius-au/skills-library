import json
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recovery as R  # noqa: E402


@pytest.fixture(autouse=True)
def iso(tmp_path, monkeypatch):
    """Point every state path at tmp, so no test touches the real ~/.claude."""
    cfgdir = tmp_path / "dotclaude"
    cfgdir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgdir))
    return cfgdir


SESS = {"id": "session_ABC", "title": "T", "session_status": "SESSION_STATUS_RUNNING",
        "connection_status": "disconnected", "updated_at": "2025-03-04T12:00:00Z",
        "created_at": "2025-03-03T00:00:00Z", "origin": "web"}


def test_load_both_page_forms(tmp_path):
    page = {"data": [SESS], "has_more": False}
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps(page))
    raw = tmp_path / "raw.txt"
    raw.write_text('<other-session id="x">\n' + json.dumps({"ccr": page}) + "\n</other-session>")
    assert R.load_page(str(bare)) == [SESS]
    assert R.load_page(str(raw)) == [SESS]
    assert len(R.load_pages([str(bare), str(raw)])) == 1  # dedup by id


def test_suffix_join_and_filters(tmp_path):
    d = tmp_path / "jobs" / "j1"
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({
        "bridgeSessionId": "cse_ABC", "sessionId": "uuid-1", "daemonShort": "deadbeef",
        "state": "idle", "cwd": "/w"}))
    jobs = R.load_jobs(str(tmp_path / "jobs" / "*" / "state.json"))
    archived = dict(SESS, id="session_ZZZ", session_status="SESSION_STATUS_ARCHIVED")
    connected = dict(SESS, id="session_YYY", connection_status="connected")
    nojob = dict(SESS, id="session_NOJOB")
    rows = R.build_rows([SESS, archived, connected, nojob], jobs)
    assert [r["remote"] for r in rows] == ["session_ABC", "session_NOJOB"]
    assert rows[0]["short"] == "deadbeef" and rows[0]["local"] == "uuid-1"
    assert rows[1]["short"] is None


def _write_job(cfgdir, folder, **state):
    d = cfgdir / "jobs" / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps(state))


def test_rows_from_jobs_skips_live_and_incomplete_jobs_and_sorts_newest_first():
    jobs = [
        {"sessionId": "u-old", "daemonShort": "00000001", "name": "old one", "state": "done",
         "updatedAt": "2025-03-01T10:00:00.000Z", "cwd": "/w/a", "bridgeSessionId": "cse_OLD"},
        {"sessionId": "u-new", "daemonShort": "00000002", "name": "new one", "state": "blocked",
         "updatedAt": "2025-03-04T10:00:00.000Z", "cwd": "/w/b"},
        {"sessionId": "u-live", "daemonShort": "00000003", "name": "live", "updatedAt": "2025-03-05T10:00:00.000Z"},
        {"sessionId": "u-noshort", "name": "no short id"},
        {"daemonShort": "00000005", "name": "no session id"},
    ]
    rows = R.rows_from_jobs(jobs, lambda u: u == "u-live")
    assert [r["short"] for r in rows] == ["00000002", "00000001"]
    assert rows[0]["remote"] is None and rows[1]["remote"] == "session_OLD"
    assert rows[0]["updated_at"] is None and rows[0]["title"] == "new one"
    assert rows[0]["cwd"] == "/w/b" and rows[0]["local"] == "u-new" and rows[0]["state"] == "blocked"


def test_read_job_files_ignores_bad_files(iso):
    _write_job(iso, "j1", sessionId="u1", daemonShort="aaaaaaaa")
    (iso / "jobs" / "j2").mkdir()
    (iso / "jobs" / "j2" / "state.json").write_text("{not json")
    (iso / "jobs" / "j3").mkdir()
    (iso / "jobs" / "j3" / "state.json").write_text("[1, 2]")
    got = R.read_job_files(str(iso / "jobs" / "*" / "state.json"))
    assert [g["sessionId"] for g in got] == ["u1"]


def test_inventory_local_only_mode(iso, tmp_path, capsys):
    _write_job(iso, "j1", sessionId="u-1", daemonShort="deadbeef", name="Fix the build", state="done",
               updatedAt="2025-03-04T10:00:00.000Z", cwd=str(tmp_path))
    _write_job(iso, "j2", sessionId="u-2", daemonShort="cafebabe", name="Still running", state="done")
    (iso / "sessions").mkdir()
    (iso / "sessions" / "1.json").write_text(json.dumps({"sessionId": "u-2", "pid": os.getpid()}))
    work = tmp_path / "w"
    assert R.main(["--work", str(work), "inventory"]) == 0
    out = capsys.readouterr().out
    assert "deadbeef" in out and "Fix the build" in out and "cafebabe" not in out
    assert "no live process (local jobs only): 1" in out
    inv = json.load(open(work / "inventory.json"))
    assert [r["short"] for r in inv] == ["deadbeef"]


def test_inventory_with_session_pages_keeps_only_disconnected_rows(iso, tmp_path, capsys):
    _write_job(iso, "j1", bridgeSessionId="cse_ABC", sessionId="u1", daemonShort="deadbeef", state="idle")
    page = tmp_path / "page.json"
    page.write_text(json.dumps({"data": [SESS, dict(SESS, id="session_OK", connection_status="connected")]}))
    assert R.main(["--work", str(tmp_path / "w"), "inventory", "--sessions", str(page)]) == 0
    inv = json.load(open(tmp_path / "w" / "inventory.json"))
    assert [r["remote"] for r in inv] == ["session_ABC"] and inv[0]["short"] == "deadbeef"
    assert "disconnected: 1 | mapped to VM job: 1" in capsys.readouterr().out


def test_work_dir_defaults_under_the_claude_config_dir(iso, tmp_path, capsys):
    assert R.default_work() == str(iso / "session-recovery")
    assert R.main(["inventory"]) == 0
    assert (iso / "session-recovery" / "inventory.json").exists()


@pytest.mark.parametrize("gap,flag", [(28800, "ok"), (29101, "CHECK"), (29100, "ok"), (None, "CHECK")])
def test_gap_flag(gap, flag):
    assert R.gap_flag(gap) == flag


def test_gap_seconds():
    assert R.gap_seconds("2025-03-04T08:00:00Z", "2025-03-04T00:00:00.500Z") == 28799.5
    assert R.gap_seconds(None, "2025-03-04T00:00:00Z") is None


TPL = "{MARK}. A B{DUPES}C"


def test_fill_prompt():
    assert R.fill_prompt(TPL, None) == "RECOVERY REVIEW v1. A BC"
    assert R.fill_prompt(TPL, "grp") == "RECOVERY REVIEW v1. A B\nDuplicate group: grp\nC"
    assert R.fill_prompt(TPL, None, "MY MARK") == "MY MARK. A BC"


def _a(text=None, tool=None):
    c = []
    if text:
        c.append({"type": "text", "text": text})
    if tool:
        c.append({"type": "tool_use", "name": tool, "input": {"x": "y" * 300}})
    return {"type": "assistant", "message": {"content": c}}


def _u(text):
    return {"type": "user", "message": {"content": text}}


def test_review_reply_uses_last_marker_turn():
    es = [_u("RECOVERY REVIEW v1 first"), _a("old reply"), _u("RECOVERY REVIEW v1 second"),
          _a(tool="Bash"), _a("new reply")]
    text, tools, err = R.review_reply(es)
    assert text == "new reply" and err == ""
    assert len(tools) == 1 and tools[0].startswith("Bash: ") and len(tools[0]) <= len("Bash: ") + 160
    assert R.review_reply([_a("x")])[2] == "prompt not in transcript yet"


def test_marker_reply_kinds():
    es = [_u("M one"), _a("old"), {"type": "queue-operation", "content": "M two"}, _a("new"), _a(tool="T")]
    hits, texts, tools = R.marker_reply(es, "M ")
    assert hits == 2 and texts == ["new"] and tools == 1
    assert R.marker_reply(es, "nope") == (0, [], 0)


def test_parse_result_block():
    t = "x\n```\nignore: 1\n```\ntext\n```\nREVIEW RESULT: needs-work\n```\n"
    assert R.parse_result_block(t) == {"review_result": "needs-work"}
    assert R.parse_result_block("none") == {"review_result": None}


def _setup_inventory(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    cwd = tmp_path / "some-cwd"
    cwd.mkdir()
    (work / "inventory.json").write_text(json.dumps([{
        "remote": "session_ABC", "title": "T", "short": "deadbeef", "local": "uuid-1",
        "cwd": str(cwd), "updated_at": None},
        {"remote": "session_DEF", "title": "Gone", "short": "0badc0de", "local": "uuid-2",
         "cwd": str(tmp_path / "removed-worktree"), "updated_at": None}]))
    tpl = tmp_path / "tpl.md"
    tpl.write_text(TPL)
    monkeypatch.setattr(R, "TEMPLATE", str(tpl))
    return str(work)


def test_resume_refuses_live(tmp_path, monkeypatch, capsys):
    work = _setup_inventory(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "live_pid", lambda u: 4242)

    def boom(*a, **k):
        raise AssertionError("subprocess must not run")
    monkeypatch.setattr(subprocess, "run", boom)
    assert R.main(["--work", work, "resume", "deadbeef"]) == 0
    assert "SKIP live process" in capsys.readouterr().out


def test_resume_builds_exact_command(tmp_path, monkeypatch, capsys):
    work = _setup_inventory(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "live_pid", lambda u: None)
    calls = []

    def fake(args, **kw):
        calls.append((args, kw))
        return subprocess.CompletedProcess(args, 0, stdout="Workspace not trusted", stderr="")
    monkeypatch.setattr(subprocess, "run", fake)
    R.main(["--work", work, "resume", "deadbeef"])
    args, kw = calls[0]
    assert args == ["claude", "--bg", "--resume", "uuid-1", "RECOVERY REVIEW v1. A BC"]
    assert kw["cwd"].endswith("some-cwd") and kw["stdin"] == subprocess.DEVNULL
    assert "TRUST" in capsys.readouterr().out
    R.main(["--work", work, "resume", "--nudge", "deadbeef"])
    assert calls[1][0][4] == R.NUDGE


def test_default_cwd_flag_is_used_when_job_has_none(tmp_path, monkeypatch):
    work = _setup_inventory(tmp_path, monkeypatch)
    inv = json.load(open(os.path.join(work, "inventory.json")))
    inv[0]["cwd"] = None
    json.dump(inv, open(os.path.join(work, "inventory.json"), "w"))
    fallback = tmp_path / "fallback-cwd"
    fallback.mkdir()
    monkeypatch.setattr(R, "live_pid", lambda u: None)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: calls.append(kw) or
                        subprocess.CompletedProcess(args, 1, stdout="x", stderr=""))
    R.main(["--work", work, "resume", "--default-cwd", str(fallback), "deadbeef"])
    assert calls[0]["cwd"] == str(fallback)
    calls.clear()
    R.main(["--work", work, "resume", "deadbeef"])  # default is the home folder
    assert calls[0]["cwd"] == str(tmp_path)  # HOME is the tmp folder in these tests, and "~" is expanded


def test_bundled_template_has_the_marker_placeholder_and_no_write_path():
    text = open(R.TEMPLATE).read()
    assert text.startswith("{MARK}.") and "{DUPES}" in text
    assert R.fill_prompt(text, None).startswith(R.DEFAULT_MARK + ".")
    assert "REVIEW RESULT: done | needs-work | duplicate" in text
    assert "Read-only" in text


def test_review_reply_honours_a_custom_marker():
    es = [_u("MY MARK go"), _a("reply")]
    assert R.review_reply(es, "MY MARK")[0] == "reply"
    assert R.review_reply(es)[2] == "prompt not in transcript yet"


# ---------- resume does not pin, and says so ----------

def test_resume_prints_the_pin_hint_after_a_good_wake_and_runs_nothing_else(tmp_path, monkeypatch, capsys):
    work = _setup_inventory(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "live_pid", lambda u: None)
    calls = []

    def fake(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="note: woke session deadbeef", stderr="")
    monkeypatch.setattr(subprocess, "run", fake)
    assert R.main(["--work", work, "resume", "deadbeef"]) == 0
    assert [c[0] for c in calls] == ["claude"]
    out = capsys.readouterr().out
    assert out.count("PIN: nothing was pinned") == 1 and "Ctrl+T" in out


@pytest.mark.parametrize("out, rc", [("Workspace not trusted", 0), ("started a copy abcdef12", 0), ("boom", 1)])
def test_resume_prints_no_pin_hint_when_the_wake_failed(tmp_path, monkeypatch, capsys, out, rc):
    work = _setup_inventory(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "live_pid", lambda u: None)
    monkeypatch.setattr(subprocess, "run",
                        lambda args, **kw: subprocess.CompletedProcess(args, rc, stdout=out, stderr=""))
    R.main(["--work", work, "resume", "deadbeef"])
    assert "PIN:" not in capsys.readouterr().out


def test_the_cli_has_no_pin_commands():
    with pytest.raises(SystemExit):
        R.main(["pin", "aaaaaaaa"])
    with pytest.raises(SystemExit):
        R.main(["unpin", "aaaaaaaa"])


# ---------- wrap-wait ----------

def _transcript(cfgdir, uuid, entries):
    d = cfgdir / "projects" / "-some-proj"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{uuid}.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")


WRAP_MARK = "run a real session wrap"


def test_wrap_status_pure():
    assert R.wrap_status(["a", "x\n\nSession Wrap done\n"]) == "DONE"
    assert R.wrap_status(["did stuff. Reply `go` to apply."]) == "HELD"
    assert R.wrap_status(["Session Wrap done is the marker", "still working"]) == "RUNNING"
    assert R.wrap_status(["Session Wrap done. extra"]) == "RUNNING"
    assert R.wrap_status([]) == "RUNNING"
    # the session-wrap skill's own closing line follows the marker
    assert R.wrap_status(["x\n\nSession Wrap done\n\nYou can archive this conversation now.\n"]) == "DONE"
    assert R.wrap_status(["Session Wrap done\n\nNot ready to archive: a held step."]) == "HELD"
    assert R.wrap_status(["Session Wrap done\n\nNext session starts fresh."]) == "HELD"
    assert R.wrap_status(["You can archive this conversation now."]) == "RUNNING"
    assert R.wrap_status(["Session Wrap done\nsomething else"]) == "RUNNING"
    # an earlier progress block that quotes the instruction must not count
    assert R.wrap_status(["Reply `go` is what I will say", "now working"]) == "RUNNING"


def test_wrap_wait_reports_done_held_running(iso, capsys):
    _transcript(iso, "aaaaaaaa-1", [_u(WRAP_MARK), _a(tool="Bash"), _a(tool="Edit"), _a("summary\n\nSession Wrap done")])
    _transcript(iso, "bbbbbbbb-1", [_u("old"), _a("x"), _u(WRAP_MARK + " now"), _a(tool="Bash"),
                                    _a("Pushed.\nNeeds your OK to delete a branch. Reply `go` to apply.")])
    _transcript(iso, "cccccccc-1", [_u(WRAP_MARK), _a("Session Wrap done"), _u(WRAP_MARK), _a(tool="Bash"),
                                    _a("working on it")])
    assert R.main(["wrap-wait", "--mark", WRAP_MARK, "aaaaaaaa", "bbbbbbbb", "cccccccc"]) == 1
    out = capsys.readouterr().out
    assert "aaaaaaaa DONE tool calls: 2" in out
    assert "bbbbbbbb HELD tool calls: 1" in out
    assert "reply tail:" in out and "Reply `go` to apply." in out
    assert "cccccccc RUNNING tool calls: 1" in out  # an older DONE before the latest request does not count


def test_wrap_wait_exit_zero_when_all_settled(iso, capsys):
    _transcript(iso, "aaaaaaaa-1", [_u(WRAP_MARK), _a("Session Wrap done")])
    _transcript(iso, "bbbbbbbb-1", [{"type": "queue-operation", "content": WRAP_MARK}, _a("Reply `go` to apply.")])
    assert R.main(["wrap-wait", "--mark", WRAP_MARK, "aaaaaaaa", "bbbbbbbb"]) == 0


def test_wrap_wait_missing_transcript_and_mark(iso, capsys):
    _transcript(iso, "bbbbbbbb-1", [_u("hello"), _a("hi")])
    assert R.main(["wrap-wait", "--mark", WRAP_MARK, "aaaaaaaa", "bbbbbbbb"]) == 1
    out = capsys.readouterr().out
    assert "aaaaaaaa NO-TRANSCRIPT" in out and "bbbbbbbb NO-MARK" in out


def test_wrap_wait_polls_until_done(iso, monkeypatch, capsys):
    _transcript(iso, "aaaaaaaa-1", [_u(WRAP_MARK), _a("working")])
    sleeps = []

    def fake_sleep(n):
        sleeps.append(n)
        _transcript(iso, "aaaaaaaa-1", [_u(WRAP_MARK), _a("working"), _a("Session Wrap done")])
    monkeypatch.setattr(time, "sleep", fake_sleep)
    assert R.main(["wrap-wait", "--wait", "600", "--mark", WRAP_MARK, "aaaaaaaa"]) == 0
    assert sleeps == [R.POLL_S]
    assert "aaaaaaaa DONE" in capsys.readouterr().out


def test_wrap_wait_stops_at_the_deadline(iso, monkeypatch, capsys):
    _transcript(iso, "aaaaaaaa-1", [_u(WRAP_MARK), _a("working")])
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    monkeypatch.setattr(time, "sleep", lambda n: now.__setitem__(0, now[0] + n))
    assert R.main(["wrap-wait", "--wait", "30", "--mark", WRAP_MARK, "aaaaaaaa"]) == 1
    assert "aaaaaaaa RUNNING" in capsys.readouterr().out


# ---------- sidechain / meta records are not the session's own thread ----------

def _side(e):
    return {**e, "isSidechain": True}


def test_review_reply_ignores_sidechain_and_meta_records():
    es = [_u("RECOVERY REVIEW v1 real"), _a("main reply"), _a(tool="Bash"),
          _side(_u("RECOVERY REVIEW v1 from a subagent")), _side(_a("subagent text", tool="Edit")),
          {**_u("RECOVERY REVIEW v1 meta"), "isMeta": True}]
    text, tools, err = R.review_reply(es)
    assert err == "" and text == "main reply"
    assert len(tools) == 1 and tools[0].startswith("Bash: ")
    # a marker only in sidechain/meta records is not found at all
    assert R.review_reply([_side(_u("RECOVERY REVIEW v1 x")), _a("y")])[2] == "prompt not in transcript yet"


def test_marker_reply_ignores_sidechain_and_meta_records():
    es = [_u("M real"), _a(tool="Bash"), _a("main final"),
          _side(_u("M side")), _side(_a("Session Wrap done", tool="Edit")),
          {**_u("M meta"), "isMeta": True}]
    hits, texts, tools = R.marker_reply(es, "M ")
    assert hits == 1 and texts == ["main final"] and tools == 1
    assert R.wrap_status(texts) == "RUNNING"  # the subagent's "Session Wrap done" must not make it DONE


def test_wrap_wait_ignores_a_sidechain_done(iso, capsys):
    _transcript(iso, "aaaaaaaa-1", [_u(WRAP_MARK), _a("working"), _side(_a("Session Wrap done"))])
    assert R.main(["wrap-wait", "--mark", WRAP_MARK, "aaaaaaaa"]) == 1
    assert "aaaaaaaa RUNNING" in capsys.readouterr().out


def test_last_local_ts_still_counts_sidechain_activity(iso):
    _transcript(iso, "aaaaaaaa-1", [{**_a("x"), "timestamp": "2025-03-04T01:00:00Z"},
                                    {**_side(_a("y")), "timestamp": "2025-03-04T02:00:00Z"}])
    assert R.last_local_ts(R.find_transcript("aaaaaaaa-1")) == "2025-03-04T02:00:00Z"


def test_resume_skips_a_missing_cwd_and_continues(tmp_path, monkeypatch, capsys):
    # A removed worktree must not abort the batch, and its session is never woken from another folder.
    work = _setup_inventory(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "live_pid", lambda u: None)
    calls = []

    def fake(args, **kw):
        calls.append((args, kw))
        return subprocess.CompletedProcess(args, 0, stdout="backgrounded", stderr="")
    monkeypatch.setattr(subprocess, "run", fake)
    assert R.main(["--work", work, "resume", "0badc0de", "deadbeef"]) == 0
    out = capsys.readouterr().out
    assert "0badc0de: SKIP missing cwd" in out
    resumes = [c for c in calls if c[0][:3] == ["claude", "--bg", "--resume"]]
    assert [c[0][3] for c in resumes] == ["uuid-1"]


def test_resume_reports_an_os_error_and_continues(tmp_path, monkeypatch, capsys):
    work = _setup_inventory(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "live_pid", lambda u: None)
    (tmp_path / "removed-worktree").mkdir()
    seen = []

    def fake(args, **kw):
        seen.append(args[3] if args[:3] == ["claude", "--bg", "--resume"] else None)
        if args[:4] == ["claude", "--bg", "--resume", "uuid-2"]:
            raise FileNotFoundError(2, "No such file or directory", "claude")
        return subprocess.CompletedProcess(args, 0, stdout="backgrounded", stderr="")
    monkeypatch.setattr(subprocess, "run", fake)
    assert R.main(["--work", work, "resume", "0badc0de", "deadbeef"]) == 0
    out = capsys.readouterr().out
    assert "0badc0de: FAIL could not run the resume (FileNotFoundError" in out
    assert "uuid-1" in seen


# ---------- exact transcript resolution ----------

def _tfile(cfgdir, proj, uuid, text, mtime=None):
    d = cfgdir / "projects" / proj
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{uuid}.jsonl"
    p.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def _job(cfgdir, short, uuid, cwd=None):
    d = cfgdir / "jobs" / short
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({"sessionId": uuid, "cwd": cwd, "daemonShort": short}))


def test_short_id_resolves_through_the_job_not_the_first_glob(iso):
    _tfile(iso, "-a", "abcd1234-old-fork", "old")
    want = _tfile(iso, "-a", "abcd1234-real", "real")
    _job(iso, "abcd1234", "abcd1234-real")
    f, note = R.resolve_transcript("abcd1234", by_uuid=False)
    assert f == str(want) and note is None


def test_ambiguous_short_id_without_a_job_is_refused(iso):
    _tfile(iso, "-a", "abcd1234-one", "x")
    _tfile(iso, "-b", "abcd1234-two", "y")
    f, note = R.resolve_transcript("abcd1234", by_uuid=False)
    assert f is None and note.startswith("AMBIGUOUS short id abcd1234")
    status, tools, last = R.wrap_state("abcd1234", "m")
    assert status == "AMBIGUOUS"


def test_same_uuid_in_two_project_folders_prefers_the_session_cwd(iso):
    cwd = "/home/user/projects/repo"
    newer_elsewhere = _tfile(iso, "-other", "u-1", "elsewhere", mtime=2_000_000_000)
    in_cwd = _tfile(iso, R.project_dir_name(cwd), "u-1", "home", mtime=1_000_000_000)
    assert R.find_transcript("u-1", cwd=cwd) == str(in_cwd)
    assert R.find_transcript("u-1") == str(newer_elsewhere)


def test_project_dir_name_matches_claude_code():
    assert R.project_dir_name("/home/user/projects/example") == "-home-user-projects-example"
    assert R.project_dir_name("/a/.claude/worktrees/x") == "-a--claude-worktrees-x"


# ---------- a later user turn unsettles a wrap ----------

def _asst(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _user(text):
    return {"type": "user", "message": {"content": text}}


def _tool_result():
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}


def test_wrap_done_then_a_new_user_message_is_running(iso):
    _transcript(iso, "u-wrap", [_user(WRAP_MARK), _asst("summary\n\nSession Wrap done"), _user("one more thing")])
    _job(iso, "u-wrap00", "u-wrap")
    assert R.wrap_state("u-wrap00", WRAP_MARK)[0] == "RUNNING"


def test_wrap_done_then_a_queued_message_is_running(iso):
    _transcript(iso, "u-q", [_user(WRAP_MARK), _asst("Session Wrap done"), {"type": "queue-operation", "operation": "enqueue"}])
    _job(iso, "u-q00000", "u-q")
    assert R.wrap_state("u-q00000", WRAP_MARK)[0] == "RUNNING"


def _queued(**attachment):
    return {"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "prompt",
                                                 "prompt": "one more thing", **attachment}}


def test_wrap_done_then_a_human_queued_attachment_is_running(iso):
    _transcript(iso, "u-h", [_user(WRAP_MARK), _asst("Session Wrap done"), _queued(origin={"kind": "human"})])
    _job(iso, "u-h00000", "u-h")
    assert R.wrap_state("u-h00000", WRAP_MARK)[0] == "RUNNING"


def test_wrap_done_then_a_human_turn_flag_attachment_is_running(iso):
    _transcript(iso, "u-f", [_user(WRAP_MARK), _asst("Session Wrap done"), _queued(humanTurn=True)])
    _job(iso, "u-f00000", "u-f")
    assert R.wrap_state("u-f00000", WRAP_MARK)[0] == "RUNNING"


def test_a_non_human_queued_attachment_does_not_reopen_a_wrap(iso):
    _transcript(iso, "u-n", [_user(WRAP_MARK), _asst("Session Wrap done"), _queued(origin={"kind": "task"})])
    _job(iso, "u-n00000", "u-n")
    assert R.wrap_state("u-n00000", WRAP_MARK)[0] == "DONE"


def test_wrap_done_after_the_new_message_is_answered_is_done_again(iso):
    _transcript(iso, "u-a", [_user(WRAP_MARK), _asst("Session Wrap done"), _user("and this?"),
                             _asst("answered.\n\nSession Wrap done")])
    _job(iso, "u-a00000", "u-a")
    assert R.wrap_state("u-a00000", WRAP_MARK)[0] == "DONE"


def test_tool_results_after_the_wrap_do_not_reopen_it(iso):
    _transcript(iso, "u-t", [_user(WRAP_MARK), _asst("Session Wrap done"), _tool_result()])
    _job(iso, "u-t00000", "u-t")
    assert R.wrap_state("u-t00000", WRAP_MARK)[0] == "DONE"
