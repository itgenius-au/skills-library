"""Setup errors stop with exit 2 and one clear line, never a traceback or a key.

Covers: template placeholders, gcloud missing or failing, a key that is not
JSON, missing google-auth, and an end-to-end run with no config at all."""
import importlib.util
import os
import pathlib
import subprocess
import sys
from subprocess import run as real_run  # bound before the conftest guard

import pytest

MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "chat-post.py"
_spec = importlib.util.spec_from_file_location("chat_post_setup", MOD_PATH)
chat_post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_post)


# --- placeholders: only values that START like a template value ---

@pytest.mark.parametrize(("value", "expected"), [
    ("your_gcp_project", True),
    ("users/your_bot_user_id", True),
    ("you@example.com", True),
    ("your_gcloud_account@example.com", True),
    ("acme-your_team-project", False),
    ("ops-key-your_", False),
    ("sam@example.com", False),
    ("users/111111111111", False),
    (42, False),
])
def test_is_placeholder_matches_only_template_values(value, expected):
    assert chat_post._is_placeholder(value) is expected


# --- _load_sa_key failures ---

@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(chat_post, "CHAT", {"gcp_project": "acme-chat"})


def test_missing_gcloud_exits_2(monkeypatch, capsys, configured):
    def no_gcloud(*a, **k):
        raise FileNotFoundError("gcloud")

    monkeypatch.setattr(chat_post.subprocess, "check_output", no_gcloud)
    with pytest.raises(SystemExit) as exc:
        chat_post._load_sa_key("acme-bot-key")
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "gcloud not found" in err and "'acme-bot-key'" in err and "'acme-chat'" in err


def test_gcloud_failure_exits_2_naming_secret_project_account(monkeypatch, capsys, configured):
    def denied(cmd, **k):
        raise subprocess.CalledProcessError(1, cmd, output="KEY-MATERIAL",
                                            stderr="WARN x\nERROR: PERMISSION_DENIED")

    monkeypatch.setattr(chat_post.subprocess, "check_output", denied)
    with pytest.raises(SystemExit) as exc:
        chat_post._load_sa_key("acme-bot-key")
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "'acme-bot-key'" in err and "'acme-chat'" in err
    assert "the active gcloud account" in err and "PERMISSION_DENIED" in err
    assert "KEY-MATERIAL" not in err


def test_key_that_is_not_json_exits_2_without_printing_it(monkeypatch, capsys, configured):
    monkeypatch.setattr(chat_post.subprocess, "check_output", lambda *a, **k: "not-json-KEY")
    with pytest.raises(SystemExit) as exc:
        chat_post._load_sa_key("acme-bot-key")
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "is not a JSON key file" in err and "not-json-KEY" not in err


# --- missing google-auth: one line, exit 2 ---

def test_missing_google_auth_exits_2(monkeypatch, capsys):
    def needs_google(args):
        raise ImportError("No module named 'google'", name="google")

    monkeypatch.setattr(chat_post, "cmd_list", needs_google)
    monkeypatch.setattr(sys, "argv", ["chat-post.py", "list", "spaces/AAAAexample"])
    with pytest.raises(SystemExit) as exc:
        chat_post.main()
    assert exc.value.code == 2
    assert "pip install google-auth requests" in capsys.readouterr().err


def test_other_import_errors_are_not_hidden(monkeypatch):
    def broken(args):
        raise ImportError("No module named 'yaml'", name="yaml")

    monkeypatch.setattr(chat_post, "cmd_list", broken)
    monkeypatch.setattr(sys, "argv", ["chat-post.py", "list", "spaces/AAAAexample"])
    with pytest.raises(ImportError):
        chat_post.main()


# --- end to end: a new machine with no config ---

def test_no_config_end_to_end_exits_2(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "GOOGLE_CHAT_UPDATE_CONFIG"}
    env["HOME"] = str(tmp_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = real_run([sys.executable, str(MOD_PATH), "list", "spaces/AAAAexample"],
                 capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2, r.stderr
    assert "No config file at" in r.stderr
    assert "google-chat-update.config.example.json" in r.stderr
    assert "Traceback" not in r.stderr
