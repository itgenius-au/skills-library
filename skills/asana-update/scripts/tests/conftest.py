import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import _asana  # noqa: E402

TEST_WORKSPACE = "1200000000000000"


@pytest.fixture(autouse=True)
def isolate_from_real_config(monkeypatch):
    """Isolate tests from whatever a developer's real
    ~/.claude/asana-update.config.json holds. A test that needs a value set
    overrides it with monkeypatch.setattr(_asana, ...)."""
    monkeypatch.setattr(_asana, "CONFIG_STATUS", "ok")
    monkeypatch.setattr(_asana, "WORKSPACE", TEST_WORKSPACE)
    monkeypatch.setattr(_asana, "GCP_PROJECT", "")
    monkeypatch.setattr(_asana, "TOKEN_SECRET", "")
    monkeypatch.setattr(_asana, "PERSONAL_TOKEN_SECRET", "")
    monkeypatch.setattr(_asana, "GCLOUD_ACCOUNT", "")
    monkeypatch.setattr(_asana, "MY_USER_GID", "")
    monkeypatch.setattr(_asana, "AGENT_USER_GIDS", [])
    monkeypatch.setattr(_asana, "DEFAULT_SECTIONS", {})


@pytest.fixture(autouse=True)
def force_person_unset(monkeypatch):
    """Isolate tests from the developer's real user_email / user_name and from
    author lines cached by an earlier test. With user_gid and user_email both
    unset, author_line() makes no lookup and adds no line."""
    monkeypatch.setattr(_asana, "MY_EMAIL", "")
    monkeypatch.setattr(_asana, "MY_NAME", "")
    monkeypatch.setattr(_asana, "_AUTHOR_CACHE", {})
    monkeypatch.setattr(_asana, "_EXPLICIT_TOKENS", set())


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """No test may reach the real Asana API. A call that a test did not fake
    fails here, loudly, instead of going out with a fake token."""
    import urllib.request

    def blocked(*a, **k):
        raise AssertionError("real network call in a test: fake _asana.request instead")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)


@pytest.fixture(autouse=True)
def bare_gcloud_name(monkeypatch):
    """The code resolves gcloud with shutil.which (gcloud.cmd on Windows). These tests
    assert the bare command name, so hide any gcloud on PATH from them."""
    import shutil

    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name, *a, **k: None if name == "gcloud" else real_which(name, *a, **k)
    )
