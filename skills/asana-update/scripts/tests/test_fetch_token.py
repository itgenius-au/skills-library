"""Token resolution order: flags, then config secret, then ASANA_TOKEN, then exit 2."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import _asana


@pytest.fixture(autouse=True)
def clear_token_cache():
    _asana._TOKEN_CACHE.clear()


def mock_environment(monkeypatch, **values):
    monkeypatch.setattr(_asana.os, "environ", values)


def mock_gcloud(monkeypatch, values):
    def run(command, **kwargs):
        project = next(arg.removeprefix("--project=") for arg in command if arg.startswith("--project="))
        secret = next(arg.removeprefix("--secret=") for arg in command if arg.startswith("--secret="))
        return SimpleNamespace(stdout=values[(project, secret)] + "\n")

    subprocess_run = Mock(side_effect=run)
    monkeypatch.setattr(_asana.subprocess, "run", subprocess_run)
    return subprocess_run


def expected_gcloud_call(project, secret):
    return (
        ["gcloud", "secrets", "versions", "access", "latest",
         f"--secret={secret}", f"--project={project}"],
    )


def assert_one_gcloud_read(subprocess_run, project, secret):
    subprocess_run.assert_called_once_with(
        *expected_gcloud_call(project, secret),
        capture_output=True, text=True, check=True,
    )


# --- 1. flags win over everything -----------------------------------------------

def test_flag_secret_and_project_beat_config_and_env(monkeypatch):
    monkeypatch.setattr(_asana, "TOKEN_SECRET", "config-secret")
    monkeypatch.setattr(_asana, "GCP_PROJECT", "config-project")
    mock_environment(monkeypatch, ASANA_TOKEN="ambient-token")
    run = mock_gcloud(monkeypatch, {("flag-project", "flag-secret"): "flag-token"})

    assert _asana.fetch_token(secret_name="flag-secret", project="flag-project") == "flag-token"
    assert_one_gcloud_read(run, "flag-project", "flag-secret")


def test_flag_secret_uses_config_project(monkeypatch):
    monkeypatch.setattr(_asana, "GCP_PROJECT", "config-project")
    mock_environment(monkeypatch, ASANA_TOKEN="ambient-token")
    run = mock_gcloud(monkeypatch, {("config-project", "flag-secret"): "sm-token"})

    assert _asana.fetch_token(secret_name="flag-secret") == "sm-token"
    assert_one_gcloud_read(run, "config-project", "flag-secret")


def test_flag_secret_without_any_project_exits_2(monkeypatch, capsys):
    mock_environment(monkeypatch, ASANA_TOKEN="ambient-token")
    with pytest.raises(SystemExit) as exc:
        _asana.fetch_token(secret_name="flag-secret")
    assert exc.value.code == 2
    assert "--token-project" in capsys.readouterr().err


def test_flag_token_is_marked_explicit(monkeypatch):
    mock_environment(monkeypatch)
    mock_gcloud(monkeypatch, {("p", "s"): "tok"})
    _asana.fetch_token(secret_name="s", project="p")
    assert "tok" in _asana._EXPLICIT_TOKENS


# --- 2. config secret --------------------------------------------------------------

def test_config_secret_beats_ambient_token(monkeypatch):
    monkeypatch.setattr(_asana, "TOKEN_SECRET", "config-secret")
    monkeypatch.setattr(_asana, "GCP_PROJECT", "config-project")
    mock_environment(monkeypatch, ASANA_TOKEN="ambient-token")
    run = mock_gcloud(monkeypatch, {("config-project", "config-secret"): "service-token"})

    assert _asana.fetch_token() == "service-token"
    assert_one_gcloud_read(run, "config-project", "config-secret")


def test_config_secret_without_project_and_no_env_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(_asana, "TOKEN_SECRET", "config-secret")
    mock_environment(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _asana.fetch_token()
    assert exc.value.code == 2
    assert "gcp_project" in capsys.readouterr().err


# --- 3. ASANA_TOKEN ------------------------------------------------------------------

def test_ambient_token_when_nothing_configured(monkeypatch):
    mock_environment(monkeypatch, ASANA_TOKEN="ambient-token")
    run = Mock()
    monkeypatch.setattr(_asana.subprocess, "run", run)

    assert _asana.fetch_token() == "ambient-token"
    run.assert_not_called()
    assert "ambient-token" in _asana._EXPLICIT_TOKENS


# --- 4. nothing: friendly exit 2 ---------------------------------------------------

def test_nothing_set_exits_2_naming_all_three_ways(monkeypatch, capsys):
    mock_environment(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _asana.fetch_token()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--token-secret" in err and "token_secret" in err and "ASANA_TOKEN" in err
    assert "no Asana token" in str(exc.value)


# --- personal (time entries) ----------------------------------------------------------

def test_personal_uses_config_personal_secret(monkeypatch):
    monkeypatch.setattr(_asana, "PERSONAL_TOKEN_SECRET", "personal-secret")
    monkeypatch.setattr(_asana, "TOKEN_SECRET", "config-secret")
    monkeypatch.setattr(_asana, "GCP_PROJECT", "config-project")
    mock_environment(monkeypatch)
    run = mock_gcloud(monkeypatch, {("config-project", "personal-secret"): "personal-token"})

    assert _asana.fetch_token(personal=True) == "personal-token"
    assert_one_gcloud_read(run, "config-project", "personal-secret")


def test_personal_uses_ambient_personal_token(monkeypatch):
    monkeypatch.setattr(_asana, "TOKEN_SECRET", "config-secret")
    monkeypatch.setattr(_asana, "GCP_PROJECT", "config-project")
    mock_environment(monkeypatch, ASANA_PERSONAL_TOKEN="my-pat")
    run = Mock()
    monkeypatch.setattr(_asana.subprocess, "run", run)

    assert _asana.fetch_token(personal=True) == "my-pat"
    run.assert_not_called()


def test_personal_falls_back_to_the_normal_token(monkeypatch):
    """With NO personal secret configured at all, time entries use the normal token."""
    mock_environment(monkeypatch, ASANA_TOKEN="ambient-token")
    assert _asana.fetch_token(personal=True) == "ambient-token"


def test_personal_secret_without_project_exits_2_not_falls_back(monkeypatch, capsys):
    """A personal secret that cannot be read must not fall through to another
    login: the time entry would carry the wrong author for good."""
    monkeypatch.setattr(_asana, "PERSONAL_TOKEN_SECRET", "personal-secret")
    mock_environment(monkeypatch, ASANA_TOKEN="ambient-token")
    with pytest.raises(SystemExit) as exc:
        _asana.fetch_token(personal=True)
    assert exc.value.code == 2
    assert "personal_token_secret is set but gcp_project is not" in capsys.readouterr().err


# --- config file status ------------------------------------------------------------------

def test_invalid_config_exits_2_naming_the_file(monkeypatch, capsys):
    monkeypatch.setattr(_asana, "CONFIG_STATUS", "invalid")
    mock_environment(monkeypatch, ASANA_TOKEN="ambient-token")
    with pytest.raises(SystemExit) as exc:
        _asana.fetch_token()
    assert exc.value.code == 2
    assert f"config at {_asana.CONFIG_PATH} is not a JSON object" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        _asana.require_workspace()


@pytest.mark.parametrize(("content", "status"), [
    ("{not json", "invalid"),
    ("[1, 2]", "invalid"),
    ('{"workspace_gid": "1200000000000001"}', "ok"),
])
def test_load_config_sets_the_status(tmp_path, monkeypatch, content, status):
    path = tmp_path / "asana-update.config.json"
    path.write_text(content)
    monkeypatch.setattr(_asana, "CONFIG_PATH", str(path))
    monkeypatch.setattr(_asana, "CONFIG_STATUS", "missing")
    data = _asana.load_config()
    assert _asana.CONFIG_STATUS == status
    assert data == ({"workspace_gid": "1200000000000001"} if status == "ok" else {})


def test_missing_config_is_missing_not_invalid(tmp_path, monkeypatch):
    monkeypatch.setattr(_asana, "CONFIG_PATH", str(tmp_path / "absent.json"))
    assert _asana.load_config() == {}
    assert _asana.CONFIG_STATUS == "missing"


# --- gcloud failures ----------------------------------------------------------------------

def test_missing_gcloud_exits_2_naming_secret_and_project(monkeypatch, capsys):
    monkeypatch.setattr(_asana, "TOKEN_SECRET", "config-secret")
    monkeypatch.setattr(_asana, "GCP_PROJECT", "config-project")
    mock_environment(monkeypatch)

    def no_gcloud(*a, **k):
        raise FileNotFoundError("gcloud")

    monkeypatch.setattr(_asana.subprocess, "run", no_gcloud)
    with pytest.raises(SystemExit) as exc:
        _asana.fetch_token()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "gcloud not found" in err
    assert "'config-secret'" in err and "'config-project'" in err


def test_gcloud_error_names_secret_and_project_never_the_value(monkeypatch):
    import subprocess

    monkeypatch.setattr(_asana, "TOKEN_SECRET", "config-secret")
    monkeypatch.setattr(_asana, "GCP_PROJECT", "config-project")
    mock_environment(monkeypatch)

    def denied(cmd, **k):
        raise subprocess.CalledProcessError(1, cmd, output="SECRET-VALUE", stderr="PERMISSION_DENIED")

    monkeypatch.setattr(_asana.subprocess, "run", denied)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        _asana.fetch_token()
    assert "'config-secret'" in exc.value.stderr and "'config-project'" in exc.value.stderr
    assert "PERMISSION_DENIED" in exc.value.stderr
    assert exc.value.output is None and "SECRET-VALUE" not in str(exc.value)


# --- cache and gcloud account ----------------------------------------------------------

def test_cache_is_keyed_by_project_and_secret(monkeypatch):
    mock_environment(monkeypatch)
    run = mock_gcloud(monkeypatch, {
        ("project-one", "shared-secret"): "first-token",
        ("project-two", "shared-secret"): "second-token",
    })

    assert _asana.fetch_token(secret_name="shared-secret", project="project-one") == "first-token"
    assert _asana.fetch_token(secret_name="shared-secret", project="project-one") == "first-token"
    assert _asana.fetch_token(secret_name="shared-secret", project="project-two") == "second-token"
    assert run.call_count == 2


def test_gcloud_account_set_adds_account_flag(monkeypatch):
    monkeypatch.setattr(_asana, "TOKEN_SECRET", "config-secret")
    monkeypatch.setattr(_asana, "GCP_PROJECT", "config-project")
    monkeypatch.setattr(_asana, "GCLOUD_ACCOUNT", "pinned@example.org")
    mock_environment(monkeypatch)
    run = mock_gcloud(monkeypatch, {("config-project", "config-secret"): "service-token"})

    assert _asana.fetch_token() == "service-token"
    assert run.call_args.args[0] == [
        "gcloud", "secrets", "versions", "access", "latest",
        "--secret=config-secret", "--project=config-project", "--account=pinned@example.org",
    ]


# --- token_request ------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("secret", "project", "expected"),
    [
        (None, None, {}),
        ("s", None, {"secret_name": "s"}),
        (" s ", " p ", {"secret_name": "s", "project": "p"}),
    ],
)
def test_token_request_maps_flags(secret, project, expected):
    args = SimpleNamespace(token_secret=secret, token_project=project)
    assert _asana.token_request(args) == expected


@pytest.mark.parametrize(
    ("secret", "project", "message"),
    [
        ("", None, "--token-secret is empty"),
        ("s", " ", "--token-project is empty"),
        (None, "p", "--token-project needs --token-secret"),
    ],
)
def test_token_request_refuses_bad_combinations(secret, project, message):
    args = SimpleNamespace(token_secret=secret, token_project=project)
    with pytest.raises(SystemExit) as exc:
        _asana.token_request(args)
    assert message in str(exc.value)


def test_token_project_alone_uses_the_config_secret(monkeypatch):
    monkeypatch.setattr(_asana, "TOKEN_SECRET", "config-secret")
    mock_environment(monkeypatch)
    run = mock_gcloud(monkeypatch, {("other-project", "config-secret"): "tok"})
    kwargs = _asana.token_request(SimpleNamespace(token_secret=None, token_project="other-project"))
    assert kwargs == {"project": "other-project"}
    assert _asana.fetch_token(**kwargs) == "tok"
    assert_one_gcloud_read(run, "other-project", "config-secret")
