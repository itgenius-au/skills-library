"""Tests for scan_secrets.py: real throwaway git repos, the script run as a subprocess.

Every secret value here is invented and obviously fake (runs of FAKE, counting digits). Each is assembled
at runtime, so this file holds no literal secret pattern and passes its own scan.
"""
import re
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scan_secrets.py"

GOOGLE_KEY = "AI" + "za" + "FAKE" * 8 + "FAK"                      # 39 chars, shape of a Google API key
GITHUB_TOKEN = "gh" + "p_" + "FAKE" * 6 + "0123456789"
META_TOKEN = "EA" + "A" + "FAKE" * 5 + "FA"                        # letters only: no generic rule can report it
LETTERS_SECRET = "fakefakefake" + "fakefake"                        # letters only: reads as an identifier if unquoted
STRIPE_LIVE = "sk" + "_live_" + "FAKE" * 6                          # shape of a Stripe live secret key
STRIPE_RESTRICTED = "rk" + "_live_" + "FAKE" * 6
JWT = "ey" + "J" + "FAKEFAKEFAKE" + ".ey" + "J" + "FAKEFAKEFAKE" + ".FAKESIGNATURE"
BEARER = "Bearer " + "FAKE" * 6
GOOGLE_CLIENT_SECRET = "GOC" + "SPX-" + "FAKE" * 4
AWS_KEY_ID = "AK" + "IA" + "FAKE" * 4
SLACK_TOKEN = "xo" + "xb-" + "0123456789-FAKEFAKE"
PRIVATE_KEY_BLOCK = "-----BEGIN RSA PRIV" + "ATE KEY-----"
PASSWORD_VALUE = "NotARealPass" + "123"                             # a literal, not a code reference
# The coarse inline search an earlier wrap used instead of this scanner (a control: see the tests below).
OLD_COARSE_GREP = re.compile(r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}"
                             r"|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}|sk-[A-Za-z0-9_-]{20,}")


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def git(cwd, *args):
    r = run(["git", *args], cwd)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def scan(cwd, *args):
    return run([sys.executable, str(SCRIPT), *args], cwd)


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    git(d, "init", "-q", "-b", "main")
    git(d, "config", "user.email", "t@example.com")
    git(d, "config", "user.name", "t")
    git(d, "config", "core.autocrlf", "false")
    (d / "README.md").write_text("hello\n", encoding="utf-8")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "base")
    return d


def write_and_stage(d, name, text):
    p = d / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    git(d, "add", "-A")


def test_clean_change_exits_0(repo):
    write_and_stage(repo, "notes.md", "just words\nmore words\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout
    assert "CLEAN" in r.stdout


def test_staged_secret_exits_2_and_is_masked_with_line_number(repo):
    write_and_stage(repo, "config.py", "a = 1\nb = 2\nKEY = '" + GOOGLE_KEY + "'\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "config.py:3" in r.stdout
    assert "Google API key" in r.stdout
    assert len(GOOGLE_KEY) == 39
    assert GOOGLE_KEY[4:20] not in r.stdout     # never print the value
    assert GOOGLE_KEY[:4] in r.stdout           # masked form keeps the first 4 chars


def test_unpushed_commit_is_scanned_against_base(repo):
    base = git(repo, "rev-parse", "HEAD")
    write_and_stage(repo, "deploy.sh", "export TOKEN=" + GITHUB_TOKEN + "\n")
    git(repo, "commit", "-q", "-m", "wip")
    r = scan(repo, "--base", base)
    assert r.returncode == 2, r.stdout
    assert "GitHub token" in r.stdout


def test_secret_already_in_base_is_not_reported(repo):
    write_and_stage(repo, "old.py", "K = '" + GOOGLE_KEY + "'\n")
    git(repo, "commit", "-q", "-m", "old")
    write_and_stage(repo, "new.md", "fine\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout


def test_placeholder_value_is_not_reported(repo):
    # xxxx... has a digit, so only the placeholder filter (not the code-reference rule) skips it
    write_and_stage(repo, "README2.md", "access_token=xxxxxxxx1234\npassword: <your-password>\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout


def test_allow_marker_skips_the_line(repo):
    write_and_stage(repo, "fixture.py", "K = '" + GOOGLE_KEY + "'  # secret-scan: allow\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout


def test_example_file_is_not_reported(repo):
    write_and_stage(repo, "settings.example", "K=" + GOOGLE_KEY + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout


def test_added_dotenv_file_is_reported(repo):
    write_and_stage(repo, ".env", "DEBUG=1\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "Committed .env file" in r.stdout


def test_auto_base_uses_upstream_so_pushed_secrets_are_not_rescanned(repo, tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")
    git(repo, "checkout", "-q", "-b", "feat")
    write_and_stage(repo, "pushed.py", "K = '" + GOOGLE_KEY + "'\n")
    git(repo, "commit", "-q", "-m", "pushed on feat")
    git(repo, "push", "-q", "-u", "origin", "feat")   # upstream origin/feat is AHEAD of origin/main
    r = scan(repo)
    assert r.returncode == 0, r.stdout              # only the upstream excludes pushed.py
    write_and_stage(repo, "later.sh", "T=" + GITHUB_TOKEN + "\n")
    git(repo, "commit", "-q", "-m", "unpushed")
    r = scan(repo)
    assert r.returncode == 2, r.stdout
    assert "later.sh:1" in r.stdout and "pushed.py" not in r.stdout


def test_outside_a_git_repo_exits_1(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(tmp_path))
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=d, capture_output=True, text=True, env=env)
    assert r.returncode == 1


def test_non_ascii_file_name_is_still_scanned(repo):
    write_and_stage(repo, "caf\u00e9.py", "K = '" + GOOGLE_KEY + "'\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "caf\u00e9.py:1" in r.stdout


def test_mnemonic_prefix_config_does_not_hide_files(repo):
    git(repo, "config", "diff.mnemonicPrefix", "true")
    write_and_stage(repo, "conf.py", "K = '" + GOOGLE_KEY + "'\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout


def test_auto_base_with_no_remote_exits_1_not_clean(repo):
    write_and_stage(repo, "x.sh", "T=" + GITHUB_TOKEN + "\n")
    git(repo, "commit", "-q", "-m", "local only")
    r = scan(repo)                                  # no upstream, no origin: cannot scope the scan
    assert r.returncode == 1, r.stdout + r.stderr


def test_generic_assignment_from_code_is_not_reported(repo):
    code = ('password = request.form["pw"]\n'
            "client_secret=args.client_secret\n"
            "secret = get_secret(name)\n"
            "api_key=self.api_key\n"
            "In docs: `api_key=self.api_key`)\n")
    write_and_stage(repo, "app.py", code)
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout


def test_generic_assignment_of_a_literal_is_reported(repo):
    write_and_stage(repo, "settings.ini", "password = " + PASSWORD_VALUE + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "Generic secret assignment" in r.stdout


@pytest.mark.parametrize("template", [
    'client_secret = "{}"',
    "client_secret = '{}'",
    'CLIENT_SECRET\t=\t"{}"',
    '`client_secret = "{}"`',
    '"client_secret": "{}",',
    "{{'client_secret': '{}'}}",
    '`client_secret`: "{}"',
    '**client_secret**: "{}"',
    '{{\\"client_secret\\":\\"{}\\"}}',
    'access_token = fetch_token(client_secret="{}")',
])
def test_quoted_letters_only_literal_is_reported(repo, template):
    write_and_stage(repo, "settings.txt", template.format(LETTERS_SECRET) + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "Generic secret assignment" in r.stdout


def test_generic_finding_prints_no_part_of_the_value(repo):
    write_and_stage(repo, "settings.txt", 'client_secret = "' + LETTERS_SECRET + '"\n')
    r = scan(repo, "--base", "HEAD")
    finding = next(ln for ln in r.stdout.splitlines() if "settings.txt" in ln)
    assert "Generic secret assignment" in finding
    assert LETTERS_SECRET[:4] not in finding and not finding.endswith(LETTERS_SECRET[-2:])


def test_nested_literal_with_a_digit_is_reported(repo):
    write_and_stage(repo, "app.py", 'api_key = fetch(client_secret="' + LETTERS_SECRET + '1")\n')
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "Generic secret assignment" in r.stdout


@pytest.mark.parametrize("line", [
    'password = "password)"',  # secret-scan: allow (test fixture)
    'password = "password,"',  # secret-scan: allow (test fixture)
    'password = "password\\\\"',  # secret-scan: allow (test fixture)
    "password: 'password\\'",  # secret-scan: allow (test fixture)
    "password=\\password",  # secret-scan: allow (test fixture)
])
def test_quoted_value_with_punctuation_is_not_its_own_key(repo, line):
    write_and_stage(repo, "fields.py", line + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout


@pytest.fixture
def pushed_branch(repo, tmp_path):
    """`feat` is level with its upstream; main is on origin too."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")
    git(repo, "checkout", "-q", "-b", "feat")
    git(repo, "push", "-q", "-u", "origin", "feat")
    return repo


def test_a_value_added_then_removed_in_unpushed_commits_is_reported(pushed_branch):
    repo = pushed_branch
    write_and_stage(repo, "deploy.sh", "T=" + GITHUB_TOKEN + "\n")
    git(repo, "commit", "-q", "-m", "wip")
    write_and_stage(repo, "deploy.sh", "T=gone\n")
    git(repo, "commit", "-q", "-m", "wip")
    r = scan(repo)
    assert r.returncode == 2, r.stdout
    assert "GitHub token" in r.stdout


def test_an_explicit_base_reads_the_net_diff_of_a_squash(repo):
    base = git(repo, "rev-parse", "HEAD")
    write_and_stage(repo, "deploy.sh", "T=" + GITHUB_TOKEN + "\n")
    git(repo, "commit", "-q", "-m", "wip")
    write_and_stage(repo, "deploy.sh", "T=gone\n")
    git(repo, "commit", "-q", "-m", "wip")
    r = scan(repo, "--base", base)
    assert r.returncode == 0, r.stdout


def diverge_from_main(repo, main_file, main_text):
    """main gains a pushed commit and feat gains its own, so a merge makes a real merge commit."""
    git(repo, "checkout", "-q", "main")
    write_and_stage(repo, main_file, main_text)
    git(repo, "commit", "-q", "-m", "on main")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "feat")
    write_and_stage(repo, "feat.txt", "feature work\n")
    git(repo, "commit", "-q", "-m", "on feat")


def test_a_merge_of_published_main_is_not_rescanned(pushed_branch):
    repo = pushed_branch
    diverge_from_main(repo, "already-public.sh", "T=" + GITHUB_TOKEN + "\n")
    git(repo, "merge", "-q", "--no-edit", "main")
    r = scan(repo)
    assert r.returncode == 0, r.stdout


def test_a_value_added_only_in_a_merge_commit_is_reported(pushed_branch):
    repo = pushed_branch
    diverge_from_main(repo, "m.txt", "main\n")
    git(repo, "merge", "-q", "--no-commit", "--no-ff", "main")
    write_and_stage(repo, "evil.sh", "T=" + GITHUB_TOKEN + "\n")
    git(repo, "commit", "-q", "-m", "merge")
    r = scan(repo)
    assert r.returncode == 2, r.stdout
    assert "evil.sh" in r.stdout


def test_a_dotenv_added_then_deleted_in_unpushed_commits_is_reported(pushed_branch):
    repo = pushed_branch
    write_and_stage(repo, ".env", "DATABASE_URL=postgres://u@h/db\n")
    git(repo, "commit", "-q", "-m", "wip")
    (repo / ".env").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "wip")
    r = scan(repo)
    assert r.returncode == 2, r.stdout
    assert "Committed .env file" in r.stdout


def test_a_staged_dotenv_is_reported_with_no_unpushed_commit(pushed_branch):
    write_and_stage(pushed_branch, ".env", "DEBUG=1\n")
    r = scan(pushed_branch)
    assert r.returncode == 2, r.stdout
    assert "Committed .env file" in r.stdout


def test_a_dotenv_from_published_main_is_not_rescanned(pushed_branch):
    repo = pushed_branch
    diverge_from_main(repo, ".env", "DEBUG=1\n")
    git(repo, "merge", "-q", "--no-edit", "main")
    r = scan(repo)
    assert r.returncode == 0, r.stdout


def test_a_staged_value_is_reported_with_no_unpushed_commit(pushed_branch):
    write_and_stage(pushed_branch, "later.sh", "T=" + GITHUB_TOKEN + "\n")
    r = scan(pushed_branch)
    assert r.returncode == 2, r.stdout
    assert "later.sh:1" in r.stdout


def test_a_failed_git_read_is_not_clean(repo):
    r = scan(repo, "--base", "no-such-rev")
    assert r.returncode == 1, r.stdout + r.stderr


def test_added_line_that_looks_like_a_file_header_does_not_stop_the_scan(repo):
    write_and_stage(repo, "count.cpp", "++ attempts;\nclient_secret = \"" + LETTERS_SECRET + "\";\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "count.cpp:2" in r.stdout


def test_removed_line_that_looks_like_a_file_header_does_not_stop_the_scan(repo):
    write_and_stage(repo, "notes.sql", "-- old note\nkeep\n")
    git(repo, "commit", "-q", "-m", "notes")
    write_and_stage(repo, "notes.sql", 'client_secret = "' + LETTERS_SECRET + '"\nkeep\n')
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "notes.sql:1" in r.stdout


def test_a_replaced_line_does_not_hide_the_next_file(repo):
    write_and_stage(repo, "a.txt", "old\n")
    git(repo, "commit", "-q", "-m", "a")
    write_and_stage(repo, "a.txt", "new\n")
    write_and_stage(repo, "b.txt", 'client_secret = "' + LETTERS_SECRET + '"\n')
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "b.txt:1" in r.stdout


def test_inter_hunk_context_config_does_not_hide_the_next_file(repo):
    git(repo, "config", "diff.interHunkContext", "4")
    write_and_stage(repo, "a.txt", "1\n2\n3\n4\n5\n")
    git(repo, "commit", "-q", "-m", "a")
    write_and_stage(repo, "a.txt", "x\n2\n3\n4\nT=" + GITHUB_TOKEN + "\n")
    write_and_stage(repo, "z.txt", "T=" + GITHUB_TOKEN + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "a.txt:5" in r.stdout and "z.txt:1" in r.stdout


def test_a_form_feed_in_an_added_line_does_not_end_the_hunk_early(repo):
    write_and_stage(repo, "a.txt", "one\x0c+two\nthree\nclient_secret = \"" + LETTERS_SECRET + "\"\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "a.txt:3" in r.stdout


@pytest.mark.parametrize("path", [SCRIPT, Path(__file__)])
def test_the_scanner_and_its_tests_pass_their_own_scan(repo, path):
    write_and_stage(repo, "copy-" + path.name, path.read_text(encoding="utf-8"))
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("line", [
    'ACCESS_TOKEN = "access_token"',
    'ACCESS_TOKEN = "access-token"',
    'auth_token: "AUTH-TOKEN"',
    '"client_secret": "client_secret",',
    '`PASSWORD = "password"`',
    '{\\"ACCESS_TOKEN\\": \\"access_token\\"}',
])
def test_quoted_field_name_constant_is_not_reported(repo, line):
    write_and_stage(repo, "fields.py", line + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout


def test_quoted_value_that_is_another_keys_name_is_reported(repo):
    write_and_stage(repo, "fields.py", 'api_key = "access_token"\n')  # secret-scan: allow (test fixture)
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "Generic secret assignment" in r.stdout


@pytest.mark.parametrize("template", [
    "{}",
    "fb_token = {}",
    "https://graph.facebook.com/me?fields=id&access_token={}",
])
def test_meta_token_is_reported_and_masked(repo, template):
    write_and_stage(repo, "notes.md", template.format(META_TOKEN) + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "Meta access token" in r.stdout
    assert META_TOKEN[4:20] not in r.stdout


def test_meta_shape_inside_a_longer_word_is_not_reported(repo):
    write_and_stage(repo, "notes.md", "x" + META_TOKEN + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout


def test_meta_placeholder_is_not_reported(repo):
    write_and_stage(repo, "notes.md", "EA" + "A" + "x" * 24 + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout


# --- the three misses of the coarse inline search, each with a positive control ------------------------------

def test_control_the_scanner_finds_a_planted_value_it_is_judged_on(repo):
    """Positive control: a planted value must be found, or every clean result below proves nothing."""
    write_and_stage(repo, "planted.py", "K = '" + GOOGLE_KEY + "'\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "planted.py:1" in r.stdout


def test_a_value_added_then_removed_is_reported_though_the_net_diff_is_clean(pushed_branch):
    repo = pushed_branch
    write_and_stage(repo, "deploy.sh", "T=" + GITHUB_TOKEN + "\n")
    git(repo, "commit", "-q", "-m", "wip")
    write_and_stage(repo, "deploy.sh", "T=gone\n")
    git(repo, "commit", "-q", "-m", "wip")
    # Control: the net diff against the upstream, which is all the old inline search read, holds no value.
    net = git(repo, "diff", "origin/feat...HEAD")
    assert GITHUB_TOKEN not in net and not OLD_COARSE_GREP.search(net)
    # The push still publishes the first commit, so the scan must stop it.
    r = scan(repo)
    assert r.returncode == 2, r.stdout
    assert "GitHub token" in r.stdout
    assert GITHUB_TOKEN[4:24] not in r.stdout


@pytest.mark.parametrize("key", [STRIPE_LIVE, STRIPE_RESTRICTED])
def test_a_stripe_shape_key_is_reported_and_masked(repo, key):
    # Control: the old inline search needed a hyphen after "sk", which this shape does not have.
    assert not OLD_COARSE_GREP.search(key)
    write_and_stage(repo, "billing.py", "STRIPE = '" + key + "'\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "Stripe live key" in r.stdout
    assert key[6:18] not in r.stdout


@pytest.mark.parametrize("prose", [
    "see disk-cleanup-script-for-vm for the steps",
    "risk-assessment-of-the-new-deployment-plan",
    "the task-runner-for-nightly-batch-jobs",
])
def test_hyphenated_prose_is_not_reported(repo, prose):
    # Control: the old inline search read "sk-" inside "disk-" and stopped the wrap on this text.
    assert OLD_COARSE_GREP.search(prose)
    write_and_stage(repo, "notes.md", prose + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout


def test_a_real_openai_shape_key_is_still_reported(repo):
    key = "sk" + "-" + "FAKE" * 10
    write_and_stage(repo, "keys.txt", "K=" + key + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "OpenAI API key" in r.stdout


# --- coverage of each shape the wrap relies on -----------------------------------------------------------

@pytest.mark.parametrize("value, rule", [
    (JWT, "JWT"),
    (BEARER, "Bearer token"),
    (GOOGLE_CLIENT_SECRET, "Google OAuth client secret"),
    (AWS_KEY_ID, "AWS access key id"),
    (SLACK_TOKEN, "Slack token"),
    (PRIVATE_KEY_BLOCK, "Private key block"),
    (STRIPE_LIVE, "Stripe live key"),
    (GOOGLE_KEY, "Google API key"),
    (GITHUB_TOKEN, "GitHub token"),
])
def test_each_credential_shape_is_reported_in_an_unpushed_commit(pushed_branch, value, rule):
    repo = pushed_branch
    write_and_stage(repo, "conf.txt", "line one\nvalue: " + value + "\n")
    git(repo, "commit", "-q", "-m", "wip")
    r = scan(repo)
    assert r.returncode == 2, r.stdout
    assert rule in r.stdout
    assert "conf.txt:2" in r.stdout


def test_a_password_assignment_is_reported_and_prints_none_of_the_value(repo):
    write_and_stage(repo, "app.yml", "database:\n  password: " + PASSWORD_VALUE + "\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "Generic secret assignment" in r.stdout
    assert PASSWORD_VALUE[:4] not in r.stdout


def test_an_env_file_is_reported_but_an_env_example_is_not(repo):
    write_and_stage(repo, ".env.example", "DEBUG=1\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 0, r.stdout
    write_and_stage(repo, "sub/.env.production", "DEBUG=0\n")
    r = scan(repo, "--base", "HEAD")
    assert r.returncode == 2, r.stdout
    assert "Committed .env file" in r.stdout
    assert "sub/.env.production" in r.stdout
