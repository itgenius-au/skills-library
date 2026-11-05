"""End to end: run a real script on a machine with no setup, as a new user would.

No config, no ASANA_TOKEN: the script must stop with exit 2 and a message that
says what to set, before any network call."""
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def _run(tmp_path, *args, extra_env=None):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("ASANA_")}
    env["HOME"] = str(tmp_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(SCRIPTS / "post_comment.py"), *args],
                          capture_output=True, text=True, env=env, timeout=60)


def test_no_setup_exits_2_with_the_three_ways(tmp_path):
    r = _run(tmp_path, "1200000000000001", "--text", "hi")
    assert r.returncode == 2, r.stderr
    assert "no Asana token" in r.stderr
    assert "ASANA_TOKEN" in r.stderr and "token_secret" in r.stderr
    assert "Traceback" not in r.stderr


def test_bad_json_config_exits_2_naming_the_file(tmp_path):
    cfg = tmp_path / "broken.json"
    cfg.write_text("{not json")
    r = _run(tmp_path, "1200000000000001", "--text", "hi",
             extra_env={"ASANA_UPDATE_CONFIG": str(cfg), "ASANA_TOKEN": "x"})
    assert r.returncode == 2, r.stderr
    assert f"config at {cfg} is not a JSON object" in r.stderr
    assert "Traceback" not in r.stderr
