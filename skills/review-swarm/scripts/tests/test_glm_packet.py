"""Tests for glm_packet.py: what it builds and, above all, what it refuses."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "glm_packet.py"
NOTE = (
    "YOU HAVE NO SHELL AND NO REPOSITORY ACCESS. Report `DIR: inlined`. "
    "The material below is the ONLY code you can see; cite only its line numbers."
)


def run(tmp_path: Path, body: str, inline: dict[str, str], *extra: str):
    body_file = tmp_path / "body.md"
    body_file.write_text(body, encoding="utf-8")
    args = [sys.executable, str(SCRIPT), "--body", str(body_file), "--out", str(tmp_path / "packet.txt")]
    for name, text in inline.items():
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        args += ["--inline", str(path)]
    args += list(extra)
    return subprocess.run(args, capture_output=True, text=True)


REPO_NOTE = (
    "The material below is inlined for reference. You ALSO have a shell and the repository "
    "in your working directory: read and grep it to verify every claim, and report the "
    "directory you read as `DIR:`."
)


def test_repo_leg_swaps_the_no_shell_note_for_the_repo_note(tmp_path):
    result = run(tmp_path, "Review this plan.\n", {"plan.md": "# Plan\n"}, "--repo-leg")
    assert result.returncode == 0, result.stderr
    packet = (tmp_path / "packet.txt").read_text(encoding="utf-8")
    assert NOTE not in packet
    assert "NO SHELL" not in packet
    assert packet.index("Review this plan.") < packet.index(REPO_NOTE) < packet.index("# Plan")


def test_repo_leg_keeps_every_refusal(tmp_path):
    result = run(tmp_path, "See the diff below.\n", {}, "--repo-leg")
    assert result.returncode == 1
    assert "REFUSED" in result.stderr


def test_builds_body_note_and_headers_in_order(tmp_path):
    result = run(tmp_path, "Review this.\n", {"a.py": "print(1)\n", "b.diff": "+x\n"})
    assert result.returncode == 0, result.stderr
    packet = (tmp_path / "packet.txt").read_text(encoding="utf-8")
    a, b = str(tmp_path / "a.py"), str(tmp_path / "b.diff")
    assert packet.startswith("Review this.\n")
    assert packet.index("Review this.") < packet.index(NOTE) < packet.index(f"=== {a} ===")
    assert packet.index(f"=== {a} ===") < packet.index("print(1)") < packet.index(f"=== {b} ===")
    assert packet.index(f"=== {b} ===") < packet.index("+x")


def test_number_lines_prefixes_each_inlined_line(tmp_path):
    result = run(tmp_path, "Review this.", {"a.py": "one\ntwo\n"}, "--number-lines")
    assert result.returncode == 0, result.stderr
    packet = (tmp_path / "packet.txt").read_text(encoding="utf-8")
    assert "1: one\n2: two\n" in packet


def test_body_only_packet_without_promises_is_allowed(tmp_path):
    result = run(tmp_path, "Stress-test this decision: use plan A, not B.", {})
    assert result.returncode == 0, result.stderr
    assert NOTE in (tmp_path / "packet.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("text", ["", "\n", "   \n\t\n"])
def test_refuses_empty_inlined_file(tmp_path, text):
    result = run(tmp_path, "Review this.", {"a.diff": text})
    assert result.returncode == 1
    assert "empty" in result.stderr
    assert not (tmp_path / "packet.txt").exists()


def test_refuses_when_any_one_of_several_inlined_files_is_empty(tmp_path):
    result = run(tmp_path, "Review this.", {"a.py": "x = 1\n", "b.diff": ""})
    assert result.returncode == 1
    assert "b.diff" in result.stderr


def test_missing_inlined_file_is_a_usage_error(tmp_path):
    body = tmp_path / "body.md"
    body.write_text("Review this.", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--body", str(body), "--inline", str(tmp_path / "nope.diff"),
         "--out", str(tmp_path / "packet.txt")],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "cannot read" in result.stderr
    assert not (tmp_path / "packet.txt").exists()


def test_refuses_empty_body(tmp_path):
    result = run(tmp_path, "  \n", {"a.py": "x = 1\n"})
    assert result.returncode == 1
    assert "body is empty" in result.stderr


def test_refuses_packet_over_max_bytes(tmp_path):
    result = run(tmp_path, "Review this.", {"big.diff": "+" + "x" * 500 + "\n"}, "--max-bytes", "400")
    assert result.returncode == 1
    assert "over the 400 byte limit" in result.stderr
    assert not (tmp_path / "packet.txt").exists()


def test_default_limit_is_60000_bytes(tmp_path):
    ok = run(tmp_path, "Review this.", {"a.diff": "+" + "x" * 50000 + "\n"})
    assert ok.returncode == 0, ok.stderr
    too_big = run(tmp_path, "Review this.", {"a.diff": "+" + "x" * 60000 + "\n"})
    assert too_big.returncode == 1
    assert "60000 byte limit" in too_big.stderr


def test_size_limit_counts_bytes_not_characters(tmp_path):
    # 300 two-byte characters: 300 characters, 600 bytes, plus the note.
    result = run(tmp_path, "Review this.", {"a.txt": "é" * 300 + "\n"}, "--max-bytes", "700")
    assert result.returncode == 1


@pytest.mark.parametrize(
    "phrase",
    ["included below", "excerpt attached", "See the diff below", "The FULL TEXT FOLLOWS"],
)
def test_refuses_body_that_promises_content_when_nothing_is_inlined(tmp_path, phrase):
    result = run(tmp_path, f"Review the change ({phrase}).", {})
    assert result.returncode == 1
    assert "promises content" in result.stderr


def test_promise_phrase_is_fine_when_the_content_is_inlined(tmp_path):
    result = run(tmp_path, "The diff is included below.", {"a.diff": "+x\n"})
    assert result.returncode == 0, result.stderr


def test_refusal_removes_a_stale_packet(tmp_path):
    (tmp_path / "packet.txt").write_text("stale packet from an earlier run", encoding="utf-8")
    result = run(tmp_path, "Review this.", {"a.diff": ""})
    assert result.returncode == 1
    assert not (tmp_path / "packet.txt").exists()
