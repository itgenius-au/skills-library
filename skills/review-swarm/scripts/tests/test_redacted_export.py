"""Tests for redacted_export.py: a git-free, redacted review copy plus a redacted diff."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "redacted_export.py"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=GIT_ENV, check=True
    )
    return result.stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    """Base commit is clean; head commit adds a fixture with a customer name. Returns (repo, base, head)."""
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", str(work)], check=True, env=GIT_ENV)
    (work / "app.py").write_text("print('hello')\n", encoding="utf-8")
    git(work, "add", "app.py")
    git(work, "commit", "-q", "-m", "base")
    base = git(work, "rev-parse", "HEAD")
    tests = work / "tests"
    tests.mkdir()
    (tests / "test_scan.py").write_text(
        'assert kinds("Welcome for Examplecorp.test (Customer ID: C0abc123)")\n', encoding="utf-8"
    )
    git(work, "add", "tests/test_scan.py")
    git(work, "commit", "-q", "-m", "head")
    head = git(work, "rev-parse", "HEAD")
    return work, base, head


def run(repo_dir: Path, base: str, head: str, names: Path, out: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo_dir), "--base", base, "--head", head,
         "--names", str(names), "--out", str(out)],
        capture_output=True, text=True, env=GIT_ENV,
    )


def names_file(tmp_path: Path, *names: str) -> Path:
    path = tmp_path / "names.txt"
    path.write_text("\n".join(names) + "\n", encoding="utf-8")
    return path


def test_export_has_no_git_and_no_name(repo, tmp_path):
    work, base, head = repo
    out = tmp_path / "scratch" / "redacted-demo-codex"
    result = run(work, base, head, names_file(tmp_path, "examplecorp.test", "C0abc123"), out)
    assert result.returncode == 0, result.stderr
    assert not (out / ".git").exists()
    text = (out / "tests" / "test_scan.py").read_text(encoding="utf-8")
    assert "examplecorp" not in text.lower() and "C0abc123" not in text
    assert "REDACTED-1" in text and "REDACTED-2" in text
    assert (out / "app.py").read_text(encoding="utf-8") == "print('hello')\n"  # untouched file kept


def test_diff_file_is_written_and_redacted(repo, tmp_path):
    work, base, head = repo
    out = tmp_path / "scratch" / "redacted-demo-codex"
    assert run(work, base, head, names_file(tmp_path, "examplecorp.test", "C0abc123"), out).returncode == 0
    diff = (out / ".review-swarm" / "diff.txt").read_text(encoding="utf-8")
    assert "+++ b/tests/test_scan.py" in diff  # the real diff of base..head
    assert "examplecorp" not in diff.lower() and "C0abc123" not in diff
    assert "REDACTED-1" in diff


def test_positive_control_without_names_the_name_is_present(repo, tmp_path):
    work, base, head = repo
    out = tmp_path / "scratch" / "plain"
    assert run(work, base, head, names_file(tmp_path, "nothing-matches-this"), out).returncode == 0
    assert "Examplecorp.test" in (out / "tests" / "test_scan.py").read_text(encoding="utf-8")
    assert "Examplecorp.test" in (out / ".review-swarm" / "diff.txt").read_text(encoding="utf-8")


def test_fails_when_a_name_is_in_a_file_path(repo, tmp_path):
    work, base, head = repo
    (work / "examplecorp-notes.txt").write_text("no name inside\n", encoding="utf-8")
    git(work, "add", "examplecorp-notes.txt")
    git(work, "commit", "-q", "-m", "path holds the name")
    head2 = git(work, "rev-parse", "HEAD")
    out = tmp_path / "scratch" / "redacted"
    result = run(work, base, head2, names_file(tmp_path, "examplecorp"), out)
    assert result.returncode == 1
    assert "examplecorp-notes.txt" in result.stderr
    assert not out.exists()  # a rejected export is removed


def test_redacts_a_non_ascii_name_in_another_case(repo, tmp_path):
    work, base, head = repo
    (work / "people.txt").write_text("Owner: JOSÉ GARCÍA\n", encoding="utf-8")
    git(work, "add", "people.txt")
    git(work, "commit", "-q", "-m", "unicode")
    head2 = git(work, "rev-parse", "HEAD")
    out = tmp_path / "scratch" / "redacted"
    result = run(work, base, head2, names_file(tmp_path, "José García"), out)
    assert result.returncode == 0, result.stderr
    assert (out / "people.txt").read_text(encoding="utf-8") == "Owner: REDACTED-1\n"
    assert "GARC" not in (out / ".review-swarm" / "diff.txt").read_text(encoding="utf-8")


def test_redacts_a_name_in_a_deleted_non_ascii_path(repo, tmp_path):
    work, base, _ = repo
    (work / "José.txt").write_text("x\n", encoding="utf-8")
    git(work, "add", "José.txt")
    git(work, "commit", "-q", "-m", "add")
    base2 = git(work, "rev-parse", "HEAD")
    git(work, "rm", "-q", "José.txt")
    git(work, "commit", "-q", "-m", "delete")
    head2 = git(work, "rev-parse", "HEAD")
    out = tmp_path / "scratch" / "redacted"
    result = run(work, base2, head2, names_file(tmp_path, "José"), out)
    assert result.returncode == 0, result.stderr
    diff = (out / ".review-swarm" / "diff.txt").read_text(encoding="utf-8")
    assert "REDACTED-1.txt" in diff  # git did not octal-quote the path, so it was redacted
    assert "Jos" not in diff


def test_refuses_a_symlink_that_points_outside(repo, tmp_path):
    work, base, _ = repo
    secret = tmp_path / "private.txt"
    secret.write_text("Examplecorp.test\n", encoding="utf-8")
    os.symlink(str(secret), work / "context")
    git(work, "add", "context")
    git(work, "commit", "-q", "-m", "link")
    head2 = git(work, "rev-parse", "HEAD")
    out = tmp_path / "scratch" / "redacted"
    result = run(work, base, head2, names_file(tmp_path, "examplecorp.test"), out)
    assert result.returncode != 0
    assert not out.exists()


def test_redacts_a_name_inside_a_binary_file(repo, tmp_path):
    work, base, head = repo
    (work / "blob.bin").write_bytes(b"\x00\x01Examplecorp.test\xff\xfe")
    git(work, "add", "blob.bin")
    git(work, "commit", "-q", "-m", "binary")
    head2 = git(work, "rev-parse", "HEAD")
    out = tmp_path / "scratch" / "redacted"
    result = run(work, base, head2, names_file(tmp_path, "examplecorp.test"), out)
    assert result.returncode == 0, result.stderr
    data = (out / "blob.bin").read_bytes()
    assert b"examplecorp" not in data.lower()
    assert data.startswith(b"\x00\x01REDACTED-1") and data.endswith(b"\xff\xfe")


def test_refuses_an_out_dir_inside_the_repo(repo, tmp_path):
    work, base, head = repo
    out = work / ".claude" / "worktrees" / "review-demo-codex"
    result = run(work, base, head, names_file(tmp_path, "examplecorp"), out)
    assert result.returncode == 2
    assert "outside the repo" in result.stderr
    assert not out.exists()


def test_refuses_an_existing_non_empty_out_dir(repo, tmp_path):
    work, base, head = repo
    out = tmp_path / "scratch" / "taken"
    out.mkdir(parents=True)
    (out / "keep.txt").write_text("someone's file\n", encoding="utf-8")
    result = run(work, base, head, names_file(tmp_path, "examplecorp"), out)
    assert result.returncode == 2
    assert "not empty" in result.stderr
    assert (out / "keep.txt").exists()


def test_refuses_an_empty_names_file(repo, tmp_path):
    work, base, head = repo
    result = run(work, base, head, names_file(tmp_path), tmp_path / "scratch" / "x")
    assert result.returncode == 2
    assert "no names" in result.stderr
