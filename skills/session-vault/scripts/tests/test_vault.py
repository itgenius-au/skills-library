"""Unit tests for _vault.py config resolution (flat, standalone config schema)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import _vault  # noqa: E402


def test_bq_project_read_directly():
    r = _vault.resolve({"bq_project": "agent-alex"})
    assert r["bq_project"] == "agent-alex"


def test_dataset_and_table_defaults():
    r = _vault.resolve({"bq_project": "agent-alex"})
    assert r["bq_dataset"] == "claude_memory_vault"
    assert r["messages_table"] == "claude_memory_vault.messages"
    assert r["heartbeat_table"] == "claude_memory_vault.session_heartbeat"


def test_custom_dataset_flows_into_tables():
    r = _vault.resolve({"bq_project": "agent-alex", "bq_dataset": "my_vault"})
    assert r["messages_table"] == "my_vault.messages"
    assert r["heartbeat_table"] == "my_vault.session_heartbeat"


def test_bucket_defaults_from_project():
    r = _vault.resolve({"bq_project": "agent-alex"})
    assert r["gcs_backup_bucket"] == "agent-alex-claude-vault-backup"


def test_explicit_bucket_wins():
    r = _vault.resolve({"bq_project": "agent-alex", "gcs_backup_bucket": "my-bucket"})
    assert r["gcs_backup_bucket"] == "my-bucket"


def test_paths_are_expanded():
    r = _vault.resolve({})
    assert r["gcloud_config_dir"].startswith(os.path.expanduser("~"))
    assert "~" not in r["gcloud_config_dir"]
    assert "~" not in r["offset_state_dir"]


def test_flags_default_off():
    r = _vault.resolve({"bq_project": "agent-alex"})
    assert r["enabled"] is False
    assert r["heartbeat_enabled"] is False
    assert r["backup_enabled"] is False


def test_flags_read_true():
    r = _vault.resolve(
        {
            "bq_project": "agent-alex",
            "enabled": True,
            "heartbeat_enabled": True,
            "backup_enabled": True,
        }
    )
    assert r["enabled"] is True
    assert r["heartbeat_enabled"] is True
    assert r["backup_enabled"] is True


def test_missing_keys_when_enabled_without_project():
    r = _vault.resolve({"enabled": True})
    miss = _vault.missing_keys(r)
    assert any("bq_project" in m for m in miss)


def test_no_missing_keys_when_project_present():
    r = _vault.resolve({"bq_project": "agent-alex", "enabled": True})
    assert _vault.missing_keys(r) == []


def test_sa_secret_default():
    r = _vault.resolve({})
    assert r["sa_secret_name"] == "local-session-sync-sa-key"


def test_machine_name_from_flat_key():
    r = _vault.resolve({"machine_name": "alex-mbp"})
    assert r["machine_name"] == "alex-mbp"


def test_empty_config_is_safe():
    r = _vault.resolve({})
    assert r["enabled"] is False
    assert r["bq_project"] == ""
    # No project -> no derived bucket.
    assert r["gcs_backup_bucket"] == ""


def test_flat_config_resolves_to_expected_vault_shell_env():
    """A fully-populated flat config (the shape in templates/session-vault.config.example.json,
    with every default overridden) must resolve to exactly the expected VAULT_* shell exports.
    This guards the public contract every downstream script (bash hooks, syncers, setup) relies
    on: they only ever read VAULT_* env vars, never the config file's keys directly."""
    flat = {
        "enabled": True,
        "bq_project": "my-gcp-project",
        "bq_dataset": "claude_memory_vault",
        "heartbeat_enabled": True,
        "backup_enabled": True,
        "gcs_backup_bucket": "my-custom-bucket",
        "sa_secret_name": "local-session-sync-sa-key",
        "gcloud_config_dir": "~/.config/gcloud-vault",
        "offset_state_dir": "~/.claude/hooks/.offsets",
        "machine_name": "alex-mbp",
    }
    r = _vault.resolve(flat)
    shell_env = _vault._shell_env(r)

    expected_home = os.path.expanduser("~")
    assert r == {
        "enabled": True,
        "heartbeat_enabled": True,
        "backup_enabled": True,
        "bq_project": "my-gcp-project",
        "bq_dataset": "claude_memory_vault",
        "messages_table": "claude_memory_vault.messages",
        "heartbeat_table": "claude_memory_vault.session_heartbeat",
        "gcloud_config_dir": expected_home + "/.config/gcloud-vault",
        "offset_state_dir": expected_home + "/.claude/hooks/.offsets",
        "sa_secret_name": "local-session-sync-sa-key",
        "gcs_backup_bucket": "my-custom-bucket",
        "machine_name": "alex-mbp",
    }
    for line in [
        "export VAULT_ENABLED=1",
        "export VAULT_HEARTBEAT_ENABLED=1",
        "export VAULT_BACKUP_ENABLED=1",
        "export VAULT_BQ_PROJECT=my-gcp-project",
        "export VAULT_BQ_DATASET=claude_memory_vault",
        "export VAULT_MESSAGES_TABLE=claude_memory_vault.messages",
        "export VAULT_HEARTBEAT_TABLE=claude_memory_vault.session_heartbeat",
        "export VAULT_GCLOUD_CONFIG=" + expected_home + "/.config/gcloud-vault",
        "export VAULT_OFFSET_DIR=" + expected_home + "/.claude/hooks/.offsets",
        "export VAULT_SA_SECRET=local-session-sync-sa-key",
        "export VAULT_GCS_BUCKET=my-custom-bucket",
        "export VAULT_MACHINE_NAME=alex-mbp",
    ]:
        assert line in shell_env, "missing/incorrect shell export: %s" % line


# --- config-path resolution (env override vs. default) ---


def _claude_dir(tmp_path):
    d = tmp_path / ".claude"
    d.mkdir()
    return d


def test_config_path_defaults_to_home_claude_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("SESSION_VAULT_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert _vault._config_path() == str(tmp_path / ".claude" / "session-vault.config.json")


def test_env_override_wins_over_default(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _claude_dir(tmp_path)
    envp = tmp_path / "custom.json"
    envp.write_text("{}")
    monkeypatch.setenv("SESSION_VAULT_CONFIG", str(envp))
    assert _vault._config_path() == str(envp)


def test_empty_env_override_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SESSION_VAULT_CONFIG", "")
    assert _vault._config_path() == str(tmp_path / ".claude" / "session-vault.config.json")


def test_load_config_reads_env_file(monkeypatch, tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"enabled": true, "bq_project": "agent-alex"}')
    monkeypatch.setenv("SESSION_VAULT_CONFIG", str(p))
    cfg = _vault.load_config()
    assert cfg.get("enabled") is True
    assert cfg.get("bq_project") == "agent-alex"


def test_missing_config_file_resolves_safely(monkeypatch, tmp_path):
    monkeypatch.setenv("SESSION_VAULT_CONFIG", str(tmp_path / "does-not-exist.json"))
    r = _vault.resolve()
    assert r["enabled"] is False
    assert r["bq_project"] == ""
