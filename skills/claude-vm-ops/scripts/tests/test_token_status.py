"""Tests for token_status.py. Runs the script as a subprocess against tmp_path fixtures."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "token_status.py"
NOW = 1_800_000_000_000
DAY = 86_400_000
FAKE = "sk-" + "ant-oat01-FAKEVALUE123"  # split so no secret scanner mistakes the fixture for a key


def run(tmp_path, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--home-root", str(tmp_path), "--now-ms", str(NOW), *args],
        capture_output=True, text=True)


def write_creds(tmp_path, account, oauth=None, raw=None):
    d = tmp_path / account / ".claude"
    d.mkdir(parents=True)
    f = d / ".credentials.json"
    f.write_text(raw if raw is not None else json.dumps({"claudeAiOauth": oauth}))


def good(**over):
    o = {"accessToken": FAKE, "refreshToken": FAKE + "R", "expiresAt": NOW + 3_600_000,
         "refreshTokenExpiresAt": NOW + 20 * DAY}
    o.update(over)
    return o


def verdict(r, account):
    for line in r.stdout.splitlines():
        if line.startswith(account + " "):
            return line.split()[1]
    raise AssertionError(f"no line for {account}: {r.stdout!r}")


def test_ok(tmp_path):
    write_creds(tmp_path, "a", good())
    r = run(tmp_path, "a")
    assert verdict(r, "a") == "OK" and r.returncode == 0
    assert "SUMMARY ok=1 due=0 expired=0 wiped=0 unknown=0" in r.stdout
    assert "access=yes refresh=yes" in r.stdout


def test_due_within_the_default_three_days(tmp_path):
    write_creds(tmp_path, "a", good(refreshTokenExpiresAt=NOW + DAY))
    r = run(tmp_path, "a")
    assert verdict(r, "a") == "DUE" and r.returncode == 1


def test_default_due_window_is_three_days_exactly(tmp_path):
    write_creds(tmp_path, "a", good(refreshTokenExpiresAt=NOW + 3 * DAY))
    assert verdict(run(tmp_path, "a"), "a") == "DUE"  # the boundary is DUE
    write_creds(tmp_path, "b", good(refreshTokenExpiresAt=NOW + 3 * DAY + 1))
    r = run(tmp_path, "b")
    assert verdict(r, "b") == "OK" and r.returncode == 0  # one millisecond past it is OK
    write_creds(tmp_path, "c", good(refreshTokenExpiresAt=NOW + 2 * DAY + DAY // 2))
    assert verdict(run(tmp_path, "c"), "c") == "DUE"  # 2.5 days: DUE now, was OK under a 2-day default


def test_due_days_option_changes_the_window(tmp_path):
    write_creds(tmp_path, "a", good(refreshTokenExpiresAt=NOW + 2 * DAY))
    assert verdict(run(tmp_path, "a"), "a") == "DUE"
    assert verdict(run(tmp_path, "--due-days", "1", "a"), "a") == "OK"
    assert verdict(run(tmp_path, "--due-days", "2", "a"), "a") == "DUE"
    assert verdict(run(tmp_path, "--due-days", "0", "a"), "a") == "OK"


def test_expired(tmp_path):
    write_creds(tmp_path, "a", good(refreshTokenExpiresAt=NOW))
    r = run(tmp_path, "a")
    assert verdict(r, "a") == "EXPIRED" and r.returncode == 1


def test_wiped(tmp_path):
    write_creds(tmp_path, "a", good(accessToken="", refreshToken="", expiresAt=0))
    r = run(tmp_path, "a")
    assert verdict(r, "a") == "WIPED" and r.returncode == 1
    assert "access=no refresh=no access_expires=none" in r.stdout


def test_unknown_invalid_json(tmp_path):
    write_creds(tmp_path, "a", raw="{not json " + FAKE)
    r = run(tmp_path, "a")
    assert verdict(r, "a") == "UNKNOWN" and r.returncode == 3
    assert "detail=JSONDecodeError" in r.stdout


def test_unknown_missing_refresh_expiry(tmp_path):
    o = good()
    del o["refreshTokenExpiresAt"]
    write_creds(tmp_path, "a", o)
    r = run(tmp_path, "a")
    assert verdict(r, "a") == "UNKNOWN" and r.returncode == 3


def test_unknown_bool_expires_at(tmp_path):
    write_creds(tmp_path, "a", good(expiresAt=True))
    r = run(tmp_path, "a")
    assert verdict(r, "a") == "UNKNOWN" and r.returncode == 3


def test_unknown_negative_and_wrong_shapes(tmp_path):
    write_creds(tmp_path, "neg", good(refreshTokenExpiresAt=-5))
    write_creds(tmp_path, "lst", raw="[]")
    write_creds(tmp_path, "nooauth", raw="{}")
    r = run(tmp_path, "neg", "lst", "nooauth")
    assert [verdict(r, a) for a in ("neg", "lst", "nooauth")] == ["UNKNOWN"] * 3
    assert r.returncode == 3


def test_unknown_missing_file(tmp_path):
    r = run(tmp_path, "ghost")
    assert verdict(r, "ghost") == "UNKNOWN" and r.returncode == 3
    assert "detail=file_missing" in r.stdout


def test_mixed_unknown_beats_wiped(tmp_path):
    write_creds(tmp_path, "ok", good())
    write_creds(tmp_path, "wiped", good(accessToken="", refreshToken="", expiresAt=0))
    r = run(tmp_path, "ok", "wiped", "ghost")
    assert r.returncode == 3
    assert [line.split()[0] for line in r.stdout.splitlines()[:3]] == ["ok", "wiped", "ghost"]
    assert "SUMMARY ok=1 due=0 expired=0 wiped=1 unknown=1" in r.stdout


def test_mixed_wiped_without_unknown_exits_1(tmp_path):
    write_creds(tmp_path, "ok", good())
    write_creds(tmp_path, "wiped", good(accessToken="", refreshToken="", expiresAt=0))
    r = run(tmp_path, "ok", "wiped")
    assert r.returncode == 1
    assert verdict(r, "ok") == "OK" and verdict(r, "wiped") == "WIPED"
    assert "SUMMARY ok=1 due=0 expired=0 wiped=1 unknown=0" in r.stdout


def test_token_value_never_printed(tmp_path):
    write_creds(tmp_path, "ok", good())
    write_creds(tmp_path, "bad", raw='{"claudeAiOauth": {"accessToken": "' + FAKE + '", oops}')
    write_creds(tmp_path, "due", good(refreshTokenExpiresAt=NOW + DAY))
    r = run(tmp_path, "ok", "bad", "due")
    # the script really ran: right verdicts, summary and exit code
    assert [verdict(r, a) for a in ("ok", "bad", "due")] == ["OK", "UNKNOWN", "DUE"]
    assert "SUMMARY ok=1 due=1 expired=0 wiped=0 unknown=1" in r.stdout
    assert r.returncode == 3
    assert FAKE not in r.stdout and FAKE not in r.stderr
    assert "sk-ant" not in r.stdout + r.stderr


def test_bad_account_names_exit_2(tmp_path):
    for bad in ("../x", "a/b", "..", ".", ""):
        r = run(tmp_path, bad)
        assert r.returncode == 2, bad
        assert "usage:" in r.stderr and "invalid account name" in r.stderr
        assert r.stdout == ""


def test_negative_due_days_exits_2(tmp_path):
    r = run(tmp_path, "--due-days", "-1", "a")
    assert r.returncode == 2
    assert "usage:" in r.stderr and "must be >= 0" in r.stderr


def test_expiry_out_of_range_is_unknown(tmp_path):
    write_creds(tmp_path, "a", good(refreshTokenExpiresAt=10**19))
    r = run(tmp_path, "a")
    assert verdict(r, "a") == "UNKNOWN" and r.returncode == 3
    assert "detail=expiry_out_of_range" in r.stdout
    assert " OK " not in r.stdout


def test_expiry_printed_with_seconds(tmp_path):
    write_creds(tmp_path, "a", good(expiresAt=1_800_000_123_000, refreshTokenExpiresAt=1_800_000_456_000))
    r = run(tmp_path, "a")
    assert "access_expires=2027-01-15 08:02:03 UTC" in r.stdout
    assert "refresh_expires=2027-01-15 08:07:36 UTC" in r.stdout


def test_unknown_expires_at_key_missing(tmp_path):
    o = good()
    del o["expiresAt"]
    write_creds(tmp_path, "a", o)
    r = run(tmp_path, "a")
    assert verdict(r, "a") == "UNKNOWN" and r.returncode == 3
    assert "detail=expiresAt_missing" in r.stdout


def test_expires_at_zero_with_tokens_is_wiped(tmp_path):
    write_creds(tmp_path, "a", good(expiresAt=0))
    r = run(tmp_path, "a")
    assert verdict(r, "a") == "WIPED" and r.returncode == 1
