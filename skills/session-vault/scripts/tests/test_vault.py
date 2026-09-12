"""Unit tests for _vault.py config resolution."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import _vault  # noqa: E402


def test_project_falls_back_to_personal_project():
    r = _vault.resolve({"gcp": {"personal_project": "agent-alex"}})
    assert r["bq_project"] == "agent-alex"


def test_explicit_bq_project_overrides_personal_project():
    r = _vault.resolve(
        {"gcp": {"personal_project": "agent-alex"}, "logging": {"bq_project": "agent-shared"}}
    )
    assert r["bq_project"] == "agent-shared"


def test_dataset_and_table_defaults():
    r = _vault.resolve({"gcp": {"personal_project": "agent-alex"}})
    assert r["bq_dataset"] == "claude_memory_vault"
    assert r["messages_table"] == "claude_memory_vault.messages"
    assert r["heartbeat_table"] == "claude_memory_vault.session_heartbeat"


def test_custom_dataset_flows_into_tables():
    r = _vault.resolve(
        {"gcp": {"personal_project": "agent-alex"}, "logging": {"bq_dataset": "my_vault"}}
    )
    assert r["messages_table"] == "my_vault.messages"
    assert r["heartbeat_table"] == "my_vault.session_heartbeat"


def test_bucket_defaults_from_project():
    r = _vault.resolve({"gcp": {"personal_project": "agent-alex"}})
    assert r["gcs_backup_bucket"] == "agent-alex-claude-vault-backup"


def test_explicit_bucket_wins():
    r = _vault.resolve(
        {"gcp": {"personal_project": "agent-alex"}, "logging": {"gcs_backup_bucket": "my-bucket"}}
    )
    assert r["gcs_backup_bucket"] == "my-bucket"


def test_paths_are_expanded():
    r = _vault.resolve({})
    assert r["gcloud_config_dir"].startswith(os.path.expanduser("~"))
    assert "~" not in r["gcloud_config_dir"]
    assert "~" not in r["offset_state_dir"]


def test_flags_default_off():
    r = _vault.resolve({"gcp": {"personal_project": "agent-alex"}})
    assert r["enabled"] is False
    assert r["heartbeat_enabled"] is False
    assert r["backup_enabled"] is False


def test_flags_read_true():
    r = _vault.resolve(
        {
            "gcp": {"personal_project": "agent-alex"},
            "logging": {"enabled": True, "heartbeat_enabled": True, "backup_enabled": True},
        }
    )
    assert r["enabled"] is True
    assert r["heartbeat_enabled"] is True
    assert r["backup_enabled"] is True


def test_missing_keys_when_enabled_without_project():
    r = _vault.resolve({"logging": {"enabled": True}})
    miss = _vault.missing_keys(r)
    assert any("bq_project" in m for m in miss)


def test_no_missing_keys_when_project_present():
    r = _vault.resolve({"gcp": {"personal_project": "agent-alex"}, "logging": {"enabled": True}})
    assert _vault.missing_keys(r) == []


def test_sa_secret_default():
    r = _vault.resolve({})
    assert r["sa_secret_name"] == "local-session-sync-sa-key"


def test_machine_name_from_person():
    r = _vault.resolve({"person": {"machine_name": "alex-mbp"}})
    assert r["machine_name"] == "alex-mbp"


def test_empty_config_is_safe():
    r = _vault.resolve({})
    assert r["enabled"] is False
    assert r["bq_project"] == ""
    # No project -> no derived bucket.
    assert r["gcs_backup_bucket"] == ""


# --- config-path resolution (rename: itg.config.json new-then-old, env overrides) ---


def _claude_dir(tmp_path):
    d = tmp_path / ".claude"
    d.mkdir()
    return d


def test_config_path_prefers_new_file(monkeypatch, tmp_path):
    monkeypatch.delenv("ITG_CONFIG", raising=False)
    monkeypatch.delenv("ALLTEAM_CONFIG_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    d = _claude_dir(tmp_path)
    (d / "itg.config.json").write_text("{}")
    (d / "allteam-config.json").write_text("{}")
    assert _vault._config_path() == str(d / "itg.config.json")


def test_config_path_falls_back_to_old(monkeypatch, tmp_path):
    monkeypatch.delenv("ITG_CONFIG", raising=False)
    monkeypatch.delenv("ALLTEAM_CONFIG_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    d = _claude_dir(tmp_path)
    (d / "allteam-config.json").write_text("{}")
    assert _vault._config_path() == str(d / "allteam-config.json")


def test_itg_config_env_wins_over_new_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = _claude_dir(tmp_path)
    (d / "itg.config.json").write_text("{}")
    envp = tmp_path / "custom.json"
    envp.write_text("{}")
    monkeypatch.setenv("ITG_CONFIG", str(envp))
    monkeypatch.delenv("ALLTEAM_CONFIG_PATH", raising=False)
    assert _vault._config_path() == str(envp)


def test_legacy_env_wins_over_file_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = _claude_dir(tmp_path)
    (d / "itg.config.json").write_text("{}")
    monkeypatch.delenv("ITG_CONFIG", raising=False)
    legacy = tmp_path / "legacy.json"
    legacy.write_text("{}")
    monkeypatch.setenv("ALLTEAM_CONFIG_PATH", str(legacy))
    assert _vault._config_path() == str(legacy)


def test_itg_config_wins_over_legacy_env(monkeypatch, tmp_path):
    itg = tmp_path / "itg.json"
    itg.write_text("{}")
    legacy = tmp_path / "legacy.json"
    legacy.write_text("{}")
    monkeypatch.setenv("ITG_CONFIG", str(itg))
    monkeypatch.setenv("ALLTEAM_CONFIG_PATH", str(legacy))
    assert _vault._config_path() == str(itg)


def test_empty_env_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = _claude_dir(tmp_path)
    (d / "allteam-config.json").write_text("{}")
    monkeypatch.setenv("ITG_CONFIG", "")
    monkeypatch.setenv("ALLTEAM_CONFIG_PATH", "")
    assert _vault._config_path() == str(d / "allteam-config.json")


def test_load_config_reads_env_file(monkeypatch, tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"logging": {"enabled": true}}')
    monkeypatch.setenv("ITG_CONFIG", str(p))
    monkeypatch.delenv("ALLTEAM_CONFIG_PATH", raising=False)
    assert _vault.load_config().get("logging", {}).get("enabled") is True


def test_legacy_env_disables_logging_even_with_new_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = _claude_dir(tmp_path)
    (d / "itg.config.json").write_text('{"logging": {"enabled": true}}')
    legacy = tmp_path / "legacy.json"
    legacy.write_text('{"logging": {"enabled": false}}')
    monkeypatch.delenv("ITG_CONFIG", raising=False)
    monkeypatch.setenv("ALLTEAM_CONFIG_PATH", str(legacy))
    assert _vault.resolve()["enabled"] is False
