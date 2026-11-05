"""Config-ingestion tests: load a FRESH copy of _asana.py against a real config
file (never by patching the module values), so a bug in the module-level
parsing itself is caught."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "_asana.py"
TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "asana-update.config.example.json"


def load_fresh_asana(tmp_path, monkeypatch, config, raw=None):
    """Write `config` to a temp file named by ASANA_UPDATE_CONFIG, then exec a
    brand new copy of _asana.py against it."""
    path = tmp_path / "asana-update.config.json"
    path.write_text(raw if raw is not None else json.dumps(config))
    monkeypatch.setenv("ASANA_UPDATE_CONFIG", str(path))
    spec = importlib.util.spec_from_file_location("_asana_fresh", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("gcloud_account", "expected"),
    [
        ("pinned@example.org", "pinned@example.org"),
        ("  pinned@example.org  ", "pinned@example.org"),
        ("", ""),
        (123, ""),
        (True, ""),
        ([], ""),
        (["pinned@example.org"], ""),
        ({}, ""),
        (None, ""),
    ],
)
def test_gcloud_account_type_rules(tmp_path, monkeypatch, gcloud_account, expected):
    module = load_fresh_asana(tmp_path, monkeypatch, {"gcloud_account": gcloud_account})
    assert module.GCLOUD_ACCOUNT == expected


def test_flat_keys_are_read(tmp_path, monkeypatch):
    module = load_fresh_asana(tmp_path, monkeypatch, {
        "workspace_gid": "1200000000000000",
        "user_gid": "1200000000000001",
        "user_name": "Jon Tester",
        "user_email": "jon@example.org",
        "token_secret": "asana-token",
        "personal_token_secret": "asana-pat",
        "gcp_project": "my-project",
        "agent_user_gids": ["1200000000000009", 1200000000000008],
        "author_label": "Agent",
        "default_sections": {"1200000000000100": "1200000000000101"},
    })
    assert module.WORKSPACE == "1200000000000000"
    assert module.MY_USER_GID == "1200000000000001"
    assert module.MY_NAME == "Jon Tester"
    assert module.MY_EMAIL == "jon@example.org"
    assert module.TOKEN_SECRET == "asana-token"
    assert module.PERSONAL_TOKEN_SECRET == "asana-pat"
    assert module.GCP_PROJECT == "my-project"
    assert module.AGENT_USER_GIDS == ["1200000000000009", "1200000000000008"]
    assert module.AUTHOR_LABEL == "Agent"
    assert module.DEFAULT_SECTIONS == {"1200000000000100": "1200000000000101"}


def test_the_template_counts_as_unset(tmp_path, monkeypatch):
    """A copied but unfilled template must not look like a real setup."""
    module = load_fresh_asana(tmp_path, monkeypatch, None, raw=TEMPLATE_PATH.read_text())
    assert module.WORKSPACE == ""
    assert module.MY_USER_GID == ""
    assert module.MY_NAME == ""
    assert module.MY_EMAIL == ""
    assert module.TOKEN_SECRET == ""
    assert module.GCP_PROJECT == ""
    assert module.AUTHOR_LABEL == "Claude"


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", "null", '"text"'])
def test_bad_or_missing_config_imports_cleanly(tmp_path, monkeypatch, raw):
    module = load_fresh_asana(tmp_path, monkeypatch, None, raw=raw)
    assert module.CONFIG == {}
    assert module.WORKSPACE == ""
    assert module.GCLOUD_ACCOUNT == ""


def test_no_config_file_at_all(tmp_path, monkeypatch):
    monkeypatch.setenv("ASANA_UPDATE_CONFIG", str(tmp_path / "missing.json"))
    spec = importlib.util.spec_from_file_location("_asana_fresh", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.CONFIG == {}
    with pytest.raises(SystemExit) as exc:
        module.require_workspace()
    assert exc.value.code == 2
