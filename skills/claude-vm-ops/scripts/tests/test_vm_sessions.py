"""Tests for the pure helpers in vm_sessions.py. The /proc scan itself needs a live VM."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "vm_sessions.py"
SECRET = "sk-" + "ant-oat01-FAKEVALUE123"  # split so no secret scanner mistakes the fixture for a key

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")


def load():
    spec = importlib.util.spec_from_file_location("vm_sessions", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_text_of_handles_string_blocks_and_junk():
    vs = load()
    assert vs.text_of({"content": "hello"}) == "hello"
    assert vs.text_of({"content": [{"type": "text", "text": "a"}, {"type": "tool_use"}, "x",
                                   {"type": "text", "text": "b"}]}) == "a b"
    assert vs.text_of({"content": 5}) == ""
    assert vs.text_of({}) == ""


def test_read_transcript_title_first_last_and_turns(tmp_path):
    vs = load()
    lines = [
        {"type": "summary", "summary": "Old title"},
        {"type": "user", "message": {"content": "<system-reminder>skip me</system-reminder>"}},
        {"type": "user", "isMeta": True, "message": {"content": "meta, skip"}},
        {"type": "user", "toolUseResult": {"x": 1}, "message": {"content": "tool output, skip"}},
        {"type": "user", "message": {"content": "first ask"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "first answer"}]}},
        {"type": "user", "message": {"content": "second ask"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "last answer"}]}},
        {"customTitle": "Final title"},
    ]
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    info = vs.read_transcript(str(f))
    assert info["title"] == "Final title"
    assert info["first_user"] == "first ask" and info["last_user"] == "second ask"
    assert info["last_assistant"] == "last answer" and info["turns"] == 2


def test_read_transcript_missing_file_reports_error(tmp_path):
    vs = load()
    assert "error" in vs.read_transcript(str(tmp_path / "nope.jsonl"))


def test_session_bin_can_be_overridden(monkeypatch):
    monkeypatch.setenv("CLAUDE_SESSION_BIN", "claude")
    assert load().SESSION_BIN == "claude"
    monkeypatch.delenv("CLAUDE_SESSION_BIN")
    assert load().SESSION_BIN == "claude.exe"


def test_uuid_regex_matches_the_scratch_folder_link():
    vs = load()
    m = vs.UUID_RE.search("/tmp/claude-1001/-home-claude-1-projects-workspace/"
                          "0a1b2c3d-1111-2222-3333-444455556666/tasks")
    assert m.group(1) == "-home-claude-1-projects-workspace"
    assert m.group(2) == "0a1b2c3d-1111-2222-3333-444455556666"


def test_redact_replaces_token_shapes_and_keeps_ordinary_text():
    vs = load()
    assert vs.redact("use " + SECRET + " now") == "use [REDACTED] now"
    assert vs.redact("key " + "a1B2c3D4" * 5 + " end") == "key [REDACTED] end"
    plain = "Fix the login page, then run the tests in /srv/app."
    assert vs.redact(plain) == plain  # positive control: the filter leaves normal text alone


def test_read_transcript_redacts_every_text_field(tmp_path):
    vs = load()
    lines = [
        {"type": "summary", "summary": "Title " + SECRET},
        {"type": "user", "message": {"content": "first ask with " + SECRET}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "reply " + SECRET}]}},
        {"type": "user", "message": {"content": "last ask with " + "z9Y8x7W6" * 6}},
    ]
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    info = vs.read_transcript(str(f))
    assert SECRET not in json.dumps(info) and "sk-ant" not in json.dumps(info)
    assert "z9Y8x7W6z9Y8x7W6" not in json.dumps(info)
    assert info["title"] == "Title [REDACTED]"
    assert info["first_user"] == "first ask with [REDACTED]"
    assert info["last_assistant"] == "reply [REDACTED]"
    assert info["last_user"] == "last ask with [REDACTED]"


def test_redaction_happens_before_the_cut_so_no_prefix_leaks(tmp_path):
    vs = load()
    # The first token starts 6 characters before the 220-character cut, and the second one is cut
    # in the middle by the 260-character tail. Cutting first would leave part of each.
    lines = [
        {"type": "user", "message": {"content": "ab " * 71 + SECRET}},
        {"type": "assistant", "message": {"content": [{"type": "text",
                                                       "text": "ef " * 20 + SECRET + " " + "cd " * 82}]}},
    ]
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    info = vs.read_transcript(str(f))
    assert info["first_user"].startswith("ab ab ") and "sk-a" not in info["first_user"]
    assert info["first_user"].endswith("[REDACT")  # the placeholder is cut, the token is not
    assert "FAKEVALUE" not in info["last_assistant"] and "[REDACTED]" in info["last_assistant"]
    # Control: the same cut on the raw text would have shown the token parts.
    assert "sk-a" in ("ab " * 71 + SECRET)[:220]
    assert "FAKEVALUE" in ("ef " * 20 + SECRET + " " + "cd " * 82)[-260:]


def test_help_prints_usage_and_does_not_run_the_inventory(monkeypatch, capsys):
    vs = load()
    calls = []
    monkeypatch.setattr(vs, "procs", lambda: calls.append(1) or {})
    with pytest.raises(SystemExit) as exc:
        vs.main(["--help"])
    assert exc.value.code == 0 and calls == []
    out = capsys.readouterr().out
    assert "usage:" in out and "private path" in out
    vs.main([])  # positive control: with no argument the inventory does run
    assert calls == [1]


def test_unknown_arguments_exit_2_without_running_the_inventory(monkeypatch, capsys):
    vs = load()
    calls = []
    monkeypatch.setattr(vs, "procs", lambda: calls.append(1) or {})
    for bad in (["--bogus"], ["claude-1"]):
        with pytest.raises(SystemExit) as exc:
            vs.main(bad)
        assert exc.value.code == 2
    assert calls == []
    assert "usage:" in capsys.readouterr().err


def test_help_from_the_command_line(tmp_path):
    r = subprocess.run([sys.executable, "-I", str(SCRIPT), "--help"], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0 and "usage:" in r.stdout
    assert not [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
