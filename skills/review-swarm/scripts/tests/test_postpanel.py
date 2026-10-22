"""Tests for postpanel.sh: the read-only post-panel check after orchestrator-run legs."""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
POSTPANEL = HERE / "postpanel.sh"
SNAPSHOTS = HERE / "snapshots.sh"

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
def panel(tmp_path):
    """A repo with an origin, a build branch, and snapshots made by snapshots.sh."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=GIT_ENV)
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", str(work)], check=True, env=GIT_ENV)
    git(work, "checkout", "-q", "-b", "feature")
    git(work, "remote", "add", "origin", str(origin))
    (work / "f.txt").write_text("one\n", encoding="utf-8")
    git(work, "add", "f.txt")
    git(work, "commit", "-q", "-m", "one")
    git(work, "push", "-q", "origin", "feature")
    sha = git(work, "rev-parse", "HEAD")
    scratch = tmp_path / "scratch"
    subprocess.run(
        ["bash", str(SNAPSHOTS), str(work), "p1", sha, str(scratch)],
        check=True, capture_output=True, text=True, env=GIT_ENV,
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_log = tmp_path / "gh.log"
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(f'#!/bin/bash\necho "$@" >> "{gh_log}"\n')
    fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IXUSR)
    env = {**GIT_ENV, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return {"work": work, "origin": origin, "scratch": scratch, "env": env, "gh_log": gh_log}


def run(panel, *legs: str):
    return subprocess.run(
        ["bash", str(POSTPANEL), str(panel["work"]), "p1", str(panel["scratch"]), *legs],
        capture_output=True, text=True, env=panel["env"],
    )


def snap(panel, leg: str) -> Path:
    return panel["work"] / ".claude" / "worktrees" / f"review-p1-{leg}"


def test_a_clean_panel_passes(panel):
    result = run(panel)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "branch: feature" in result.stdout
    assert "POST-PANEL: CLEAN" in result.stdout
    calls = panel["gh_log"].read_text()
    assert "pr list --author @me --state all --limit 5" in calls
    assert "search prs --author @me --created >=" in calls


def test_a_dirty_snapshot_is_flagged(panel):
    (snap(panel, "gemini") / "stray.txt").write_text("x\n", encoding="utf-8")

    result = run(panel)

    assert result.returncode == 1
    assert "REVIEW: snapshot gemini has 1 dirty entries" in result.stdout


def test_a_commit_in_a_snapshot_is_a_write_attempt(panel):
    target = snap(panel, "codex")
    (target / "f.txt").write_text("changed\n", encoding="utf-8")
    git(target, "commit", "-q", "-am", "leg wrote this")

    result = run(panel)

    assert result.returncode == 1
    assert "REVIEW: snapshot codex reflog shows a write" in result.stdout


def test_a_new_remote_branch_is_flagged(panel):
    git(panel["work"], "push", "-q", "origin", "feature:leg-branch")

    result = run(panel)

    assert result.returncode == 1
    assert "REVIEW: remote branches changed since the panel started" in result.stdout
    assert "leg-branch" in result.stdout


def test_a_dirty_build_worktree_is_shown_not_failed(panel):
    (panel["work"] / "mine.txt").write_text("orchestrator work\n", encoding="utf-8")

    result = run(panel)

    assert result.returncode == 0
    assert "mine.txt" in result.stdout


def test_missing_baseline_is_refused(panel):
    (panel["scratch"] / "refs-before.txt").unlink()

    result = run(panel)

    assert result.returncode == 2
    assert "refs-before.txt" in result.stderr
