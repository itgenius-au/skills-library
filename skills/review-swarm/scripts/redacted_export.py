#!/usr/bin/env python3
"""redacted_export.py - a git-free, redacted copy of a review checkpoint for external-provider legs.

usage: redacted_export.py --repo <repo> --base <commit> --head <commit> --names <file> --out <dir>

  --repo   the repo under review
  --base   the start of the diff range (for example the merge-base)
  --head   the checkpoint commit the legs read
  --names  one name, email or ID per line (blank lines and # comments are skipped)
  --out    a NEW or empty directory OUTSIDE the repo (one per leg, in your scratch directory)

It writes <out>/ from `git archive <head>` (no .git, so a leg cannot run `git diff` or `git show`
and read the committed text) and <out>/.review-swarm/diff.txt from `git diff <base> <head>`. Every
name is replaced, case-insensitively, with REDACTED-<n> (n = its line number among the names)
in every file, binary files included. Then it checks the export: a name left in any file, or in
a file path, fails the run and removes the export.

Exit: 0 clean (prints `hits=0`), 1 a name survived (export removed), 2 usage error.
Stdlib only. Why: redacting the files of a git snapshot is not enough. A repo-capable leg runs
`git diff` or `git show`, and git prints the committed text, so a name in the diff still reaches
the provider. This export has no git history to read.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


def fail(msg: str, code: int = 2) -> None:
    print(f"redacted_export: {msg}", file=sys.stderr)
    sys.exit(code)


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode != 0:
        fail(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def read_names(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"cannot read --names: {exc}")
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--names", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    names = read_names(args.names)
    if not names:
        fail(f"no names in {args.names}; list one name, email or ID per line")

    root = Path(git(args.repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    out = args.out.resolve()
    if out == root or root in out.parents:
        fail(f"--out must be outside the repo ({root}); use your scratch directory")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        fail(f"--out {out} exists and is not empty; pick a new directory")
    for rev in (args.base, args.head):
        git(args.repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")

    if not hasattr(tarfile, "data_filter"):
        fail("needs a Python with tarfile extraction filters (3.12+, or a security backport): "
             "without them a symlink in the repo could point the leg at files outside the export")

    # Longest name first, so a name that contains another is replaced whole. UTF-8 text is matched
    # as text (so JOSÉ matches José); other bytes are matched as bytes.
    order = sorted(range(len(names)), key=lambda i: -len(names[i]))
    text_patterns = [(re.compile(re.escape(names[i]), re.IGNORECASE), f"REDACTED-{i + 1}") for i in order]
    byte_patterns = [(re.compile(re.escape(names[i].encode()), re.IGNORECASE), f"REDACTED-{i + 1}".encode())
                     for i in order]

    def redact(data: bytes) -> tuple[bytes, int]:
        total = 0
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            for pattern, label in byte_patterns:
                data, n = pattern.subn(label, data)
                total += n
            return data, total
        for pattern, label in text_patterns:
            text, n = pattern.subn(label, text)
            total += n
        return text.encode("utf-8"), total

    def leaks(data: bytes) -> bool:
        return redact(data)[1] > 0

    out.mkdir(parents=True, exist_ok=True)
    try:
        archive = subprocess.Popen(["git", "-C", str(args.repo), "archive", "--format=tar", args.head],
                                   stdout=subprocess.PIPE)
        with tarfile.open(fileobj=archive.stdout, mode="r|") as tar:
            tar.extractall(out, filter="data")
        if archive.wait() != 0:
            raise RuntimeError(f"git archive {args.head} failed")
    except (tarfile.TarError, OSError, RuntimeError) as exc:
        shutil.rmtree(out, ignore_errors=True)
        fail(f"export failed, nothing kept: {exc}", code=1)

    # core.quotePath=false: otherwise git writes a non-ASCII path as octal escapes, and the name hides.
    review = out / ".review-swarm"
    review.mkdir(exist_ok=True)
    (review / "diff.txt").write_bytes(
        git(args.repo, "-c", "core.quotePath=false", "diff", "--no-color", "--no-ext-diff", args.base, args.head))

    files = replaced = 0
    for path in sorted(out.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        data, n = redact(path.read_bytes())
        if n:
            path.write_bytes(data)
            replaced += n
        files += 1

    hits = []
    for path in sorted(out.rglob("*")):
        rel = str(path.relative_to(out))
        if leaks(rel.encode("utf-8", "surrogateescape")):
            hits.append(f"{rel}: a name is in the file path")
        if path.is_symlink():
            if leaks(os.readlink(path).encode("utf-8", "surrogateescape")):
                hits.append(f"{rel}: a name is in the symlink target")
        elif path.is_file() and leaks(path.read_bytes()):
            hits.append(f"{rel}: a name is still in the file")
    if hits:
        shutil.rmtree(out, ignore_errors=True)
        for hit in hits:
            print(f"redacted_export: {hit}", file=sys.stderr)
        fail(f"{len(hits)} hit(s); export removed. Rename the file or redact by hand.", code=1)

    print(f"redacted export: {out} files={files} replaced={replaced} diff={review / 'diff.txt'} hits=0")


if __name__ == "__main__":
    main()
