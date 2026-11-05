#!/usr/bin/env python3
"""Unit tests for chat-post.py react helpers (emoji + token-source precedence + URL/body).

Pure-logic tests only: no network, no gcloud, no Secret Manager. The token minting itself is thin
I/O and is exercised by the live verify step in the build, not here.
"""
import importlib.util
import pathlib
import sys

import pytest

MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "chat-post.py"
_spec = importlib.util.spec_from_file_location("chat_post", MOD_PATH)
chat_post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_post)


# --- emoji precedence: arg > react_emoji > default 👁 ---

def test_emoji_arg_wins():
    assert chat_post.resolve_react_emoji("✅", {"react_emoji": "👁"}) == "✅"


def test_emoji_config_when_no_arg():
    assert chat_post.resolve_react_emoji(None, {"react_emoji": "🙋"}) == "🙋"


def test_emoji_default_when_nothing():
    assert chat_post.resolve_react_emoji(None, {}) == "👁"


# --- token-source precedence (auto): personal_oauth > gcloud-adc > admin_dwd ---

def test_plan_personal_oauth_takes_precedence():
    chat = {
        "personal_oauth_secret": "my-chat-oauth",
        "personal_token_source": "gcloud-adc",
        "admin_sa_secret": "admin-sa-secret",
        "dwd_subject": "you@example.com",
    }
    plan = chat_post.resolve_react_plan(chat)
    assert plan["source"] == "personal_oauth"
    assert plan["secret"] == "my-chat-oauth"


def test_plan_gcloud_adc_when_no_oauth_secret():
    chat = {"personal_token_source": "gcloud-adc",
            "admin_sa_secret": "admin-sa-secret", "dwd_subject": "you@example.com"}
    plan = chat_post.resolve_react_plan(chat)
    assert plan["source"] == "gcloud-adc"


def test_plan_admin_dwd_fallback():
    chat = {"admin_sa_secret": "admin-sa-secret", "dwd_subject": "alex@example.com"}
    plan = chat_post.resolve_react_plan(chat)
    assert plan["source"] == "admin_dwd"
    assert plan["secret"] == "admin-sa-secret"
    assert plan["subject"] == "alex@example.com"


# --- forcing a source via react_token_source ---

def test_plan_force_admin_dwd_over_personal():
    chat = {
        "react_token_source": "admin_dwd",
        "personal_oauth_secret": "my-chat-oauth",
        "admin_sa_secret": "admin-sa-secret",
        "dwd_subject": "alex@example.com",
    }
    plan = chat_post.resolve_react_plan(chat)
    assert plan["source"] == "admin_dwd"


def test_plan_force_missing_config_errors():
    # forced personal_oauth but no secret configured
    chat = {"react_token_source": "personal_oauth"}
    with pytest.raises(SystemExit):
        chat_post.resolve_react_plan(chat)


def test_plan_force_invalid_value_errors():
    chat = {"react_token_source": "banana", "admin_sa_secret": "x", "dwd_subject": "y"}
    with pytest.raises(SystemExit):
        chat_post.resolve_react_plan(chat)


# --- no self path configured -> actionable error ---

def test_plan_none_configured_errors():
    with pytest.raises(SystemExit):
        chat_post.resolve_react_plan({})


def test_plan_gcloud_adc_source_string_ignored_if_not_that_value():
    # personal_token_source set to something other than gcloud-adc must NOT pick B
    chat = {"personal_token_source": "nonsense",
            "admin_sa_secret": "admin-sa-secret", "dwd_subject": "p@x"}
    plan = chat_post.resolve_react_plan(chat)
    assert plan["source"] == "admin_dwd"


# --- URL + body shape (dot-joined message resource name) ---

def test_reactions_url():
    msg = "spaces/AAAA/messages/THREAD.MSG"
    assert chat_post.reactions_url(msg) == \
        "https://chat.googleapis.com/v1/spaces/AAAA/messages/THREAD.MSG/reactions"


def test_react_body_shape():
    assert chat_post.react_body("👁") == {"emoji": {"unicode": "👁"}}


# --- react scope is the BROAD chat.messages, never create/reactions-narrow ---

def test_react_scope_is_broad_chat_messages():
    assert chat_post.REACT_SCOPES == ["https://www.googleapis.com/auth/chat.messages"]


# --- message-name validation: dot-joined thread.msg, not slash ---

def test_valid_message_name_dot_ok():
    assert chat_post.valid_message_name("spaces/AAAA/messages/THREAD.MSG")


def test_valid_message_name_slash_bad():
    # the malformed shape the docs warn 400s
    assert not chat_post.valid_message_name("spaces/AAAA/messages/THREAD/MSG")


def test_valid_message_name_missing_messages_segment():
    assert not chat_post.valid_message_name("spaces/AAAA/threads/T")


def test_valid_message_name_no_spaces_prefix():
    assert not chat_post.valid_message_name("messages/T.M")


# --- react_token: the three credential branches (mocked, no network) ---

def test_react_token_admin_dwd(monkeypatch):
    import google.oauth2.service_account as gsa
    captured = {}

    class FakeCreds:
        def __init__(self):
            self.token = None

        def with_subject(self, subj):
            captured["subject"] = subj
            return self

        def refresh(self, _req):
            self.token = "ADMIN_TOKEN"

    def fake_from_info(info, scopes=None):
        captured["scopes"] = scopes
        return FakeCreds()

    monkeypatch.setattr(gsa.Credentials, "from_service_account_info", staticmethod(fake_from_info))
    monkeypatch.setattr(chat_post, "_load_sa_key", lambda secret, project=None: {"sa": secret})
    tok = chat_post.react_token({"source": "admin_dwd", "secret": "admin-key", "subject": "p@x"})
    assert tok == "ADMIN_TOKEN"
    assert captured["subject"] == "p@x"            # DWD impersonation, not the raw SA
    assert captured["scopes"] == chat_post.REACT_SCOPES  # broad chat.messages


def test_react_token_gcloud_adc(monkeypatch):
    monkeypatch.setattr(chat_post.subprocess, "check_output", lambda *a, **k: "  TOK123\n")
    assert chat_post.react_token({"source": "gcloud-adc"}) == "TOK123"


def test_react_token_personal_oauth(monkeypatch):
    import google.oauth2.credentials as goc

    class FakeCreds:
        def __init__(self, *a, **k):
            self.token = None
            self.kw = k

        def refresh(self, _req):
            self.token = "OAUTH_TOKEN"

    monkeypatch.setattr(goc, "Credentials", FakeCreds)
    monkeypatch.setattr(chat_post, "_load_sa_key",
                        lambda s, project=None: {"client_id": "c", "client_secret": "s", "refresh_token": "r"})
    assert chat_post.react_token({"source": "personal_oauth", "secret": "oauth"}) == "OAUTH_TOKEN"


def test_react_token_personal_oauth_malformed_secret_errors(monkeypatch):
    # missing client_id/client_secret -> actionable SystemExit, not a raw KeyError
    monkeypatch.setattr(chat_post, "_load_sa_key", lambda s, project=None: {"refresh_token": "r"})
    with pytest.raises(SystemExit):
        chat_post.react_token({"source": "personal_oauth", "secret": "oauth"})


# --- _verify_reaction: match / mismatch / cannot-verify ---

def test_verify_reaction_match_ok():
    # exact match -> no raise, no warning
    chat_post._verify_reaction(
        {"name": "n", "user": {"name": "users/1"}, "emoji": {"unicode": "👁"}},
        {"self_user_id": "users/1"})


def test_verify_reaction_mismatch_hard_fails():
    with pytest.raises(SystemExit):
        chat_post._verify_reaction(
            {"user": {"name": "users/2"}, "emoji": {"unicode": "👁"}},
            {"self_user_id": "users/1"})


def test_verify_reaction_unset_self_id_warns(capsys):
    chat_post._verify_reaction(
        {"user": {"name": "users/2"}, "emoji": {"unicode": "👁"}}, {})
    assert "could not verify" in capsys.readouterr().err


def test_verify_reaction_missing_user_warns(capsys):
    chat_post._verify_reaction({"emoji": {"unicode": "👁"}}, {"self_user_id": "users/1"})
    assert "could not verify" in capsys.readouterr().err


# --- cmd_react: validation + dry-run never mints ---

class _Args:
    def __init__(self, message, emoji=None, dry_run=False):
        self.message = message
        self.emoji = emoji
        self.dry_run = dry_run


def test_cmd_react_rejects_slash_form():
    with pytest.raises(SystemExit):
        chat_post.cmd_react(_Args("spaces/S/messages/T/M"))


def test_cmd_react_dry_run_never_mints(monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("dry-run must not mint a token or POST")

    monkeypatch.setattr(chat_post, "react_token", boom)
    monkeypatch.setattr(chat_post, "_http", boom)
    monkeypatch.setattr(chat_post, "resolve_react_plan", lambda *a, **k: {"source": "admin_dwd"})
    chat_post.cmd_react(_Args("spaces/S/messages/T.M", emoji="✅", dry_run=True))
    assert "DRY-RUN react ✅ via admin_dwd" in capsys.readouterr().out


def test_cmd_react_dry_run_without_credential(monkeypatch, capsys):
    def raise_exit(*a, **k):
        raise SystemExit("no cred")

    monkeypatch.setattr(chat_post, "resolve_react_plan", raise_exit)
    monkeypatch.setattr(chat_post, "react_token", raise_exit)
    monkeypatch.setattr(chat_post, "_http", raise_exit)
    chat_post.cmd_react(_Args("spaces/S/messages/T.M", dry_run=True))
    assert "no react credential configured" in capsys.readouterr().out


def test_react_argparse_dispatches(monkeypatch):
    called = {}
    monkeypatch.setattr(chat_post, "cmd_react",
                        lambda a: called.update(message=a.message, emoji=a.emoji, dry=a.dry_run))
    monkeypatch.setattr(sys, "argv",
                        ["chat-post.py", "react", "spaces/S/messages/T.M", "✅", "--dry-run"])
    chat_post.main()
    assert called == {"message": "spaces/S/messages/T.M", "emoji": "✅", "dry": True}


# --- _load_sa_key: per-secret project override + gcp_project fallback ---
# Exercises the project-selection logic added for split-project setups (a bot SA
# key in one Secret Manager project, the admin SA key in another). subprocess is mocked, so
# no gcloud call and no network.

def _capture_gcloud_cmd(monkeypatch):
    """Mock subprocess.check_output so _load_sa_key runs offline; return the captured cmd."""
    captured = {}

    def fake_check_output(cmd, text=None, **kwargs):
        captured["cmd"] = cmd
        return '{"ok": true}'

    monkeypatch.setattr(chat_post.subprocess, "check_output", fake_check_output)
    return captured


def test_load_sa_key_uses_override_project(monkeypatch):
    monkeypatch.setattr(chat_post, "CHAT", {"gcp_project": "fallback-proj"})
    cap = _capture_gcloud_cmd(monkeypatch)
    chat_post._load_sa_key("SECRET", "override-proj")
    assert "--project=override-proj" in cap["cmd"]     # override wins over gcp_project
    assert "--secret=SECRET" in cap["cmd"]


def test_load_sa_key_falls_back_to_gcp_project(monkeypatch):
    monkeypatch.setattr(chat_post, "CHAT", {"gcp_project": "fallback-proj"})
    cap = _capture_gcloud_cmd(monkeypatch)
    chat_post._load_sa_key("SECRET")                   # no override -> gcp_project
    assert "--project=fallback-proj" in cap["cmd"]


def test_load_sa_key_override_works_without_gcp_project(monkeypatch):
    # gcp_project is now OPTIONAL when a per-secret override is supplied.
    monkeypatch.setattr(chat_post, "CHAT", {})
    cap = _capture_gcloud_cmd(monkeypatch)
    chat_post._load_sa_key("SECRET", "only-override")
    assert "--project=only-override" in cap["cmd"]


def test_load_sa_key_errors_when_no_project_anywhere(monkeypatch):
    monkeypatch.setattr(chat_post, "CHAT", {})

    def must_not_call(*a, **k):
        raise AssertionError("must not call gcloud when no project resolves")

    monkeypatch.setattr(chat_post.subprocess, "check_output", must_not_call)
    with pytest.raises(SystemExit):
        chat_post._load_sa_key("SECRET")


# --- call-site wiring: each token fn passes the RIGHT per-secret project ---
# Spy on _load_sa_key and stop before any google credential call, then assert the
# (secret, project) each token function requested.

class _Stop(Exception):
    pass


def _spy_load_sa_key(monkeypatch):
    rec = {}

    def spy(secret, project=None):
        rec["secret"] = secret
        rec["project"] = project
        raise _Stop()

    monkeypatch.setattr(chat_post, "_load_sa_key", spy)
    return rec


def test_bot_write_token_uses_bot_sa_project(monkeypatch):
    monkeypatch.setattr(chat_post, "CHAT",
                        {"bot_sa_secret": "BOT-KEY", "bot_sa_project": "bot-proj"})
    rec = _spy_load_sa_key(monkeypatch)
    with pytest.raises(_Stop):
        chat_post.bot_write_token()
    assert rec == {"secret": "BOT-KEY", "project": "bot-proj"}


def test_read_token_uses_admin_sa_project(monkeypatch):
    monkeypatch.setattr(chat_post, "CHAT",
                        {"admin_sa_secret": "ADMIN-KEY", "admin_sa_project": "admin-proj"})
    rec = _spy_load_sa_key(monkeypatch)
    with pytest.raises(_Stop):
        chat_post.read_token()
    assert rec == {"secret": "ADMIN-KEY", "project": "admin-proj"}


def test_self_write_token_uses_admin_sa_project(monkeypatch):
    monkeypatch.setattr(chat_post, "CHAT",
                        {"admin_sa_secret": "ADMIN-KEY", "admin_sa_project": "admin-proj"})
    rec = _spy_load_sa_key(monkeypatch)
    with pytest.raises(_Stop):
        chat_post.self_write_token()
    assert rec == {"secret": "ADMIN-KEY", "project": "admin-proj"}


def test_react_admin_dwd_uses_admin_sa_project(monkeypatch):
    monkeypatch.setattr(chat_post, "CHAT", {"admin_sa_project": "admin-proj"})
    rec = _spy_load_sa_key(monkeypatch)
    with pytest.raises(_Stop):
        chat_post.react_token({"source": "admin_dwd", "secret": "ADMIN-KEY", "subject": "p@x"})
    assert rec == {"secret": "ADMIN-KEY", "project": "admin-proj"}


def test_token_fn_falls_back_to_gcp_project_when_no_override(monkeypatch):
    # Backward compat: a config with only gcp_project (no per-secret projects) still
    # resolves - the call site passes None, and _load_sa_key then uses gcp_project.
    monkeypatch.setattr(chat_post, "CHAT",
                        {"bot_sa_secret": "BOT-KEY", "gcp_project": "shared-proj"})
    rec = _spy_load_sa_key(monkeypatch)
    with pytest.raises(_Stop):
        chat_post.bot_write_token()
    assert rec == {"secret": "BOT-KEY", "project": None}   # None -> _load_sa_key uses gcp_project


# --- list: 200-char truncation by default, whole text with --full ---

def _run_list(monkeypatch, capsys, text, full):
    import argparse
    monkeypatch.setattr(chat_post, "read_token", lambda: "TOK")
    monkeypatch.setattr(chat_post, "_http", lambda *a, **k: {"messages": [
        {"name": "spaces/S/messages/1", "createTime": "t", "text": text,
         "sender": {"name": "users/1"}, "thread": {"name": "spaces/S/threads/1"}}]})
    chat_post.cmd_list(argparse.Namespace(space="spaces/S", limit=5, full=full))
    return capsys.readouterr().out


def test_list_truncates_at_200_by_default(monkeypatch, capsys):
    out = _run_list(monkeypatch, capsys, "a" * 150 + "\n" + "b" * 150, full=False)
    assert out.rstrip("\n").endswith("a" * 150 + " / " + "b" * 47)
    assert "b" * 48 not in out


def test_list_full_prints_whole_message_on_one_line(monkeypatch, capsys):
    out = _run_list(monkeypatch, capsys, "a" * 150 + "\n" + "b" * 150, full=True)
    assert out.rstrip("\n").endswith("a" * 150 + " / " + "b" * 150)
    assert out.count("\n") == 1
