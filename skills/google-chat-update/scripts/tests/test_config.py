#!/usr/bin/env python3
"""Tests for the skill-scoped config file: load_config() and _require().

No network and no gcloud. Each test points CONFIG_PATH at a temp file.
"""
import importlib.util
import json
import pathlib

import pytest

MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "chat-post.py"
TEMPLATE = pathlib.Path(__file__).resolve().parents[2] / "templates" / "google-chat-update.config.example.json"
_spec = importlib.util.spec_from_file_location("chat_post", MOD_PATH)
chat_post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_post)


def _load(monkeypatch, path):
    monkeypatch.setattr(chat_post, "CONFIG_PATH", str(path))
    values, status, placeholders = chat_post.load_config()
    monkeypatch.setattr(chat_post, "CHAT", values)
    monkeypatch.setattr(chat_post, "CONFIG_STATUS", status)
    monkeypatch.setattr(chat_post, "PLACEHOLDER_KEYS", placeholders)
    return values, status, placeholders


def test_missing_file_exits_2_and_names_template(monkeypatch, tmp_path, capsys):
    _, status, _ = _load(monkeypatch, tmp_path / "nope.json")
    assert status == "missing"
    with pytest.raises(SystemExit) as e:
        chat_post._require("bot_sa_secret")
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "nope.json" in err and "google-chat-update.config.example.json" in err


def test_bad_json_is_invalid(monkeypatch, tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{not json")
    _, status, _ = _load(monkeypatch, p)
    assert status == "invalid"
    with pytest.raises(SystemExit) as e:
        chat_post._require("bot_sa_secret")
    assert e.value.code == 2


def test_non_object_is_invalid(monkeypatch, tmp_path):
    p = tmp_path / "c.json"
    p.write_text("[1, 2]")
    assert _load(monkeypatch, p)[1] == "invalid"


def test_template_values_count_as_unset(monkeypatch, tmp_path, capsys):
    values, status, placeholders = _load(monkeypatch, TEMPLATE)
    assert status == "ok"
    assert "bot_sa_secret" in placeholders and "dwd_subject" in placeholders
    assert "bot_sa_secret" not in values
    assert not any(k.startswith("_") for k in values)
    with pytest.raises(SystemExit) as e:
        chat_post._require("bot_sa_secret")
    assert e.value.code == 2
    assert "placeholder" in capsys.readouterr().err


def test_filled_value_is_returned(monkeypatch, tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"gcp_project": "acme-chat", "bot_sa_secret": "acme-bot-key"}))
    _load(monkeypatch, p)
    assert chat_post._require("bot_sa_secret") == "acme-bot-key"


def test_missing_key_in_good_file_exits_2(monkeypatch, tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"gcp_project": "acme-chat"}))
    _load(monkeypatch, p)
    with pytest.raises(SystemExit) as e:
        chat_post._require("admin_sa_secret")
    assert e.value.code == 2
    assert "Missing `admin_sa_secret`" in capsys.readouterr().err


def test_template_is_valid_json_with_every_documented_key():
    data = json.loads(TEMPLATE.read_text())
    for key in ("gcp_project", "bot_sa_secret", "bot_display_name", "bot_user_id",
                "admin_sa_secret", "dwd_subject", "self_user_id", "default_write_identity"):
        assert key in data, key
