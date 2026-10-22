"""Tests for snapshots.sh: create, move, baseline files, and refusals."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "snapshots.sh"

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
    """A repo with an origin (one pushed branch) and two commits; returns (repo, sha1, sha2)."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=GIT_ENV)
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", str(work)], check=True, env=GIT_ENV)
    git(work, "checkout", "-q", "-b", "main")
    git(work, "remote", "add", "origin", str(origin))
    (work / "f.txt").write_text("one\n", encoding="utf-8")
    git(work, "add", "f.txt")
    git(work, "commit", "-q", "-m", "one")
    sha1 = git(work, "rev-parse", "HEAD")
    (work / "f.txt").write_text("two\n", encoding="utf-8")
    git(work, "commit", "-q", "-am", "two")
    sha2 = git(work, "rev-parse", "HEAD")
    git(work, "push", "-q", "origin", "main")
    return work, sha1, sha2


def snapshots(repo_dir: Path, slug: str, sha: str, scratch: Path, *legs: str):
    return subprocess.run(
        ["bash", str(SCRIPT), str(repo_dir), slug, sha, str(scratch), *legs],
        capture_output=True, text=True, env=GIT_ENV,
    )


def snap_path(repo_dir: Path, slug: str, leg: str) -> Path:
    return repo_dir / ".claude" / "worktrees" / f"review-{slug}-{leg}"


def test_creates_one_detached_snapshot_per_default_leg(repo, tmp_path):
    work, sha1, _ = repo
    result = snapshots(work, "demo", sha1, tmp_path / "scratch")
    assert result.returncode == 0, result.stderr
    for leg in ("codex", "gemini", "fable"):
        snap = snap_path(work, "demo", leg)
        assert git(snap, "rev-parse", "HEAD") == sha1
        assert git(snap, "branch", "--show-current") == ""  # detached
        assert f"{leg}: {sha1[:7]}" in result.stdout
        assert "dirty=0" in result.stdout


def test_moves_existing_snapshots_to_the_next_checkpoint(repo, tmp_path):
    work, sha1, sha2 = repo
    scratch = tmp_path / "scratch"
    assert snapshots(work, "demo", sha1, scratch).returncode == 0
    result = snapshots(work, "demo", sha2, scratch)
    assert result.returncode == 0, result.stderr
    for leg in ("codex", "gemini", "fable"):
        assert git(snap_path(work, "demo", leg), "rev-parse", "HEAD") == sha2


def test_custom_legs_replace_the_defaults(repo, tmp_path):
    work, sha1, _ = repo
    result = snapshots(work, "demo", sha1, tmp_path / "scratch", "codex", "glm")
    assert result.returncode == 0, result.stderr
    assert snap_path(work, "demo", "codex").is_dir()
    assert snap_path(work, "demo", "glm").is_dir()
    assert not snap_path(work, "demo", "gemini").exists()


def test_records_baseline_each_run(repo, tmp_path):
    work, sha1, sha2 = repo
    scratch = tmp_path / "scratch"
    assert snapshots(work, "demo", sha1, scratch).returncode == 0
    refs = (scratch / "refs-before.txt").read_text(encoding="utf-8")
    assert refs.strip().endswith("refs/heads/main")
    assert git(work, "rev-parse", "origin/main") in refs
    stamp = (scratch / "panel-start.txt").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", stamp)

    git(work, "push", "-q", "origin", f"{sha1}:refs/heads/other")
    assert snapshots(work, "demo", sha2, scratch).returncode == 0
    assert "refs/heads/other" in (scratch / "refs-before.txt").read_text(encoding="utf-8")
    assert list(scratch.glob("refs-before.*")) == [scratch / "refs-before.txt"]  # no temp file left


def test_reports_a_dirty_snapshot(repo, tmp_path):
    work, sha1, _ = repo
    scratch = tmp_path / "scratch"
    assert snapshots(work, "demo", sha1, scratch).returncode == 0
    (snap_path(work, "demo", "codex") / "stray.txt").write_text("written by a leg\n", encoding="utf-8")
    result = snapshots(work, "demo", sha1, scratch)
    assert result.returncode == 0, result.stderr
    assert "codex: " in result.stdout and "dirty=1" in result.stdout
    assert "WARNING" in result.stderr


def test_refuses_an_unknown_commit_and_touches_nothing(repo, tmp_path):
    work, _, _ = repo
    result = snapshots(work, "demo", "deadbeef", tmp_path / "scratch")
    assert result.returncode == 2
    assert "not a commit" in result.stderr
    assert not (work / ".claude").exists()


def test_refuses_a_bad_slug(repo, tmp_path):
    work, sha1, _ = repo
    result = snapshots(work, "../evil", sha1, tmp_path / "scratch")
    assert result.returncode == 2
    assert "bad slug" in result.stderr


def test_refuses_a_directory_that_is_not_a_worktree(repo, tmp_path):
    work, sha1, _ = repo
    squatter = snap_path(work, "demo", "codex")
    squatter.mkdir(parents=True)
    result = snapshots(work, "demo", sha1, tmp_path / "scratch")
    assert result.returncode == 1
    assert "not a worktree" in result.stderr


def test_needs_all_four_arguments(repo, tmp_path):
    work, sha1, _ = repo
    result = subprocess.run(["bash", str(SCRIPT), str(work), "demo", sha1], capture_output=True, text=True)
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_fails_without_an_origin_remote(repo, tmp_path):
    work, sha1, _ = repo
    git(work, "remote", "remove", "origin")
    scratch = tmp_path / "scratch"
    result = snapshots(work, "demo", sha1, scratch)
    assert result.returncode != 0
    assert "cannot read remote refs" in result.stderr
    assert not (scratch / "refs-before.txt").exists()
    assert not snap_path(work, "demo", "codex").exists()
