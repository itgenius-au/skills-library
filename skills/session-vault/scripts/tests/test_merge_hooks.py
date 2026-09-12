"""Tests for lib/merge-hooks.py: idempotent add, preserve existing, clean remove."""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MH = os.path.join(HERE, "..", "lib", "merge-hooks.py")
PH = "/x/bq-log-prompt.sh"
RH = "/x/bq-log-response.sh"


def _run(args):
    return subprocess.run([sys.executable, MH] + args, capture_output=True, text=True)


def _cmds(d, event):
    return [h["command"] for g in d.get("hooks", {}).get(event, []) for h in g.get("hooks", [])]


def test_add_preserves_existing(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "AC"}]}]}}))
    _run(["--settings", str(s), "--prompt-hook", PH, "--response-hook", RH])
    d = json.loads(s.read_text())
    assert "AC" in _cmds(d, "Stop")
    assert RH in _cmds(d, "Stop")
    assert PH in _cmds(d, "UserPromptSubmit")


def test_add_idempotent(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text("{}")
    _run(["--settings", str(s), "--prompt-hook", PH, "--response-hook", RH])
    _run(["--settings", str(s), "--prompt-hook", PH, "--response-hook", RH])
    d = json.loads(s.read_text())
    assert _cmds(d, "UserPromptSubmit").count(PH) == 1
    assert _cmds(d, "Stop").count(RH) == 1


def test_remove_takes_ours_out(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text("{}")
    _run(["--settings", str(s), "--prompt-hook", PH, "--response-hook", RH])
    _run(["--settings", str(s), "--prompt-hook", PH, "--response-hook", RH, "--remove"])
    d = json.loads(s.read_text())
    assert PH not in _cmds(d, "UserPromptSubmit")
    assert RH not in _cmds(d, "Stop")


def test_remove_preserves_other(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "AC"},
        {"type": "command", "command": RH},
    ]}]}}))
    _run(["--settings", str(s), "--prompt-hook", PH, "--response-hook", RH, "--remove"])
    d = json.loads(s.read_text())
    assert "AC" in _cmds(d, "Stop")
    assert RH not in _cmds(d, "Stop")


def test_backup_written(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"hooks": {}}))
    _run(["--settings", str(s), "--prompt-hook", PH, "--response-hook", RH])
    assert (tmp_path / "settings.json.bak").exists()
